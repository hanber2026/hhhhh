# -*- coding: utf-8 -*-
"""智慧图书馆数字资源平台 —— 命令行入口。

两种用法：
  python3 main.py                 进入交互式菜单（默认）
  python3 main.py <子命令> [参数]  直接执行单个功能，便于脚本化演示与测试
"""
import sys

import audit
import books
import borrows
import config
import db
import files
import stats

MENU = """
================ 智慧图书馆数字资源平台 ================
 1. 图书检索（书名/类别/价格区间/标签）
 2. 评分 Top10 图书
 3. 新增图书
 4. 删除图书
 5. 读者查询（按学院）
 6. 借书
 7. 还书
 8. 统计报表（类别/学院/趋势/借阅榜/写回集合）
 9. 上传电子书与封面到 GridFS
10. 电子书检索与下载（字节校验）
11. GridFS 文件清单
12. 审计日志
 0. 退出
========================================================"""


def _fmt_money(v):
    return "%.2f" % v if isinstance(v, (int, float)) else "-"


# ----------------------------------------------------------------- 各功能
def do_search():
    print("\n-- 图书检索 --")
    kw = input("书名包含（回车跳过）: ").strip() or None
    cat = input("类别（回车跳过）: ").strip() or None
    lo = input("最低价（回车跳过）: ").strip()
    hi = input("最高价（回车跳过）: ").strip()
    tag = input("标签（回车跳过）: ").strip() or None
    rows = books.search(keyword=kw, category=cat,
                        price_min=float(lo) if lo else None,
                        price_max=float(hi) if hi else None, tag=tag)
    print("命中 %d 条：" % len(rows))
    for r in rows:
        print("  %-14s %-28s %-6s %6.2f 元 评分 %s 库存 %s"
              % (r["isbn"], r["title"][:26], r["category"], r["price"],
                 r.get("rating"), r.get("stock")))


def do_top():
    print("\n-- 评分 Top10 --")
    for i, r in enumerate(books.top_rated(), 1):
        print("  %2d. %-30s %-12s %s" % (i, r["title"][:28], r["author"], r["rating"]))


def do_add():
    print("\n-- 新增图书 --")
    doc = {
        "isbn": input("ISBN: ").strip(),
        "title": input("书名: ").strip(),
        "author": input("作者: ").strip(),
        "publisher": input("出版社: ").strip(),
        "category": input("类别: ").strip(),
        "price": float(input("价格: ").strip()),
        "stock": int(input("库存: ").strip()),
        "rating": float(input("评分: ").strip()),
        "publish_date": input("出版日期(YYYY-MM-DD): ").strip(),
        "location": {"floor": input("楼层: ").strip(), "shelf": input("书架: ").strip()},
        "tags": [t for t in input("标签(逗号分隔): ").strip().split(",") if t],
    }
    isbn = books.add_book(doc)
    print("新增成功：%s" % isbn)


def do_delete():
    isbn = input("\n要删除的 ISBN: ").strip()
    print("删除 %d 条" % books.delete_book(isbn))


def do_reader():
    college = input("\n学院（回车列出全部）: ").strip() or None
    for r in books_readers(college):
        print("  %s %-8s %-14s %s" % (r["card_no"], r["name"], r["college"], r["level"]))


def books_readers(college):
    import readers
    return readers.list_readers(college)


def do_borrow():
    print("\n-- 借书 --")
    card = input("读者卡号: ").strip()
    isbn = input("ISBN: ").strip()
    days = input("借期天数（回车默认 30）: ").strip()
    log_id = borrows.borrow(card, isbn, int(days) if days else 30)
    print("借阅成功，记录 ID：%s" % log_id)


def do_return():
    log_id = input("\n借阅记录 ID: ").strip()
    print("归还时间：%s" % borrows.return_book(log_id))


def do_stats():
    print("\n-- 1 类别统计 / 2 学院 Top5 / 3 月度趋势 / 4 借阅榜 / 5 写回集合 --")
    which = input("选择: ").strip()
    if which == "1":
        for r in stats.category_stats():
            print("  %-8s 品种 %2d 册数 %3d 均价 %6.2f 均分 %s"
                  % (r["category"], r["book_count"], r["stock_total"],
                     r["avg_price"], r["avg_rating"]))
    elif which == "2":
        for r in stats.college_top5():
            print("  %-16s 借阅 %4d 次 / 读者 %d 人" % (r["college"], r["times"], r["readers"]))
    elif which == "3":
        for r in stats.month_trend():
            print("  %s  %d" % (r["month"], r["times"]))
    elif which == "4":
        for i, r in enumerate(stats.top_books(), 1):
            print("  %2d. %-26s %4d 次  %s %s"
                  % (i, r["title"][:24], r["borrow_count"], r["floor"], r["shelf"]))
    elif which == "5":
        print("已写入 %s 集合：%d 条" % (config.COL_CATEGORY_STATS, stats.save_category_stats()))


