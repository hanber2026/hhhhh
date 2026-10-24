#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reader_manager.py —— 读者管理模块（ST-5.3 读者信息管理、学院统计、等级分布）
封装的方法：find / count_documents / distinct / insert_one / update_one / delete_one
所有数据库连接统一来自 mongodb_connect.py。
"""
from datetime import datetime

from pymongo.errors import DuplicateKeyError

from mongodb_connect import get_collection


def readers():
    """readers 集合。"""
    return get_collection("readers")


def find_one(card_no):
    """按借阅证号查找读者。"""
    return readers().find_one({"card_no": card_no})


def find(name=None, college=None, level=None, limit=0):
    """多条件检索读者（姓名模糊、学院、等级）。"""
    cond = {}
    if name:
        cond["name"] = {"$regex": name}
    if college:
        cond["college"] = college
    if level:
        cond["level"] = level
    cur = readers().find(cond, {"_id": 0, "card_no": 1, "name": 1, "college": 1, "level": 1,
                                "email": 1, "phone": 1}).sort("card_no", 1)
    return list(cur.limit(limit) if limit else cur)


def count(condition=None):
    """读者总数或满足条件的读者数（count_documents）。"""
    return readers().count_documents(condition or {})


def main_projection(limit=0):
    """只取借阅证号、姓名、学院三个字段。"""
    cur = readers().find({}, {"_id": 0, "card_no": 1, "name": 1, "college": 1}).sort("card_no", 1)
    return list(cur.limit(limit) if limit else cur)


def colleges():
    """全部学院清单（distinct）。"""
    return sorted(readers().distinct("college"))


def levels():
    """全部借阅等级（distinct）。"""
    return sorted(readers().distinct("level"))


def college_statistics():
    """学院统计：$group 按学院聚合人数，并用 $sort 降序。"""
    pipe = [{"$group": {"_id": "$college", "count": {"$sum": 1}}},
            {"$sort": {"count": -1, "_id": 1}},
            {"$project": {"_id": 0, "college": "$_id", "count": 1}}]
    return list(readers().aggregate(pipe))


def level_distribution():
    """等级分布：普通 / 高级 / 教师各多少人。"""
    pipe = [{"$sortByCount": "$level"},
            {"$project": {"_id": 0, "level": "$_id", "count": 1}}]
    return list(readers().aggregate(pipe))


def missing_email():
    """未登记邮箱的读者（email 为 null 或字段缺失）。"""
    return list(readers().find({"$or": [{"email": None}, {"email": {"$exists": False}}]},
                               {"_id": 0, "card_no": 1, "name": 1, "email": 1}).sort("card_no", 1))


def insert_one(card_no, name, college, email=None, phone="", level="普通",
               fav_categories=None, register_date=None):
    """新增读者（借阅证号唯一）。"""
    doc = {
        "card_no": card_no, "name": name, "college": college, "email": email,
        "phone": phone, "level": level,
        "register_date": register_date or datetime(2026, 9, 1),
        "fav_categories": fav_categories or [],
    }
    try:
        return readers().insert_one(doc)
    except DuplicateKeyError:
        print("  [失败] 借阅证号 %s 已存在（唯一索引 idx_card_no_unique）" % card_no)
        return None


def update_one(card_no, changes):
    """修改读者部分字段（$set）。"""
    return readers().update_one({"card_no": card_no}, {"$set": dict(changes)})


def delete_one(card_no):
    """删除一位读者。"""
    return readers().delete_one({"card_no": card_no})


if __name__ == "__main__":
    print("读者总数：%d 人" % count())
    print("学院清单：%s" % "、".join(colleges()))
    print("学院统计：%s" % college_statistics())
    print("等级分布：%s" % level_distribution())
