#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mongodb_connect.py —— 数据库连接模块（ST-5.2）

本模块统一封装 MongoDB 的连接参数与连接获取逻辑，被 book_manager.py、
reader_manager.py、borrow_manager.py、stat_manager.py、main.py 共同调用：

    from mongodb_connect import get_database, test_connection, close

连接参数在本模块内集中定义（可用环境变量覆盖，便于更换环境）：
    MONGODB_URI   默认 mongodb://libWriter:Writer%402026@127.0.0.1:27017/?authSource=library
                  （任务四创建的读写账号 libWriter，认证库为 library）
    MONGODB_DB    默认 library

说明：密码中的 @ 在 URI 中必须转义为 %40，否则 URI 解析会失败
（pymongo.errors.InvalidURI: Username and password must be escaped according to RFC 3986）。
"""
import os
import urllib.parse

from pymongo import MongoClient
from pymongo.errors import PyMongoError

# ---------------------------------------------------------------- 连接参数
HOST = os.environ.get("MONGODB_HOST", "127.0.0.1")
PORT = int(os.environ.get("MONGODB_PORT", "27017"))
DB_NAME = os.environ.get("MONGODB_DB", "library")
USER = os.environ.get("MONGODB_USER", "libWriter")
PASSWORD = os.environ.get("MONGODB_PASSWORD", "Writer@2026")
AUTH_DB = os.environ.get("MONGODB_AUTH_DB", DB_NAME)

# 密码中的特殊字符按 RFC 3986 转义后拼进 URI
URI = os.environ.get(
    "MONGODB_URI",
    "mongodb://%s:%s@%s:%d/?authSource=%s"
    % (urllib.parse.quote_plus(USER), urllib.parse.quote_plus(PASSWORD), HOST, PORT, AUTH_DB),
)

_print = print
_client = None          # 模块级单例，全程序复用一条连接
_db = None


def connect(uri=None, db_name=None, quiet=True):
    """建立一个 MongoClient 连接并返回 (client, db)，带超时参数，失败抛出异常。"""
    global _client, _db, _print
    if _client is None:
        _client = MongoClient(
            uri or URI,
            serverSelectionTimeoutMS=5000,   # 连不上 5 秒内报错，而不是一直挂着
            connectTimeoutMS=5000,
            appname="lib-platform",
        )
        _db = _client[db_name or DB_NAME]
        if quiet:
            # 连接建立后不再逐条打印 pymongo 的 INFO 日志（本程序自带状态输出）
            import logging
            logging.getLogger("pymongo").setLevel(logging.WARNING)
    return _client, _db


def get_client():
    """获取模块级单例 MongoClient。"""
    connect()
    return _client


def get_database(db_name=None):
    """获取 library 数据库对象（后续所有集合操作都从这里取）。"""
    connect()
    return _db if db_name is None else _client[db_name]


def get_collection(name, db_name=None):
    """获取指定集合对象。"""
    return get_database(db_name)[name]


def test_connection():
    """连接自检：ping 服务端、读取版本号，返回状态字典（供主程序打印连接状态用）。"""
    try:
        client = get_client()
        client.admin.command("ping")
        db = get_database()
        return {
            "ok": True,
            "uri": mask_uri(),
            "database": db.name,
            "version": client.server_info().get("version"),
            "collections": sorted(db.list_collection_names()),
        }
    except PyMongoError as err:
        return {"ok": False, "uri": mask_uri(), "database": DB_NAME, "error": "%s: %s" % (type(err).__name__, err)}


def collection_counts():
    """返回各业务集合的文档总数 {集合名: 数量}，用于程序启动时展示。"""
    db = get_database()
    names = [n for n in sorted(db.list_collection_names())
             if not n.startswith("system.")]
    counts = {}
    for name in names:
        try:
            counts[name] = db[name].count_documents({})
        except PyMongoError:
            counts[name] = -1          # 视图/无权限集合
    return counts


def mask_uri(uri=None):
    """打印连接信息时隐去密码，避免明文泄露。"""
    raw = uri or URI
    if "@" not in raw:
        return raw
    head, tail = raw.split("@", 1)
    if "://" in head:
        scheme, cred = head.split("://", 1)
        user = cred.split(":", 1)[0]
        return "%s://%s:******@%s" % (scheme, user, tail)
    return "******@" + tail


def close():
    """关闭连接（程序退出前调用）。"""
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
        return True
    return False


if __name__ == "__main__":      # 单独运行本文件即可做连接测试
    import json
    logging = __import__("logging")
    logging.basicConfig(level=logging.WARNING)
    status = test_connection()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if status["ok"]:
        print("各集合文档数：", json.dumps(collection_counts(), ensure_ascii=False))
    close()
