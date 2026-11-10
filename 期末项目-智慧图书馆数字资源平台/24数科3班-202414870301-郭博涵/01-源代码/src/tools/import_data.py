# -*- coding: utf-8 -*-
"""数据导入工具：把配套数据目录中的 JSON 数组导入 MongoDB。

与直接使用 mongoimport 的区别：日期字段在这里显式转换成 BSON Date，
而不是原样存成字符串，满足任务书中“日期按 MongoDB 日期类型存储”的要求。

用法：
    python -m tools.import_data            # 追加导入
    python -m tools.import_data --drop     # 先清空再导入
"""
import argparse
import datetime as dt
import json
import os

import config
import db

BOOK_DATE_FIELDS = ["publish_date"]
READER_DATE_FIELDS = ["register_date"]
BORROW_DATE_FIELDS = ["borrow_date", "return_date"]


def _to_date(value):
    """把 ISO 8601 字符串转成带时区的 datetime；已是日期原样返回。"""
    if value is None or isinstance(value, dt.datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Python 3.11+ 的 fromisoformat 支持毫秒与 +08:00 形式；低版本做一次兜底
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(text, fmt)
            except ValueError:
                continue
    raise ValueError("无法解析日期：%r" % value)


def _load(filename, date_fields):
    with open(filename, "r", encoding="utf-8") as fh:
        rows = json.load(fh)
    for row in rows:
        for field in date_fields:
            if field in row:
                row[field] = _to_date(row[field])
    return rows


def ensure_audit_collection(database):
    """audit_logs 使用固定集合：追加写入、容量封顶、天然按写入顺序排列。"""
    if config.COL_AUDIT not in database.list_collection_names():
        database.create_collection(
            config.COL_AUDIT, capped=True, size=32 * 1024 * 1024, max=200000
        )
        print("已创建固定集合 %s (capped, 32MB, max=200000)" % config.COL_AUDIT)


def import_all(drop=False):
    database = db.get_db()
    ensure_audit_collection(database)

    plan = [
        (config.COL_BOOKS, config.BOOKS_FILE, BOOK_DATE_FIELDS, "isbn"),
        (config.COL_READERS, config.READERS_FILE, READER_DATE_FIELDS, "card_no"),
        (config.COL_BORROWS, config.BORROW_FILE, BORROW_DATE_FIELDS, None),
    ]

    summary = []
    for name, path, date_fields, unique_key in plan:
        if not os.path.exists(path):
            raise SystemExit("数据文件不存在：%s" % path)
        rows = _load(path, date_fields)
        coll = database[name]
        if drop:
            coll.delete_many({})
        if unique_key:
            coll.create_index(unique_key, unique=True)
        # 分批写入，避免单次请求过大
        for start in range(0, len(rows), 1000):
            coll.insert_many(rows[start:start + 1000], ordered=False)
        actual = coll.count_documents({})
        summary.append((name, len(rows), actual, actual == len(rows)))
        print("集合 %-12s 源文件 %5d 条 -> 数据库 %5d 条  %s"
              % (name, len(rows), actual, "一致" if actual == len(rows) else "不一致"))

    database[config.COL_AUDIT].insert_one({
        "action": "IMPORT",
        "target": "books/readers/borrow_logs",
        "detail": "从配套数据文件批量导入",
        "operator": "import_data.py",
        "ts": dt.datetime.now(dt.timezone.utc),
    })

    ok = all(item[3] for item in summary)
    print("导入结果：%s" % ("全部一致" if ok else "存在数量不一致，请检查"))
    return ok


def main():
    parser = argparse.ArgumentParser(description="图书馆平台数据导入")
    parser.add_argument("--drop", action="store_true", help="导入前清空目标集合")
    args = parser.parse_args()
    raise SystemExit(0 if import_all(drop=args.drop) else 1)


if __name__ == "__main__":
    main()
