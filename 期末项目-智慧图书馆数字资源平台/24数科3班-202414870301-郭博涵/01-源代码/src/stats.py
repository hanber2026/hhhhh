# -*- coding: utf-8 -*-
"""统计报表模块：全部使用聚合管道完成，对应任务三的 5 项统计。"""
from datetime import datetime, timedelta, timezone

import audit
import config
from db import get_collection

CST = timezone(timedelta(hours=8))


def category_stats():
    """按类别统计藏书品种、册数、均价、均分。"""
    pipe = [
        {"$group": {
            "_id": "$category",
            "book_count": {"$sum": 1},
            "stock_total": {"$sum": "$stock"},
            "avg_price": {"$avg": "$price"},
            "avg_rating": {"$avg": "$rating"},
        }},
        {"$sort": {"stock_total": -1}},
        {"$project": {"_id": 0, "category": "$_id", "book_count": 1,
                      "stock_total": 1,
                      "avg_price": {"$round": ["$avg_price", 2]},
                      "avg_rating": {"$round": ["$avg_rating", 2]}}},
    ]
    return list(get_collection(config.COL_BOOKS).aggregate(pipe))


def college_top5():
    """借阅量最高的 5 个学院：borrow_logs -> readers 关联 -> 分组。"""
    pipe = [
        {"$group": {"_id": "$reader_card", "times": {"$sum": 1}}},
        {"$lookup": {"from": config.COL_READERS, "localField": "_id",
                     "foreignField": "card_no", "as": "reader"}},
        {"$unwind": "$reader"},
        {"$group": {"_id": "$reader.college", "times": {"$sum": "$times"},
                    "readers": {"$sum": 1}}},
        {"$sort": {"times": -1}},
        {"$limit": 5},
        {"$project": {"_id": 0, "college": "$_id", "times": 1, "readers": 1}},
    ]
    return list(get_collection(config.COL_BORROWS).aggregate(pipe))


def month_trend(months=12):
    """最近若干个月的借阅量趋势（按本地时区归月）。"""
    since = datetime.now(CST) - timedelta(days=months * 31)
    pipe = [
        {"$match": {"borrow_date": {"$gte": since}}},
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m", "date": "$borrow_date",
                                              "timezone": "+08:00"}},
                    "times": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    return [{"month": r["_id"], "times": r["times"]}
            for r in get_collection(config.COL_BORROWS).aggregate(pipe)]


def top_books(limit=10):
    """借阅次数最多的图书，并带出馆藏位置。"""
    pipe = [
        {"$sort": {"borrow_count": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "title": 1, "borrow_count": 1,
                      "floor": "$location.floor", "shelf": "$location.shelf"}},
    ]
    return list(get_collection(config.COL_BOOKS).aggregate(pipe))


def save_category_stats():
    """把类别统计结果写回新的集合 category_stats（$out 覆盖写入）。"""
    pipe = [
        {"$group": {"_id": "$category", "book_count": {"$sum": 1},
                    "stock_total": {"$sum": "$stock"},
                    "avg_price": {"$avg": "$price"},
                    "avg_rating": {"$avg": "$rating"}}},
        {"$sort": {"stock_total": -1}},
        {"$project": {"_id": 0, "category": "$_id", "book_count": 1,
                      "stock_total": 1,
                      "avg_price": {"$round": ["$avg_price", 2]},
                      "avg_rating": {"$round": ["$avg_rating", 2]}}},
        {"$out": config.COL_CATEGORY_STATS},
    ]
    list(get_collection(config.COL_BOOKS).aggregate(pipe))
    n = get_collection(config.COL_CATEGORY_STATS).count_documents({})
    audit.write_audit("EXPORT", config.COL_CATEGORY_STATS, "分类统计写入 %d 条" % n)
    return n
