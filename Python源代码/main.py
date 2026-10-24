#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py —— 图书情报检索与统计平台 主程序（菜单式交互，串联各功能模块，ST-5.5）

  1. 程序启动：打印数据库连接状态与各集合文档总数
  2. 菜单提供 9 个功能项，覆盖检索 / 统计 / 更新 / 删除
  3. 每次数据变更后打印受影响的文档数
  4. 查询无结果时给出明确提示
  5. 退出前关闭数据库连接

运行：python3 main.py            （交互模式）
      python3 main.py --demo     （自动演示全部功能，无需人工输入）
"""
import sys
from datetime import datetime

from pymongo.errors import PyMongoError

import book_manager as bm
import borrow_manager as bw
import reader_manager as rm
import stat_manager as sm
from mongodb_connect import close, collection_counts, get_database, test_connection

LINE = "=" * 78
SUB = "-" * 78
MENU = """
+----------------------------------------------------------------------------+
|                     图书情报检索与统计平台  v1.0                           |
+----------------------------------------------------------------------------+
|  1. 按关键字检索图书（书名/作者/出版社，分页）      2. 按价格区间检索      |
|  3. 按类别/标签检索图书                            4. 图书评分排行榜       |
|  5. 新增图书（写入 + 唯一索引校验）                6. 修改图书信息         |
|  7. 删除图书（危险操作，需二次确认）               8. 借阅登记             |
|  9. 归还登记                                       10. 读者查询            |
| 11. 读者借阅排行榜（聚合 + $lookup）               12. 逾期提醒            |
| 13. 分类统计（$group 库存/均价/数量）              14. 借阅趋势（按年/月）  |
| 15. 畅销榜（借阅次数 Top5）                        16. 平台今日概览        |
|  0. 退出系统                                                              |
+----------------------------------------------------------------------------+"""


def title(text):
    print("\n" + SUB + "\n " + text + "\n" + SUB)


_AUTO = {"on": False}


def pause():
    """交互模式下按回车继续；--demo 演示模式自动跳过（无需人工输入）。"""
    if not _AUTO["on"]:
        try:
            input("\n按回车键继续……")
        except (KeyboardInterrupt, EOFError):
            print()


def show_books(rows, empty_hint="未找到符合条件的图书，请调整检索条件。"):
    """统一打印图书列表；rows 为空时给出明确提示（ST-5.5 要求）。"""
    if not rows:
        print("  [提示] " + empty_hint)
        return
    print("  %-16s %-26s %-8s %-6s %-8s" % ("ISBN", "书名", "价格", "库存", "借阅次数"))
    for d in rows:
        print("  %-16s %-26s %8.2f %6d %8d" % (
            d.get("isbn", "-"), d.get("title", "-")[:24], d.get("price", 0),
            d.get("stock", 0), d.get("borrow_count", 0)))
    print("  共 %d 条" % len(rows))


# ---------------------------------------------------------------- 功能 1
def f_search(auto=False):
    kw = "数据结构" if auto else input("请输入关键字（书名/作者/出版社）：").strip()
    if not kw:
        print("  [提示] 关键字不能为空。")
        return
    total, pages, page, docs = bm.search_by_keyword(kw, page=1, size=3)
    title("按关键字检索：“%s”  第 %d/%d 页" % (kw, page, pages))
    if not total:
        print("  [提示] 没有匹配“%s”的图书。" % kw)
        return
    print("  命中 %d 条，分 %d 页" % (total, pages))
    for i, d in enumerate(docs, 1):
        print("  %d. %-26s %-10s %6.2f 元  %s" % (
            i, d["title"][:24], d["author"][:8], d["price"],
            "可借 %d 本" % d["stock"] if d["stock"] else "已全部借出"))
    more = bm.search_by_keyword(kw, page=2, size=3)
    if pages > 1:
        print("  （第 2 页：%s）" % "、".join(x["title"][:12] for x in more[3]))
    else:
        print("  （共 %d 页，已全部显示）" % pages)


# ---------------------------------------------------------------- 功能 2
def f_price(auto=False):
    if auto:
        lo, hi = 80, 200
    else:
        lo, hi = 0.0, None
        try:
            lo = float(input("最低价（元，回车跳过）：") or 0)
            hi = float(input("最高价（元，回车跳过）：") or 0) or None
        except ValueError:
            print("  [提示] 价格必须是数字。")
            return
    rows = bm.search_by_price(lo, hi)
    title("价格区间检索：%s 元的图书" % ("%s ~ %s" % (lo, hi) if hi else "≥ %s" % lo))
    show_books(rows)


# ---------------------------------------------------------------- 功能 3
def f_category(auto=False):
    cats = bm.categories()
    title("按类别 / 标签检索")
    print("  现有类别（distinct）：%s" % "、".join(cats))
    cat = "计算机" if auto else input("请输入类别（回车跳过）：").strip()
    tag = "编程" if auto else input("请输入标签（回车跳过）：").strip()
    cond = {}
    if cat:
        cond["category"] = cat
    if tag:
        cond["tags"] = tag
    rows = list(bm.find(cond, {"_id": 0, "isbn": 1, "title": 1, "price": 1, "stock": 1,
                               "borrow_count": 1, "tags": 1}, sort=[("rating", -1)]))
    print("  条件：%s" % (" 且 ".join(["类别=%s" % cat if cat else "", "标签=%s" % tag if tag else ""])
                        .strip(" 且") or "无条件"))
    show_books(rows)


# ---------------------------------------------------------------- 功能 4
def f_rating(auto=False):
    title("图书评分排行榜 Top5（sort + limit + 投影）")
    rows = bm.rating_ranking(5)
    for i, d in enumerate(rows, 1):
        print("  %d. %-28s 评分 %.1f  借阅 %d 次" % (i, d["title"][:26], d["rating"], d["borrow_count"]))


# ---------------------------------------------------------------- 功能 5
def f_insert(auto=False):
    title("新增图书")
    if auto:
        doc = bm.new_book("9787115400001", "MongoDB 权威指南（第3版）", "Kristina Chodorow",
                          "人民邮电出版社", "计算机", 128.0, 6, 4.6, ["MongoDB", "数据库", "NoSQL"],
                          datetime(2024, 5, 1), 0)
        print("  录入内容：%s / %s / %.2f 元 / 库存 %d" % (doc["isbn"], doc["title"], doc["price"], doc["stock"]))
    else:
        print("  请依次输入图书信息：")
        try:
            doc = bm.new_book(
                input("  ISBN：").strip(), input("  书名：").strip(), input("  作者：").strip(),
                input("  出版社：").strip(), input("  类别：").strip(),
                float(input("  价格：") or 0), int(input("  库存：") or 0),
                float(input("  评分（回车=5.0）：") or 5.0),
                [t.strip() for t in input("  标签（逗号分隔）：").split(",") if t.strip()])
        except ValueError:
            print("  [提示] 价格/库存/评分必须是数字。")
            return
    before = bm.count()
    res = bm.insert_one(doc)
    if res is None:          # 唯一索引 idx_isbn_unique 拦截重复 ISBN
        return
    after = bm.count()
    print("  新增成功：inserted_id = %s" % res.inserted_id)
    print("  受影响文档数：1（books %d -> %d）" % (before, after))


# ---------------------------------------------------------------- 功能 6
def f_update(auto=False):
    title("修改图书信息（update_one + $set，受影响条数）")
    isbn = "9787115428028" if auto else input("请输入要修改的图书 ISBN：").strip()
    book = bm.find_one(isbn)
    if not book:
        print("  [提示] ISBN %s 对应的图书不存在。" % isbn)
        return
    print("  当前：《%s》 库存 %d，评分 %.1f" % (book["title"], book["stock"], book["rating"]))
    if auto:
        stock, rating = book["stock"] + 2, round(book["rating"] + 0.1, 1)
        print("  修改为：库存 %d，评分 %.1f" % (stock, rating))
    else:
        try:
            stock = int(input("  新库存（回车不改）：") or book["stock"])
            rating = float(input("  新评分（回车不改）：") or book["rating"])
        except ValueError:
            print("  [提示] 输入必须是数字。")
            return
    res = bm.update_one(isbn, {"stock": stock, "rating": rating,
                               "updated_at": datetime.now().replace(microsecond=0)})
    print("  匹配 %d 条，实际修改 %d 条" % (res.matched_count, res.modified_count))


# ---------------------------------------------------------------- 功能 7
def f_delete(auto=False):
    title("删除图书（delete_one / delete_many，危险操作）")
    isbn = "9787115400001" if auto else input("请输入要删除的图书 ISBN：").strip()
    book = bm.find_one(isbn)
    if not book:
        print("  [提示] ISBN %s 对应的图书不存在，无需删除。" % isbn)
        return
    ok = True if auto else input("  确认删除《%s》吗？(y/N)：" % book["title"]).strip().lower() == "y"
    if not ok:
        print("  已取消，未删除任何文档。")
        return
    before = bm.count()
    res = bm.delete_one(isbn)
    print("  删除成功：affected = %d（books %d -> %d）" % (res.deleted_count, before, before - res.deleted_count))
    zero = bm.delete_many({"stock": 0, "borrow_count": {"$lt": 0}})     # 清理示例：条件删除
    print("  附带条件清理（stock=0 且 borrow_count<0）：affected = %d" % zero.deleted_count)


# ---------------------------------------------------------------- 功能 8
def f_borrow(auto=False):
    title("借阅登记（insert_one 追加流水 + 库存扣减）")
    card, isbn = ("R20240003", "9787115428028") if auto else (
        input("  读者借阅证号：").strip(), input("  图书 ISBN：").strip())
    flag, msg = bw.borrow(card, isbn)
    print("  " + msg)
    print("  当前在借记录：%d 条" % bw.count({"status": {"$in": ["借出", "逾期"]}}))


# ---------------------------------------------------------------- 功能 9
def f_return(auto=False):
    title("归还登记（追加已归还状态 + 库存回补）")
    card, isbn = ("R20240003", "9787115428028") if auto else (
        input("  读者借阅证号：").strip(), input("  图书 ISBN：").strip())
    flag, msg = bw.return_book(card, isbn)
    print("  " + msg)


# ---------------------------------------------------------------- 功能 10
def f_readers(auto=False):
    title("读者查询（find / count_documents / distinct）")
    print("  读者总数：%d 人；学院 %d 个：%s" % (rm.count(), len(rm.colleges()), "、".join(rm.colleges())))
    print("  借阅等级（distinct）：%s" % "、".join(rm.levels()))
    name = "张" if auto else input("  按姓名检索（回车列出全部）：").strip()
    rows = rm.find(name=name, limit=5) if name else rm.main_projection(5)
    if not rows:
        print("  [提示] 没有找到姓名包含“%s”的读者。" % name)
        return
    print("  %-12s %-8s %-16s %-6s" % ("借阅证号", "姓名", "学院", "等级"))
    for d in rows:
        print("  %-12s %-8s %-16s %-6s" % (d["card_no"], d["name"], d["college"], d["level"]))
    print("  学院统计：%s" % "，".join("%s %d 人" % (r["college"], r["count"])
                                     for r in rm.college_statistics()))
    print("  等级分布：%s" % "，".join("%s %d 人" % (r["level"], r["count"])
                                     for r in rm.level_distribution()))
    print("  未登记邮箱：%s" % "、".join("%s(%s)" % (d["name"], d["card_no"]) for d in rm.missing_email()))


# ---------------------------------------------------------------- 功能 11
def f_reader_rank(auto=False):
    title("读者借阅排行榜 Top5（$group + $lookup + 姓名脱敏）")
    rows = sm.reader_ranking(5)
    if not rows:
        print("  [提示] 暂无借阅记录。")
        return
    print("  %-4s %-12s %-8s %-18s %-6s %-6s %s" % ("名次", "借阅证号", "姓名", "学院", "等级", "次数", "首次借阅"))
    for i, d in enumerate(rows, 1):
        print("  %-4d %-12s %-8s %-18s %-6s %-6d %s" % (
            i, d["card_no"], d["name"], d["college"], d["level"], d["times"], d["first"]))
    print("  学院借阅量排行：%s" % "，".join("%s %d 次" % (r["college"], r["times"])
                                       for r in sm.college_ranking()))


# ---------------------------------------------------------------- 功能 12
def f_overdue(auto=False):
    title("逾期提醒（借期 %d 天）" % bw.BORROW_DAYS)
    rows = bw.overdue_list()
    if not rows:
        print("  [提示] 当前没有逾期记录，全部图书都在借期内。")
        return
    print("  需提醒 %d 条：" % len(rows))
    for i, d in enumerate(rows, 1):
        print("  %d. %-12s %-6s 《%s》 借于 %s，逾期 %d 天" % (
            i, d["reader_card"], d["reader_name"], d["title"], d["borrow_date"], d["overdue_days"]))


# ---------------------------------------------------------------- 功能 13
def f_category_stat(auto=False):
    title("分类统计（$group：数量 / 库存总量 / 均价 / 均分，按库存降序）")
    rows = sm.category_statistics(write_back=True) or sm.category_statistics()
    print("  %-10s %-6s %-8s %-8s %-6s" % ("类别", "数量", "库存", "均价", "均分"))
    for d in rows:
        print("  %-10s %4d %8d %8.2f %6.2f" % (d["category"], d["book_count"], d["stock_total"],
                                               d["avg_price"], d["avg_rating"]))
    res = get_database()["category_stats"].count_documents({})
    print("  本次 $merge 写回 %d 组统计结果，category_stats 集合现有 %d 条" % (len(rows), res))


# ---------------------------------------------------------------- 功能 14
def f_trend(auto=False):
    title("借阅趋势（$dateToString 按年 / 按月分组）")
    by = "月" if auto else (input("  按年(y)/按月(m)统计？(y/m)：").strip().lower() or "y")
    rows = sm.borrow_trend("month" if by in ("m", "月") else "year")
    if not rows:
        print("  [提示] 暂无借阅数据。")
        return
    label = "月份" if by in ("m", "月") else "年份"
    print("  %-10s %-6s %-8s %s" % (label, "次数", "读者数", "分布"))
    for d in rows:
        print("  %-10s %6d %6d   %s" % (d["period"], d["count"], d["readers"], "#" * d["count"]))
    print("  对照（$year + $concat）：%s" % "，".join("%s %d 次" % (r["label"], r["count"])
                                                  for r in sm.year_trend_with_year_operator()))


# ---------------------------------------------------------------- 功能 15
def f_bestseller(auto=False):
    title("畅销榜 Top5（借阅次数最多的图书）")
    for i, d in enumerate(sm.bestseller(5), 1):
        print("  %d. %-26s 借阅 %3d 次  销售额 %8.2f 元  评分 %.1f" % (
            i, d["title"][:24], d["borrow_count"], d["sales"], d["rating"]))
    print("  按借阅流水统计的真实热门书：%s" % "，".join(
        "%s %d 次" % (r["title"], r["times"]) for r in sm.real_bestseller(3)))


# ---------------------------------------------------------------- 功能 16
def f_overview(auto=False):
    title("平台今日概览  %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    stock = bm.stock_statistics()
    print("  图书：%d 种，库存合计 %d 册，有货 %d 种（%.1f%%），售罄 %d 种，均价 %.2f 元" % (
        stock.get("kinds", 0), stock.get("total_stock", 0), stock.get("in_stock", 0),
        100.0 * stock.get("in_stock", 0) / max(1, stock.get("kinds", 1)), stock.get("zero", 0),
        stock.get("avg_price", 0)))
    print("  读者：%d 人（未登记邮箱 %d 人）" % (rm.count(), len(rm.missing_email())))
    print("  借阅流水：%d 条 —— %s" % (bw.count(), "，".join(
        "%s %d" % (d["status"], d["count"]) for d in bw.status_distribution())))
    facet = sm.overview_facet()[0]
    t = facet["total"][0] if facet["total"] else {}
    print("  $facet 一次性统计：记录 %s 条，涉及 %s 种图书、%s 位读者" % (
        t.get("records"), t.get("book_kinds"), t.get("reader_kinds")))
    print("  视图 book_in_stock 前 3 条：%s" % "，".join(
        "%s(%d 本)" % (d["title"][:12], d["stock"]) for d in bm.view_book_in_stock(3)))


ACTIONS = {"1": f_search, "2": f_price, "3": f_category, "4": f_rating, "5": f_insert,
           "6": f_update, "7": f_delete, "8": f_borrow, "9": f_return, "10": f_readers,
           "11": f_reader_rank, "12": f_overdue, "13": f_category_stat, "14": f_trend,
           "15": f_bestseller, "16": f_overview}


def show_status():
    """程序启动时打印数据库连接状态与各集合文档总数（ST-5.5 要求）。"""
    print(LINE)
    print(" 图书情报检索与统计平台  v1.0   ——  基于 MongoDB 7.0 + PyMongo")
    print(LINE)
    st = test_connection()
    if not st["ok"]:
        print(" [连接失败] %s" % st.get("error"))
        print(" 请检查 mongod 服务是否启动、账号口令与认证库是否正确。")
        return False
    print(" [连接成功] URI：%s" % st["uri"])
    print(" 数据库：%-10s 服务端版本：%s" % (st["database"], st["version"]))
    print(" 启动时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print(" 各集合文档总数：")
    for name, cnt in collection_counts().items():
        print("   %-28s %6d" % (name, cnt))
    print(LINE)
    return True


def main(argv):
    auto = "--demo" in argv
    _AUTO["on"] = auto
    if not show_status():
        close()
        return 1
    if auto:
        print("\n[演示模式] 自动依次执行全部功能项：")
        for key in [str(i) for i in range(1, 17)]:
            ACTIONS[key](auto=True)
    else:
        while True:
            print(MENU)
            print()
            choice = input("请选择功能编号（0 退出）：").strip()
            if choice == "0":
                break
            func = ACTIONS.get(choice)
            if not func:
                print("  [提示] 无效的编号，请输入 0—16。")
                continue
            try:
                func()
            except PyMongoError as err:
                print("  [数据库异常] %s: %s" % (type(err).__name__, err))
            except (KeyboardInterrupt, EOFError):
                print("\n  已中断当前操作。")
            pause()
    print("\n%s\n 感谢使用，数据库连接已关闭。" % LINE)
    close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
