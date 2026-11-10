# -*- coding: utf-8 -*-
"""读者业务模块。"""
import config
from db import get_collection


def _readers():
    return get_collection(config.COL_READERS)


def find_reader(card_no):
    return _readers().find_one({"card_no": card_no}, {"_id": 0})


def list_readers(college=None, limit=10):
    """按学院列出读者；不传学院则列出前若干名。"""
    query = {"college": college} if college else {}
    proj = {"_id": 0, "card_no": 1, "name": 1, "college": 1, "level": 1,
            "fav_categories": 1}
    return list(_readers().find(query, proj).limit(limit))


def distinct_colleges():
    return sorted(_readers().distinct("college"))


def add_reader(doc):
    _readers().insert_one(dict(doc))
    return doc["card_no"]
