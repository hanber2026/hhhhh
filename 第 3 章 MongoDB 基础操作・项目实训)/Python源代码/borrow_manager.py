#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
borrow_manager.py —— 借阅管理模块（ST-5.3 借阅登记、归还处理、逾期查询）
封装的方法：insert_one / update_many / find / count_documents / delete_many
所有数据库连接统一来自 mongodb_connect.py。

⚠ 关于 borrow_logs（时间序列集合）的写入限制，本模块采用了两种策略：
   · 借阅登记：insert_one 追加一条新流水（timeField=borrow_date, metaField=reader_card）
   · 归还处理：时间序列集合不允许更新非 metaField 字段
     （报错 “Cannot perform an update on a time-series collection which updates a field
       that is not the metaField 'reader_card'”），因此不原地修改 return_date/status，
     而是追加一条 borrow_date 相同、状态为“已归还”的新记录，读取时以最新一条为准；
   · update_many 用于维护 books 集合（库存、累计借阅次数）这类普通集合。
"""
from datetime import datetime, timedelta

from pymongo import DESCENDING
from pymongo.errors import PyMongoError

from mongodb_connect import get_collection

BORROW_DAYS = 30        # 借期 30 天
# 逾期判定：借期已过仍未归还，或状态本身为“逾期”
OVERDUE_MATCH = {"$or": [{"status": "逾期"},
                         {"status": "借出",
                          "borrow_date": {"$lt": datetime.now() - timedelta(days=BORROW_DAYS)}}]}


def logs():
    """借阅流水集合（时间序列）。"""
    return get_collection("borrow_logs")


def books():
    """图书集合。"""
    return get_collection("books")


def book_title_map():
    """ISBN -> 书名 的映射，用于输出时补全书名。"""
    return {d["isbn"]: d for d in books().find({}, {"_id": 0, "isbn": 1, "title": 1})}


def reader_map():
    """借阅证号 -> 读者文档。"""
    return {d["card_no"]: d for d in get_collection("readers").find({})}


def count(condition=None):
    """借阅流水总数/条件计数。"""
    return logs().count_documents(condition or {})


def find(condition=None, projection=None, limit=10):
    """条件查询借阅流水，按借阅时间倒序。"""
    cur = logs().find(condition or {}, projection or
                      {"_id": 0, "reader_card": 1, "book_isbn": 1, "borrow_date": 1,
                       "return_date": 1, "status": 1}).sort("borrow_date", DESCENDING)
    return list(cur.limit(limit) if limit else cur)


def borrow(card_no, isbn, days=BORROW_DAYS, now=None):
    """借阅登记：校验读者/图书/库存 -> 追加流水 -> 库存 -1、累计借阅 +1。返回 (成功?, 说明)。"""
    now = now or datetime.now().replace(microsecond=0)
    reader = get_collection("readers").find_one({"card_no": card_no})
    if not reader:
        return False, "读者 %s 不存在" % card_no
    book = books().find_one({"isbn": isbn})
    if not book:
        return False, "图书 %s 不存在" % isbn
    if book["stock"] <= 0:
        return False, "《%s》库存为 0，无法借阅" % book["title"]
    # 同一读者同一本书不允许重复在借
    if logs().find_one({"reader_card": card_no, "book_isbn": isbn, "status": {"$in": ["借出", "逾期"]}}):
        return False, "[提示] 未重复借阅：读者 %s 已有《%s》在借记录（同一图书不可重复在借）" % (card_no, book["title"])
    res = logs().insert_one({"reader_card": card_no, "book_isbn": isbn, "borrow_date": now,
                             "return_date": None, "status": "借出"})
    books().update_one({"isbn": isbn}, {"$inc": {"stock": -1, "borrow_count": 1}})
    return True, ("借阅成功（流水 _id=%s）：读者 %s %s，图书《%s》，借期 %d 天，应还 %s；"
                  "库存与累计借阅已通过 update_many/update_one 更新"
                  % (res.inserted_id, card_no, reader["name"], book["title"], days,
                     (now + timedelta(days=days)).strftime("%Y-%m-%d")))


def borrow_batch(items, days=BORROW_DAYS):
    """批量借阅（逐条调用 borrow），返回成功条数。"""
    ok = 0
    for card_no, isbn in items:
        flag, msg = borrow(card_no, isbn, days)
        print("   " + msg)
        ok += 1 if flag else 0
    return ok


def return_book(card_no, isbn, now=None):
    """归还处理：追加“已归还”状态记录 + 库存回补，返回 (成功?, 说明)。"""
    now = now or datetime.now().replace(microsecond=0)
    rec = logs().find_one({"reader_card": card_no, "book_isbn": isbn, "status": {"$in": ["借出", "逾期"]}},
                          sort=[("borrow_date", DESCENDING)])
    if not rec:
        return False, "读者 %s 没有《%s》的在借记录" % (card_no, isbn)
    days = (now - rec["borrow_date"]).days
    logs().insert_one({"reader_card": card_no, "book_isbn": isbn, "borrow_date": rec["borrow_date"],
                       "return_date": now, "status": "已归还", "operator": "borrow_manager.return_book"})
    res = books().update_many({"isbn": isbn}, {"$inc": {"stock": 1}})     # update_many 维护库存
    return True, ("归还成功：读者 %s 归还《%s》，借阅 %d 天%s；库存回补 +1（受影响 %d 条）"
                  % (card_no, book_title_map().get(isbn, {}).get("title", isbn), days,
                     "（逾期 %d 天）" % (days - BORROW_DAYS) if days > BORROW_DAYS else "",
                     res.modified_count))


def overdue_list(days=BORROW_DAYS, limit=20):
    """逾期查询：借出超过借期仍未归还的记录，附逾期天数。"""
    cond = {"status": "借出", "borrow_date": {"$lt": datetime.now() - timedelta(days=days)}}
    titles, readers = book_title_map(), reader_map()
    rows = []
    for d in logs().find(cond, {"_id": 0, "reader_card": 1, "book_isbn": 1, "borrow_date": 1, "status": 1}) \
                   .sort("borrow_date", 1).limit(limit):
        passed = (datetime.now() - d["borrow_date"]).days
        rows.append({"reader_card": d["reader_card"],
                     "reader_name": readers.get(d["reader_card"], {}).get("name", "-"),
                     "title": titles.get(d["book_isbn"], {}).get("title", d["book_isbn"]),
                     "borrow_date": d["borrow_date"].strftime("%Y-%m-%d"),
                     "overdue_days": passed - days})
    return rows


def status_distribution():
    """借阅状态分布（$sortByCount）。"""
    pipe = [{"$sortByCount": "$status"},
            {"$project": {"_id": 0, "status": "$_id", "count": 1}}]
    return list(logs().aggregate(pipe))


def reader_history(card_no, limit=10):
    """某读者的借阅历史（find + sort）。"""
    return find({"reader_card": card_no}, limit=limit)


def active_borrows(limit=10):
    """当前在借（未归还）记录。"""
    return find({"status": {"$in": ["借出", "逾期"]}}, limit=limit)


def delete_many(condition):
    """按条件清理借阅流水（时间序列集合支持 delete，查询条件需带 metaField）。"""
    try:
        return logs().delete_many(condition)
    except PyMongoError as err:
        return "删除失败：%s" % err


if __name__ == "__main__":
    print("借阅流水总数：%d 条" % count())
    print("状态分布：%s" % status_distribution())
    print("逾期记录：%s" % overdue_list(limit=5))
