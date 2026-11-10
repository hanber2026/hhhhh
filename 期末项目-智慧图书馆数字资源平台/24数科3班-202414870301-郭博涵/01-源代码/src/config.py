# -*- coding: utf-8 -*-
"""统一配置读取模块。

所有程序文件通过本模块获取连接串、库名与目录配置，避免在代码里硬编码。
优先级：环境变量 > config.ini > 内置默认值。
"""
import configparser
import os

# 配置文件默认放在项目根目录（src 的上一级），也允许用 LIBRARY_CONFIG 指定
_DEFAULT_INI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.ini")

# 用 RawConfigParser：连接串里的 %40（URL 编码的 @）不能被当成插值语法
_cfg = configparser.RawConfigParser()
_cfg.read(os.environ.get("LIBRARY_CONFIG", _DEFAULT_INI), encoding="utf-8")


def _get(section, key, default, env=None):
    if env and os.environ.get(env):
        return os.environ[env]
    try:
        return _cfg.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default


MONGODB_URI = _get("mongodb", "uri", "mongodb://127.0.0.1:27017", "MONGODB_URI")
DB_NAME = _get("mongodb", "database", "library_db", "MONGODB_DB")
# 只读账号连接串：用于“越权验证”演示
MONGODB_URI_READONLY = _get("mongodb", "uri_readonly", MONGODB_URI, "MONGODB_URI_READONLY")

DATA_DIR = _get("app", "data_dir", os.path.join(os.path.dirname(_DEFAULT_INI), "data"), "LIBRARY_DATA_DIR")
DOWNLOAD_DIR = _get("app", "download_dir", os.path.join(os.path.dirname(_DEFAULT_INI), "downloads"), "LIBRARY_DOWNLOAD_DIR")

BOOKS_FILE = os.path.join(DATA_DIR, "books.txt")
READERS_FILE = os.path.join(DATA_DIR, "readers.txt")
BORROW_FILE = os.path.join(DATA_DIR, "borrow_logs.txt")

# 集合名集中定义，避免各处拼写不一致
COL_BOOKS = "books"
COL_READERS = "readers"
COL_BORROWS = "borrow_logs"
COL_AUDIT = "audit_logs"
COL_CATEGORY_STATS = "category_stats"

# 审计动作白名单：超出范围的动作统一记为 OTHER，避免脏值污染审计集合
AUDIT_ACTIONS = {"IMPORT", "CREATE", "DELETE", "UPDATE", "EXPORT",
                 "UPLOAD", "DOWNLOAD", "BORROW", "RETURN", "LOGIN", "OTHER"}

if __name__ == "__main__":
    print("URI      :", MONGODB_URI)
    print("DATABASE :", DB_NAME)
    print("DATA_DIR :", DATA_DIR)
