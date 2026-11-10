# -*- coding: utf-8 -*-
"""任务五演示：副本集读写偏好与故障转移下的应用行为。

用法：
  （读写偏好用 /data/scripts/rs_readpref.sh 演示）
  python3 rs_demo.py failover   主动让主节点下台，统计应用感知到新主节点的时间
  python3 rs_demo.py write      持续写入，用于观察故障转移期间的报错与自动重试
"""
import os
import sys
import time
from datetime import datetime

from pymongo import MongoClient, ReadPreference
from pymongo.errors import NotPrimaryError, AutoReconnect, PyMongoError

import config

ADMIN_URI = os.environ.get(
    "MONGODB_ADMIN_URI",
    "mongodb://lib_admin:Admin%40123@192.168.121.134:27017,192.168.121.135:27017,"
    "192.168.121.136:27017/admin?replicaSet=rs0&authSource=admin")


def _uri_without_readpref():
    """连接串里带的 readPreference 优先级高于关键字参数，这里先把它摘掉。"""
    parts = [p for p in config.MONGODB_URI.split("&") if not p.lower().startswith("readpreference=")]
    return "&".join(parts)


def connect(read_pref=None):
    kw = {"serverSelectionTimeoutMS": 8000, "replicaSet": "rs0"}
    if read_pref:
        kw["read_preference"] = read_pref
    return MongoClient(_uri_without_readpref(), **kw)


def current_primary(client):
    """从驱动的拓扑描述里取出当前主节点（pymongo 4.x 没有 .primary 属性）。"""
    try:
        client.admin.command("ping")
    except PyMongoError:
        return None
    for (h, p), desc in client.topology_description.server_descriptions().items():
        if desc.server_type_name == "RSPrimary":
            return "%s:%s" % (h, p)
    return None


def topology(client):
    # 先做一次真实操作，触发驱动的拓扑发现，否则刚创建时拿不到主节点地址
    client.admin.command("ping")
    td = client.topology_description
    print("拓扑类型 : %s" % td.topology_type_name)
    print("成员列表 : %s" % ", ".join(sorted("%s:%s" % (h, p) for (h, p) in td.server_descriptions())))
    primary = None
    for (h, p), desc in td.server_descriptions().items():
        if desc.server_type_name == "RSPrimary":
            primary = "%s:%s" % (h, p)
    print("当前主节点: %s" % primary)
    return primary


def failover():
    client = connect()
    old = topology(client)
    admin = MongoClient(ADMIN_URI, serverSelectionTimeoutMS=8000)
    print("在主节点 %s 上执行 replSetStepDown(60)，模拟主节点故障" % old)
    t0 = time.time()
    try:
        admin.admin.command("replSetStepDown", 60, force=True)
        print("  stepDown 命令返回成功")
    except PyMongoError as exc:
        print("  stepDown 命令中断（预期，连接被切断）：%s" % type(exc).__name__)

    new = None
    while time.time() - t0 < 90:
        cur = current_primary(client)
        if cur and cur != old:
            new = cur
            break
        time.sleep(0.2)
    cost = time.time() - t0
    print("新主节点 : %s" % new)
    print("感知耗时 : %.1f 秒（驱动每 0.2 秒刷新一次拓扑）" % cost)

    # 切换完成后继续读，验证应用自动恢复
    db = client.get_database(config.DB_NAME)
    doc = db.books.find_one({}, {"title": 1, "_id": 0})
    print("切换后读取 : 服务节点=%s 书名=%s" % (client.address, doc["title"]))
    client.close()
    admin.close()


def write():
    """持续写入 audit 之外的临时集合，打印每次写入的结果与耗时。"""
    client = connect(ReadPreference.PRIMARY)
    col = client.get_database(config.DB_NAME)["failover_probe"]
    ok = fail = 0
    for i in range(1, 13):
        t0 = time.time()
        try:
            col.insert_one({"seq": i, "ts": datetime.now()})
            ok += 1
            print("  写入 #%02d 成功  节点=%-22s %5.1f ms" % (i, client.address, (time.time() - t0) * 1000))
        except (NotPrimaryError, AutoReconnect) as exc:
            fail += 1
            print("  写入 #%02d 失败  %-18s %5.1f ms（驱动已切走，下次重试）"
                  % (i, type(exc).__name__, (time.time() - t0) * 1000))
        time.sleep(0.4)
    print("成功 %d 次，失败 %d 次（pymongo 可重试写入会自动切到新主节点）" % (ok, fail))
    client.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "readpref"
    {"failover": failover, "write": write}[cmd]()
