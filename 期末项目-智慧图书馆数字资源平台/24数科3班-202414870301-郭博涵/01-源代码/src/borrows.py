# -*- coding: utf-8 -*-
"""读者与借阅业务模块。

borrow_logs 采用普通集合（不是固定集合）：
借阅记录需要更新 return_date/status 字段，而固定集合不允许改变文档大小；
同时它还要支持聚合与按 hashed 分片键水平切分，固定集合与 time-series 都不满足。
"""
from datetime import datetime, timedelta, timezone

import audit
import config
from db import get_collection

DEFAULT_LOAN_DAYS = 30
CST = timezone(timedelta(hours=8))


def _readers():
    return get_collection(config.COL_READERS)


def _borrows():
    return get_collection(config.COL_BORROWS)


def find_reader(card_no):
    return _readers().find_one({"card_no": card_no}, {"_id": 0})


def list_readers(college=None, limit=10):
    query = {"college": college} if college else {}
    cur = _readers().find(query, {"_id": 0, "card_no": 1, "name": 1,
                                  "college": 1, "level": 1}).limit(limit)
    return list(cur)


def borrow(reader_card, isbn, days=DEFAULT_LOAN_DAYS):
    """借书：库存 -1、借阅次数 +1，并写入一条借阅记录。"""
    books = get_collection(config.COL_BOOKS)
    book = books.find_one({"isbn": isbn})
    if not book:
        raise ValueError("图书不存在：%s" % isbn)
    if not find_reader(reader_card):
        raise ValueError("读者不存在：%s" % reader_card)
    if book.get("stock", 0) <= 0:
        raise ValueError("库存不足：《%s》" % book.get("title"))

    now = datetime.now(CST)
    log = {
        "borrow_date": now,
        "reader_card": reader_card,
        "book_isbn": isbn,
        "status": "借出",
        "duration_days": days,
        "return_date": None,
    }
    res = _borrows().insert_one(log)
    books.update_one({"isbn": isbn}, {"$inc": {"stock": -1, "borrow_count": 1}})
    audit.write_audit("BORROW", isbn, "读者 %s 借出，%d 天" % (reader_card, days))
    return str(res.inserted_id)


def return_book(log_id):
    """还书：写回归还时间并把状态改为已归还，同时库存 +1。"""
    from bson import ObjectId
    oid = ObjectId(log_id)
    log = _borrows().find_one({"_id": oid})
    if not log:
        raise ValueError("借阅记录不存在：%s" % log_id)
    if log.get("status") == "已归还":
        raise ValueError("该记录已归还")

    now = datetime.now(CST)
    _borrows().update_one({"_id": oid}, {"$set": {"status": "已归还", "return_date": now}})
    get_collection(config.COL_BOOKS).update_one(
        {"isbn": log["book_isbn"]}, {"$inc": {"stock": 1}})
    audit.write_audit("RETURN", log["book_isbn"], "记录 %s 归还" % log_id)
    return now


def logs_of_reader(card_no, limit=10):
    cur = _borrows().find({"reader_card": card_no},
                          {"_id": 1, "book_isbn": 1, "borrow_date": 1,
                           "return_date": 1, "status": 1}) \
                    .sort("borrow_date", -1).limit(limit)
    return list(cur)


def overdue(limit=10):
    """逾期未还：状态为借出且借阅时间超过 duration_days。"""
    pipe = [
        {"$match": {"status": "借出"}},
        {"$addFields": {"due": {"$add": ["$borrow_date",
                                        {"$multiply": ["$duration_days", 86400000]}]}}},
        {"$match": {"due": {"$lt": datetime.now(CST)}}},
        {"$sort": {"due": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "reader_card": 1, "book_isbn": 1, "due": 1}},
    ]
    return list(_borrows().aggregate(pipe))
