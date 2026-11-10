# -*- coding: utf-8 -*-
"""图书业务模块：检索、新增、删除。

检索条件都走任务三建立好的索引，示例：
  category + price  -> ix_category_price
  tags $all         -> ix_tags
  title 前缀正则     -> ix_title
"""
from datetime import datetime

import audit
import config
from db import get_collection


def _books():
    return get_collection(config.COL_BOOKS)


def search(keyword=None, category=None, price_min=None, price_max=None,
           tag=None, limit=20):
    """组合条件检索图书，返回按价格升序的文档列表。"""
    query = {}
    if category:
        query["category"] = category
    if price_min is not None or price_max is not None:
        price = {}
        if price_min is not None:
            price["$gte"] = float(price_min)
        if price_max is not None:
            price["$lte"] = float(price_max)
        query["price"] = price
    if tag:
        # $all 命中多标签，数组元素任一匹配即可（本例只传一个标签）
        query["tags"] = {"$all": [tag]}
    if keyword:
        # 书名模糊查询用正则；命中 ix_title 前缀扫描，中文分词则依赖外部方案
        query["title"] = {"$regex": keyword}

    proj = {"_id": 0, "isbn": 1, "title": 1, "author": 1,
            "category": 1, "price": 1, "stock": 1, "rating": 1,
            "location": 1, "tags": 1}
    cur = _books().find(query, proj).sort("price", 1).limit(limit)
    return list(cur)


def get_by_isbn(isbn):
    return _books().find_one({"isbn": isbn}, {"_id": 0})


def top_rated(limit=10):
    """评分最高的若干本，只返回 title/author/rating 三个字段。"""
    cur = _books().find({}, {"_id": 0, "title": 1, "author": 1, "rating": 1}) \
                  .sort("rating", -1).limit(limit)
    return list(cur)


def add_book(doc):
    """新增图书。isbn 上有唯一索引，重复插入会抛 DuplicateKeyError。"""
    doc.setdefault("borrow_count", 0)
    doc.setdefault("tags", [])
    if isinstance(doc.get("publish_date"), str):
        doc["publish_date"] = datetime.fromisoformat(doc["publish_date"])
    _books().insert_one(dict(doc))
    audit.write_audit("CREATE", doc["isbn"], "新增图书 %s" % doc.get("title", ""))
    return doc["isbn"]


def delete_book(isbn):
    """删除图书并写审计。返回删除条数。"""
    res = _books().delete_one({"isbn": isbn})
    if res.deleted_count:
        audit.write_audit("DELETE", isbn, "删除图书 1 条")
    return res.deleted_count


def missing_tags():
    """没有 tags 字段的图书（用于数据质量核查）。"""
    cur = _books().find({"tags": {"$exists": False}}, {"_id": 0, "isbn": 1, "title": 1})
    return list(cur)
