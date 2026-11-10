# -*- coding: utf-8 -*-
"""GridFS 电子书与封面存储模块。

文件名统一为 <isbn>.<ext>，元数据里保留 ISBN、类型（ebook/cover）与原始文件名，
这样业务侧可以按 ISBN 精确取回，而不依赖上传时的文件名。
"""
import os

import gridfs
from bson import ObjectId

import audit
import config
from db import get_db

COLL_FILES = "fs.files"
COLL_CHUNKS = "fs.chunks"


def _fs():
    return gridfs.GridFS(get_db())


def upload(isbn, local_path, kind, original_name=None, content_type=None):
    """上传一个文件到 GridFS，返回 (file_id, 本地字节数, 存储字节数)。

    kind: "ebook" 或 "cover"
    """
    size = os.path.getsize(local_path)
    name = original_name or os.path.basename(local_path)
    meta = {
        "isbn": isbn,
        "type": kind,
        "original_name": name,
        "uploaded_at": __import__("datetime").datetime.utcnow(),
        "size": size,
    }
    with open(local_path, "rb") as fh:
        file_id = _fs().put(fh, filename="%s_%s" % (isbn, name), metadata=meta,
                            contentType=content_type or "application/octet-stream")
    stored = file_size(file_id)
    audit.write_audit("UPLOAD", isbn, "上传 %s %s，%d 字节" % (kind, name, size))
    return file_id, size, stored


def file_size(file_id):
    doc = get_db()[COLL_FILES].find_one({"_id": ObjectId(str(file_id))})
    return doc["length"] if doc else -1


def find(isbn, kind=None):
    """按 ISBN（可选类型）查询 GridFS 文件元数据。"""
    query = {"metadata.isbn": isbn}
    if kind:
        query["metadata.type"] = kind
    proj = {"_id": 1, "filename": 1, "length": 1, "uploadDate": 1, "metadata": 1}
    return list(get_db()[COLL_FILES].find(query, proj).sort("uploadDate", 1))


def list_all(limit=20):
    proj = {"_id": 0, "filename": 1, "length": 1, "metadata": 1}
    return list(get_db()[COLL_FILES].find({}, proj).sort("uploadDate", 1).limit(limit))


def download(isbn, kind="ebook", dest_dir=None):
    """按ISBN下载电子书，返回 (保存路径, 本地写入字节数, GridFS 记录字节数)。"""
    docs = find(isbn, kind)
    if not docs:
        raise ValueError("未找到 %s 类型为 %s 的文件" % (isbn, kind))
    doc = docs[0]
    dest_dir = dest_dir or config.DOWNLOAD_DIR
    os.makedirs(dest_dir, exist_ok=True)
    name = doc["metadata"].get("original_name") or doc["filename"]
    dest = os.path.join(dest_dir, "%s_%s" % (isbn, name))
    written = 0
    with open(dest, "wb") as fh:
        try:
            # pymongo 4 的 GridOut 支持 readinto，走零拷贝分块写盘
            written = _fs().get(ObjectId(str(doc["_id"]))).readinto(fh)
        except AttributeError:
            # 兼容不支持 readinto 的版本：按 256KB 分块读写
            grid_out = _fs().get(ObjectId(str(doc["_id"])))
            while True:
                chunk = grid_out.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
    audit.write_audit("DOWNLOAD", isbn, "下载 %s，%d 字节" % (name, written))
    return dest, written, doc["length"]


def delete(isbn, kind=None):
    docs = find(isbn, kind)
    for d in docs:
        _fs().delete(ObjectId(str(d["_id"])))
    if docs:
        audit.write_audit("DELETE", isbn, "删除 GridFS 文件 %d 个" % len(docs))
    return len(docs)
