# -*- coding: utf-8 -*-
"""统一的 MongoDB 连接模块。

其他模块只调用 get_db()/get_collection()，不直接创建 MongoClient，
这样连接串、认证信息、连接池参数都集中在一处维护。
"""
import sys

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

import config

_client = None


def get_client():
    """返回进程内复用的 MongoClient（线程安全，自带连接池）。"""
    global _client
    if _client is None:
        # serverSelectionTimeoutMS 调小，连不上时快速失败而不是长时间阻塞
        _client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000, appname="library-platform")
    return _client


def get_db(name=None):
    return get_client()[name or config.DB_NAME]


def get_collection(name):
    return get_db()[name]


def ping():
    """连通性检查，返回 (是否成功, 说明)。"""
    try:
        get_client().admin.command("ping")
        return True, "MongoDB 连接正常"
    except ConnectionFailure as exc:
        return False, "无法连接 MongoDB：%s" % exc
    except OperationFailure as exc:
        return False, "认证或权限失败：%s" % exc


def close():
    global _client
    if _client is not None:
        _client.close()
        _client = None


if __name__ == "__main__":
    ok, msg = ping()
    print(("[OK] " if ok else "[FAIL] ") + msg)
    sys.exit(0 if ok else 1)
