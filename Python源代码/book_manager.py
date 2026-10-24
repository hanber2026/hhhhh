#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
book_manager.py —— 图书管理模块（ST-5.3 图书增删改查、条件检索、评分排行）
                                           （ST-5.4 分类统计/畅销榜另见 stat_manager.py）

封装的方法：insert_one / insert_many / find / find_one / update_one /
            delete_one / delete_many，以及排序、投影、分页、计数等组合查询。
所有数据库连接统一来自 mongodb_connect.py。
"""
from datetime import datetime

from pymongo import DESCENDING, ASCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

from mongodb_connect import get_collection, get_database

# ---------------------------------------------------------------- 基础封装
def books():
    """books 集合。"""
    return get_collection("books")


def insert_one(book):
    """新增一本图书，返回插入结果（含 inserted_id）。isbn 唯一索引冲突时返回 None。"""
    try:
        return books().insert_one(dict(book))
    except DuplicateKeyError as err:
        print("  [失败] ISBN 已存在，唯一索引拒绝插入：%s" % err.details.get("keyValue"))
        return None


def insert_many(book_list):
    """批量新增图书，返回插入结果。"""
    return books().insert_many([dict(b) for b in book_list])


def find_one(isbn):
    """按 ISBN 精确查找一本图书。"""
    return books().find_one({"isbn": isbn})


def find(condition=None, projection=None, sort=None, limit=0, skip=0):
    """通用查询：条件 + 投影 + 排序 + 分页，返回游标（可直接迭代）。"""
    cur = books().find(condition or {}, projection)
    if sort:
        cur = cur.sort(sort)
    if skip:
        cur = cur.skip(skip)
    if limit:
        cur = cur.limit(limit)
    return cur


def update_one(isbn, changes):
    """修改一本图书（$set 部分字段），返回 UpdateResult（matched_count / modified_count）。"""
    return books().update_one({"isbn": isbn}, {"$set": dict(changes)})


def delete_one(isbn=None, condition=None):
    """删除一本图书：优先按 ISBN，否则用自定义条件。"""
    return books().delete_one({"isbn": isbn} if isbn else condition)


def delete_many(condition):
    """按条件批量删除图书。"""
    return books().delete_many(condition)


# ---------------------------------------------------------------- 业务查询
def search_by_price(min_price=None, max_price=None):
    """价格区间检索（$gt / $gte / $lt / $lte）。"""
    cond = {}
    if min_price is not None:
        cond["$gte"] = min_price
    if max_price is not None:
        cond["$lte"] = max_price
    return list(find({"price": cond} if cond else {},
                     {"_id": 0, "isbn": 1, "title": 1, "price": 1, "stock": 1, "borrow_count": 1},
                     sort=[("price", DESCENDING)]))


def search_by_keyword(keyword, fields=("title", "author", "publisher"), page=1, size=3):
    """多字段模糊检索 + 分页，返回 (命中总数, 页数, 当前页文档列表)。"""
    cond = {"$or": [{f: {"$regex": keyword, "$options": "i"}} for f in fields]}
    total = books().count_documents(cond)
    pages = max(1, (total + size - 1) // size)
    page = min(max(1, page), pages)
    docs = list(find(cond, {"_id": 0, "isbn": 1, "title": 1, "author": 1, "price": 1, "stock": 1},
                     sort=[("borrow_count", DESCENDING)], limit=size, skip=(page - 1) * size))
    return total, pages, page, docs


def search_by_tag(tag):
    """按标签检索（数组字段的等值匹配 = 数组中包含该元素）。"""
    return list(find({"tags": tag}, {"_id": 0, "isbn": 1, "title": 1, "tags": 1}, sort=[("rating", DESCENDING)]))


def in_stock_only():
    """有库存的图书（也可以直接读视图 book_in_stock）。"""
    return list(find({"stock": {"$gt": 0}}, {"_id": 0, "isbn": 1, "title": 1, "stock": 1},
                     sort=[("stock", DESCENDING)]))


def rating_ranking(top_n=5, min_stock=None):
    """评分排行：sort + limit + 投影，可选只看有库存的书。"""
    cond = {} if min_stock is None else {"stock": {"$gte": min_stock}}
    return list(find(cond, {"_id": 0, "title": 1, "rating": 1, "borrow_count": 1},
                     sort=[("rating", DESCENDING), ("borrow_count", DESCENDING)], limit=top_n))


def borrow_ranking(top_n=5):
    """借阅次数（畅销）排行。"""
    return list(find({}, {"_id": 0, "isbn": 1, "title": 1, "borrow_count": 1, "price": 1},
                     sort=[("borrow_count", DESCENDING)], limit=top_n))


def categories():
    """全部图书类别（distinct）。"""
    return sorted(books().distinct("category"))


def count(condition=None):
    """满足条件的图书数量。"""
    return books().count_documents(condition or {})


def stock_statistics():
    """库存概况：总量、有货种类、售罄种类、总库存册数。"""
    pipe = [{"$group": {"_id": None,
                        "kinds": {"$sum": 1},
                        "in_stock": {"$sum": {"$cond": [{"$gt": ["$stock", 0]}, 1, 0]}},
                        "zero": {"$sum": {"$cond": [{"$eq": ["$stock", 0]}, 1, 0]}},
                        "total_stock": {"$sum": "$stock"},
                        "avg_price": {"$avg": "$price"}}}]
    row = next(iter(books().aggregate(pipe)), None) or {}
    row.pop("_id", None)
    return row


def low_stock(threshold=10):
    """库存不足 threshold 本的图书（补货提醒）。"""
    return list(find({"stock": {"$lt": threshold}}, {"_id": 0, "isbn": 1, "title": 1, "stock": 1},
                     sort=[("stock", ASCENDING)]))


def new_book(isbn, title, author, publisher, category, price, stock, rating=5.0,
             tags=None, publish_date=None, borrow_count=0):
    """组装一本新书文档（缺省字段自动补齐，日期用 datetime）。"""
    return {
        "isbn": isbn, "title": title, "author": author, "publisher": publisher,
        "category": category, "price": float(price), "stock": int(stock), "rating": float(rating),
        "tags": tags or [], "publish_date": publish_date or datetime(2026, 1, 1),
        "borrow_count": int(borrow_count),
    }


def view_book_in_stock(limit=5):
    """读取视图 book_in_stock 的前若干条，演示视图与普通集合用法一致。"""
    return list(get_database()["book_in_stock"].find(
        {}, {"_id": 0, "isbn": 1, "title": 1, "stock": 1}).sort("stock", DESCENDING).limit(limit))


if __name__ == "__main__":
    print("图书总数：%d 本，类别：%s" % (count(), "、".join(categories())))
    print("评分排行前 3：%s" % [(d["title"], d["rating"]) for d in rating_ranking(3)])
    try:
        print("库存概况：%s" % stock_statistics())
    except PyMongoError as err:
        print("查询失败：%s" % err)