def do_upload():
    print("\n-- 上传电子书/封面 --")
    isbn = input("ISBN: ").strip()
    path = input("本地文件路径: ").strip()
    kind = input("类型(ebook/cover): ").strip() or "ebook"
    fid, local, stored = files.upload(isbn, path, kind)
    print("file_id=%s  本地 %d 字节  GridFS 记录 %d 字节  一致=%s"
          % (fid, local, stored, local == stored))


def do_download():
    isbn = input("\n要下载的电子书 ISBN: ").strip()
    dest, written, recorded = files.download(isbn)
    print("已保存：%s" % dest)
    print("写入 %d 字节 / GridFS 记录 %d 字节  一致=%s"
          % (written, recorded, written == recorded))


def do_ls():
    print("\n-- GridFS 文件清单 --")
    for f in files.list_all():
        m = f.get("metadata", {})
        print("  %-16s %-10s %8d 字节  %s"
              % (m.get("isbn", "-"), m.get("type", "-"), f["length"],
                 m.get("original_name", f["filename"])))


def do_audit():
    print("\n-- 最近审计日志 --")
    for a in audit.tail(10):
        print("  %s  %-7s %-14s %s" % (a["ts"].strftime("%m-%d %H:%M:%S"),
                                       a["action"], a["target"], a["detail"]))


# ----------------------------------------------------------------- 菜单
ACTIONS = {
    "1": do_search, "2": do_top, "3": do_add, "4": do_delete, "5": do_reader,
    "6": do_borrow, "7": do_return, "8": do_stats, "9": do_upload,
    "10": do_download, "11": do_ls, "12": do_audit,
}


def menu():
    ok, msg = db.ping()
    print("[连接] " + msg)
    if not ok:
        return 1
    while True:
        print(MENU)
        choice = input("请选择: ").strip()
        if choice == "0":
            print("再见。")
            return 0
        action = ACTIONS.get(choice)
        if not action:
            print("无效选项。")
            continue
        try:
            action()
        except Exception as exc:                      # 演示环境统一捕获，避免直接崩溃
            print("[错误] %s" % exc)


def main(argv):
    if not argv:
        return menu()
    cmd, args = argv[0], argv[1:]
    try:
        if cmd == "search":
            for r in books.search(keyword=args[0] if args else None):
                print("%-14s %-26s %s" % (r["isbn"], r["title"], r["price"]))
        elif cmd == "top":
            for r in books.top_rated():
                print("%-26s %-12s %s" % (r["title"], r["author"], r["rating"]))
        elif cmd == "stats":
            for r in stats.category_stats():
                print("%-8s %2d %3d %6.2f %s" % (r["category"], r["book_count"],
                                                 r["stock_total"], r["avg_price"],
                                                 r["avg_rating"]))
        elif cmd == "save-stats":
            print("写入 %s：%d 条" % (config.COL_CATEGORY_STATS, stats.save_category_stats()))
        elif cmd == "add":
            isbn, title, cat, price = args[0], args[1], args[2], float(args[3])
            books.add_book({"isbn": isbn, "title": title, "category": cat, "price": price,
                            "author": "待补充", "publisher": "待补充", "stock": 1,
                            "rating": 4.0, "publish_date": "2024-01-01",
                            "location": {"floor": "三楼新书区", "shelf": "N-01", "copies": 1},
                            "tags": ["新书"]})
            print("新增成功 %s" % isbn)
        elif cmd == "del":
            print("删除 %d 条" % books.delete_book(args[0]))
        elif cmd == "upload":
            fid, local, stored = files.upload(args[0], args[1], args[2] if len(args) > 2 else "ebook")
            print("file_id=%s 本地 %d 字节 GridFS %d 字节 一致=%s"
                  % (fid, local, stored, local == stored))
        elif cmd == "download":
            dest, written, recorded = files.download(args[0])
            print("保存 %s，写入 %d 字节，记录 %d 字节，一致=%s"
                  % (dest, written, recorded, written == recorded))
        elif cmd == "ls":
            for f in files.list_all():
                m = f.get("metadata", {})
                print("%-16s %-8s %8d 字节 %s" % (m.get("isbn"), m.get("type"),
                                                  f["length"], m.get("original_name")))
        elif cmd == "audit":
            for a in audit.tail(10):
                print("%s %-7s %-14s %s" % (a["ts"].strftime("%m-%d %H:%M:%S"),
                                            a["action"], a["target"], a["detail"]))
        else:
            print("未知子命令：%s" % cmd)
            return 2
    except Exception as exc:
        print("[错误] %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
