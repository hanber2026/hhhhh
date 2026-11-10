# -*- coding: utf-8 -*-
"""审计日志模块。

audit_logs 是固定集合（capped），只允许顺序追加，不能删除单条文档；
因此这里只提供写入与倒序查看两个操作，符合"日志只增不改"的业务约束。
"""
from datetime import datetime

import config
from db import get_collection


def write_audit(action, target, detail="", operator="librarian"):
    """写入一条审计记录。

    action  动作类型，取值见 config.AUDIT_ACTIONS
    target  操作对象，例如 ISBN、读者卡号或统计集合名
    detail  可读的补充说明
    """
    if action not in config.AUDIT_ACTIONS:
        action = "OTHER"
    doc = {
        "ts": datetime.utcnow(),
        "action": action,
        "target": target,
        "detail": detail[:200],
        "operator": operator,
        "app": "library-cli",
    }
    get_collection(config.COL_AUDIT).insert_one(doc)
    return doc


def tail(limit=10):
    """按时间倒序取最近若干条审计记录。"""
    cur = get_collection(config.COL_AUDIT).find({}, {"_id": 0}).sort("ts", -1).limit(limit)
    return list(cur)


def count():
    return get_collection(config.COL_AUDIT).count_documents({})
