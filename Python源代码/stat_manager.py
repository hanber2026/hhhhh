#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stat_manager.py —— 统计分析模块（ST-5.4 聚合管道编程：分类统计、借阅趋势、畅销榜）
全部统计通过 Collection.aggregate() 的聚合管道在服务端完成，
包括 $group / $sort / $lookup / $unwind / $facet / $addFields / $dateToString / $merge。
所有数据库连接统一来自 mongodb_connect.py。
"""
from pymongo import DESCENDING

from mongodb_connect import get_collection


def books():
    return get_collection("books")


def logs():
    return get_collection("borrow_logs")


def readers():
    return get_collection("readers")


# ------------------------------------------------------ 1. 分类统计（ST-5.4）
def category_statistics(write_back=False):
    """按类别分组：图书数量、库存总量、平均价格、平均评分，按库存总量降序。

    write_back=True 时用 $merge 把结果写回 category_stats 集合（需要 category 上的唯一索引）。
    """
    pipe = [
        {"$group": {"_id": "$category",
                    "book_count": {"$sum": 1},
                    "stock_total": {"$sum": "$stock"},
                    "avg_price": {"$avg": "$price"},
                    "avg_rating": {"$avg": "$rating"}}},
        {"$project": {"_id": 0, "category": "$_id", "book_count": 1, "stock_total": 1,
                      "avg_price": {"$round": ["$avg_price", 2]},
                      "avg_rating": {"$round": ["$avg_rating", 2]}}},
        {"$sort": {"stock_total": DESCENDING, "category": 1}},
    ]
    if write_back:
        stats = get_collection("category_stats")
        stats.create_index([("category", 1)], unique=True, name="uk_category")
        pipe.append({"$merge": {"into": "category_stats", "on": "category",
                                "whenMatched": "merge", "whenNotMatched": "insert"}})
        return list(books().aggregate(pipe))       # $merge 阶段返回空结果
    return list(books().aggregate(pipe))


def publisher_top():
    """出版社 Top5：$group + $topN 累加器。"""
    pipe = [
        {"$group": {"_id": None,
                    "top5": {"$topN": {"n": 5, "sortBy": {"count": DESCENDING, "publisher": 1},
                                       "output": {"publisher": "$_id", "count": "$count"}}}}},
        {"$unwind": "$top5"},
        {"$replaceRoot": {"newRoot": "$top5"}},
        {"$project": {"_id": 0}},
    ]
    # 先分组再取 topN，两步走更直观
    pipe = [
        {"$group": {"_id": "$publisher", "count": {"$sum": 1}, "avg_price": {"$avg": "$price"}}},
        {"$sort": {"count": DESCENDING, "_id": 1}},
        {"$limit": 5},
        {"$project": {"_id": 0, "publisher": "$_id", "count": 1,
                      "avg_price": {"$round": ["$avg_price", 2]}}},
    ]
    return list(books().aggregate(pipe))


# ------------------------------------------------------ 2. 借阅趋势（ST-5.4）
def borrow_trend(by="year"):
    """借阅趋势：按年/月分组统计借阅量，格式化为“2024年”“2024-11”。"""
    if by == "year":
        fmt, label = "%Y年", "年份"
    else:
        fmt, label = "%Y-%m", "月份"
    pipe = [
        {"$group": {"_id": {"$dateToString": {"format": fmt, "date": "$borrow_date"}},
                    "count": {"$sum": 1},
                    "readers": {"$addToSet": "$reader_card"}}},
        {"$project": {"_id": 0, "period": "$_id", "count": 1, "readers": {"$size": "$readers"}}},
        {"$sort": {"period": 1}},
    ]
    return list(logs().aggregate(pipe))


def year_trend_with_year_operator():
    """$year 取年份后再格式化（对照写法）：2024/2025 各自借阅量。"""
    pipe = [
        {"$group": {"_id": {"$year": "$borrow_date"}, "count": {"$sum": 1}}},
        {"$project": {"_id": 0, "year": "$_id",
                      "label": {"$concat": [{"$toString": "$_id"}, "年"]}, "count": 1}},
        {"$sort": {"year": 1}},
    ]
    return list(logs().aggregate(pipe))


# ------------------------------------------------------ 3. 畅销榜（ST-5.4）
def bestseller(top_n=5):
    """畅销榜：取借阅次数最多的图书（books.borrow_count 降序）。"""
    pipe = [
        {"$sort": {"borrow_count": DESCENDING}},
        {"$limit": top_n},
        {"$project": {"_id": 0, "isbn": 1, "title": 1, "borrow_count": 1, "price": 1, "rating": 1,
                      "sales": {"$round": [{"$multiply": ["$price", "$borrow_count"]}, 2]}}},
    ]
    return list(books().aggregate(pipe))


def real_bestseller(top_n=5):
    """真实借阅量畅销榜：以借阅流水为准做 $group + $lookup 关联书名。"""
    pipe = [
        {"$group": {"_id": "$book_isbn", "times": {"$sum": 1}}},
        {"$sort": {"times": DESCENDING}},
        {"$limit": top_n},
        {"$lookup": {"from": "books", "localField": "_id", "foreignField": "isbn", "as": "book"}},
        {"$unwind": "$book"},
        {"$project": {"_id": 0, "isbn": "$_id", "title": "$book.title", "times": 1,
                      "category": "$book.category"}},
    ]
    return list(logs().aggregate(pipe))


def reader_ranking(top_n=5, mask=True):
    """读者借阅排行：$group + $lookup(readers) + 姓名脱敏。"""
    pipe = [
        {"$group": {"_id": "$reader_card", "times": {"$sum": 1},
                    "first": {"$min": "$borrow_date"}, "last": {"$max": "$borrow_date"}}},
        {"$sort": {"times": DESCENDING, "_id": 1}},
        {"$limit": top_n},
        {"$lookup": {"from": "readers", "localField": "_id", "foreignField": "card_no", "as": "r"}},
        {"$unwind": "$r"},
        {"$project": {"_id": 0, "card_no": "$_id", "name": "$r.name", "college": "$r.college",
                      "level": "$r.level", "times": 1,
                      "first": {"$dateToString": {"format": "%Y-%m-%d", "date": "$first"}}}},
    ]
    rows = list(logs().aggregate(pipe))
    if mask:
        for row in rows:
            name = row["name"]
            row["name"] = name[0] + "*" * (len(name) - 1)
    return rows


def college_ranking():
    """学院借阅量排行榜：借阅流水与读者表 $lookup 后按学院聚合。"""
    pipe = [
        {"$group": {"_id": "$reader_card", "times": {"$sum": 1}}},
        {"$lookup": {"from": "readers", "localField": "_id", "foreignField": "card_no", "as": "r"}},
        {"$unwind": "$r"},
        {"$group": {"_id": "$r.college", "times": {"$sum": "$times"},
                    "readers": {"$sum": 1}}},
        {"$sort": {"times": DESCENDING, "_id": 1}},
        {"$project": {"_id": 0, "college": "$_id", "times": 1, "readers": 1}},
    ]
    return list(logs().aggregate(pipe))


def overview_facet():
    """一次管道返回四组统计（$facet）：状态分布、热门图书、活跃读者、总量。"""
    pipe = [
        {"$facet": {
            "status": [{"$sortByCount": "$status"}],
            "hot_books": [{"$group": {"_id": "$book_isbn", "times": {"$sum": 1}}},
                          {"$sort": {"times": DESCENDING}}, {"$limit": 3}],
            "active_readers": [{"$group": {"_id": "$reader_card", "times": {"$sum": 1}}},
                               {"$sort": {"times": DESCENDING}}, {"$limit": 3}],
            "total": [{"$group": {"_id": None, "records": {"$sum": 1},
                                  "books": {"$addToSet": "$book_isbn"},
                                  "readers": {"$addToSet": "$reader_card"}}},
                      {"$project": {"_id": 0, "records": 1,
                                    "book_kinds": {"$size": "$books"},
                                    "reader_kinds": {"$size": "$readers"}}}],
        }},
    ]
    return list(logs().aggregate(pipe))


def monthly_matrix():
    """月度 × 状态交叉透视（$group 嵌套字段 + $dateToString）。"""
    pipe = [
        {"$group": {"_id": {"month": {"$dateToString": {"format": "%Y-%m", "date": "$borrow_date"}},
                            "status": "$status"},
                    "count": {"$sum": 1}}},
        {"$group": {"_id": "$_id.month",
                    "detail": {"$push": {"k": "$_id.status", "v": "$count"}},
                    "total": {"$sum": "$count"}}},
        {"$project": {"_id": 0, "month": "$_id", "total": 1,
                      "detail": {"$arrayToObject": "$detail"}}},
        {"$sort": {"month": 1}},
    ]
    return list(logs().aggregate(pipe))


def sales_ranking():
    """销售额排行（单价 × 借阅次数，$multiply + $round）。"""
    pipe = [
        {"$addFields": {"sales": {"$round": [{"$multiply": ["$price", "$borrow_count"]}, 2]}}},
        {"$sort": {"sales": DESCENDING}},
        {"$limit": 5},
        {"$project": {"_id": 0, "title": 1, "price": 1, "borrow_count": 1, "sales": 1}},
    ]
    return list(books().aggregate(pipe))


def category_college_matrix():
    """分类 × 学院 交叉统计（$lookup 图书 + $group）。"""
    pipe = [
        {"$lookup": {"from": "books", "localField": "book_isbn", "foreignField": "isbn", "as": "b"}},
        {"$unwind": "$b"},
        {"$lookup": {"from": "readers", "localField": "reader_card", "foreignField": "card_no", "as": "r"}},
        {"$unwind": "$r"},
        {"$group": {"_id": {"category": "$b.category", "college": "$r.college"}, "times": {"$sum": 1}}},
        {"$group": {"_id": "$_id.category",
                    "total": {"$sum": "$times"},
                    "detail": {"$push": {"college": "$_id.college", "times": "$times"}}}},
        {"$sort": {"total": DESCENDING}},
        {"$project": {"_id": 0, "category": "$_id", "total": 1, "detail": 1}},
    ]
    return list(logs().aggregate(pipe))


if __name__ == "__main__":
    print("分类统计：")
    for row in category_statistics():
        print("  ", row)
    print("年度趋势：", year_trend_with_year_operator())
    print("畅销榜：", bestseller(3))
