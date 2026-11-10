# 智慧图书馆数字资源平台 · 源代码说明

MongoDB 7.0 + Python 3.12 + pymongo 4.19 实现的图书馆数字资源平台，覆盖图书/读者/借阅/审计四个集合与 GridFS 电子书文件存储，可在单机、三节点副本集、两分片集群三种形态下运行。

## 目录结构

```
src/
├── config.py          读取 config.ini，暴露连接串、库名、集合名、路径常量
├── db.py              统一连接模块：get_client / get_db / get_collection / ping
├── audit.py           审计日志：write_audit / tail / count
├── books.py           图书检索、Top10、新增、删除、缺失字段查询
├── readers.py         读者查询与借阅资格
├── borrows.py         借书、还书、读者流水、逾期清单
├── stats.py           五项聚合统计、统计结果物化
├── files.py           GridFS 上传 / 查询 / 下载 / 删除
├── main.py            12 项交互菜单 + 12 个子命令
├── rs_demo.py         副本集演示：状态、读取偏好、故障转移、切换期写入
└── tools/
    ├── __init__.py
    └── import_data.py 数据导入与逐集合计数校验
config.ini             连接串、库名、数据目录、下载目录
```

## 环境要求

- Python 3.9+（实测 3.12.14）
- pymongo 4.x（实测 4.19）
- MongoDB 7.0.x（实测 7.0.43），mongosh 2.12.0

```
pip3 install pymongo
```

## 配置

`config.ini` 中所有环境相关项均可被环境变量覆盖（`MONGODB_URI`、`MONGODB_DB`）：

```ini
[db]
uri = mongodb://librarian_rw:Librarian%40123@192.168.121.134:27017,192.168.121.135:27017,192.168.121.136:27017/library_db?replicaSet=rs0&authSource=library_db&readPreference=primaryPreferred
database = library_db
readonly_uri = mongodb://reader_ro:Reader%40123@...&readPreference=secondaryPreferred

[path]
data_dir = /data/import
download_dir = /data/downloads
```

切换部署形态时只改 `uri` 一行：

| 形态 | 连接串要点 |
| --- | --- |
| 单机 | `mongodb://127.0.0.1:27017` |
| 副本集 | 三个主机 + `replicaSet=rs0` + `readPreference=primaryPreferred` |
| 分片集群 | mongos 地址（如 `192.168.121.136:27020`），不写 replicaSet |

> 注意：`config.py` 使用 `RawConfigParser`，否则密码中的 `%40` 会被当成插值语法报错。

## 运行

```bash
cd src
python3 main.py                  # 进入 12 项交互菜单
python3 main.py search --keyword 数据 --category 计算机
python3 main.py top
python3 main.py stats
python3 main.py save-stats       # 统计结果写入 category_stats 集合并记审计
python3 main.py upload --isbn 9787115428028 --path /data/import/gridfs_files/ebook_1.pdf --kind ebook
python3 main.py download --isbn 9787115428028 --out /data/downloads
python3 main.py ls
python3 main.py audit
```

数据导入（会先 `--drop` 清空四个集合，再分批写入并逐集合核对条数）：

```bash
cd src
MONGODB_URI='mongodb://librarian_rw:Librarian%40123@192.168.121.134:27017/library_db?authSource=library_db' \
  python3 -m tools.import_data --drop
```

> `python -m tools.xxx` 必须在 `src` 目录下执行，否则报 `No module named 'tools'`。

## 账号与权限

| 账号 | 密码 | 角色 | 用途 |
| --- | --- | --- | --- |
| reader_ro | Reader@123 | read@library_db | 只读查询，验证写入被拒 |
| librarian_rw | Librarian@123 | readWrite@library_db | 应用默认账号 |
| lib_admin | Admin@123 | root@admin | 集群运维（rs.status / shardCollection） |

## 关键实现说明

- **库存扣减**：`update_one({"isbn": isbn, "stock": {"$gt": 0}}, {"$inc": {"stock": -1, "borrow_count": 1}})`，以 `matched_count` 判断是否成功，避免并发下超借。
- **审计**：所有写操作统一经 `audit.write_audit()` 写入固定集合 `audit_logs`（capped 32MB / 20 万条）。
- **GridFS**：`upload()` 写 `metadata{isbn, type, original_name, size}`；`download()` 因 pymongo 4.19 的 `GridOut` 不再实现 `readinto`，改为捕获 `AttributeError` 后按 256KB 分块 `read()` 写出。
- **日期**：导入时把 ISO8601 字符串转成 BSON Date；聚合按年月分组时显式指定 `timezone: "+08:00"`，避免 UTC 与本地时区错位导致跨月统计错误。
- **读取偏好**：`rs_demo.py` 会先剥离连接串里的 `readPreference`，再传关键字参数 `read_preference=ReadPreference.SECONDARY_PREFERRED`，否则连接串中的设置会压过关键字参数。
