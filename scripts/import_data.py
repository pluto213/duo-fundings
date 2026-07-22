"""
导入交易数据脚本
用法: python scripts/import_data.py

支持两种导入:
1. import_transactions.csv  → 交易流水 + 汇总持仓
2. import_holdings_summary.csv → 直接写持仓（无流水，用于定投等）
"""

import csv
import os
import sys
from datetime import datetime, date

# 把项目根目录加入 path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db import SessionLocal, init_db
from app.models.db_models import Holding, Transaction


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TRANSACTIONS_CSV = os.path.join(DATA_DIR, "import_transactions.csv")
SUMMARY_CSV = os.path.join(DATA_DIR, "import_holdings_summary.csv")


# ==================== 交易流水导入 ====================

def parse_transaction_row(row: dict, line_num: int) -> dict | None:
    """校验并解析一行交易数据"""
    fund_code = (row.get("fund_code") or "").strip()
    tx_type = (row.get("type") or "").strip()
    nav_str = (row.get("nav") or "").strip()
    shares_str = (row.get("shares") or "").strip()
    date_str = (row.get("trade_date") or "").strip()
    note = (row.get("note") or "").strip() or None

    if not fund_code or not tx_type:
        print(f"  ⚠ 第 {line_num} 行: 缺少 fund_code 或 type，跳过")
        return None

    if tx_type not in ("buy", "sell", "dividend", "init"):
        print(f"  ⚠ 第 {line_num} 行: type={tx_type} 无效，跳过")
        return None

    try:
        nav = float(nav_str)
    except ValueError:
        print(f"  ⚠ 第 {line_num} 行: nav={nav_str} 无效，跳过")
        return None

    try:
        shares = float(shares_str)
    except ValueError:
        print(f"  ⚠ 第 {line_num} 行: shares={shares_str} 无效，跳过")
        return None

    try:
        trade_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"  ⚠ 第 {line_num} 行: 日期={date_str} 格式错误，跳过")
        return None

    # 分红: nav 存总金额，shares 记 0
    if tx_type == "dividend":
        amount = nav
        shares = 0
    else:
        amount = nav * abs(shares)

    return {
        "fund_code": fund_code,
        "type": tx_type,
        "nav": nav,
        "amount": amount,
        "shares": shares if tx_type == "buy" else -abs(shares),
        "trade_date": trade_date,
        "note": note,
    }


def import_transactions(db, csv_path: str) -> set[str]:
    """导入交易流水，返回导入的 fund_code 集合"""
    print(f"读取文件: {csv_path}")

    imported = 0
    skipped = 0
    fund_codes = set()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for line_num, row in enumerate(reader, start=2):
            parsed = parse_transaction_row(row, line_num)
            if parsed is None:
                skipped += 1
                continue

            tx = Transaction(
                fund_code=parsed["fund_code"],
                type=parsed["type"],
                nav=parsed["nav"],
                amount=parsed["amount"],
                shares=parsed["shares"],
                trade_date=parsed["trade_date"],
                note=parsed["note"],
            )
            db.add(tx)
            fund_codes.add(parsed["fund_code"])
            imported += 1

    db.commit()
    print(f"  交易流水: 导入 {imported} 条，跳过 {skipped} 条")
    return fund_codes


def build_holdings_from_transactions(db, exclude_codes: set[str]):
    """从交易流水汇总持仓，跳过 exclude_codes 中的基金"""
    print()
    print("从交易流水汇总持仓...")

    transactions = db.query(Transaction).order_by(Transaction.fund_code, Transaction.trade_date).all()

    fund_map: dict[str, dict] = {}
    for tx in transactions:
        code = tx.fund_code
        if code in exclude_codes:
            continue
        if code not in fund_map:
            fund_map[code] = {
                "total_buy_shares": 0,
                "total_buy_amount": 0,
                "total_sell_amount": 0,
                "first_trade_date": tx.trade_date,
                "last_trade_date": tx.trade_date,
            }
        if tx.type == "buy":
            fund_map[code]["total_buy_shares"] += float(tx.shares)
            fund_map[code]["total_buy_amount"] += float(tx.amount)
        elif tx.type == "sell":
            fund_map[code]["total_sell_amount"] += float(tx.amount)

        # 更新最后交易日期
        if tx.trade_date > fund_map[code]["last_trade_date"]:
            fund_map[code]["last_trade_date"] = tx.trade_date

    for code, info in fund_map.items():
        total_shares = info["total_buy_shares"]
        total_buy = info["total_buy_amount"]
        total_sell = info["total_sell_amount"]

        sell_shares = sum(
            abs(float(tx.shares))
            for tx in transactions
            if tx.fund_code == code and tx.type == "sell"
        )
        current_shares = total_shares - sell_shares

        if current_shares <= 0:
            print(f"  {code}: 已清仓（剩余 {current_shares:.2f} 份），跳过")
            continue

        # 成本 = 买入总金额 - 卖出总金额（实际净投入）
        cost = total_buy - total_sell
        avg_nav = cost / current_shares if current_shares > 0 else 0

        holding = Holding(
            fund_code=code,
            buy_nav=round(avg_nav, 4),
            shares=round(current_shares, 2),
            first_trade_date=info["first_trade_date"],
            last_trade_date=info["last_trade_date"],
            cost=round(cost, 2),
        )
        db.add(holding)
        print(f"  {code}: {current_shares:.2f} 份，均价 {avg_nav:.4f}，成本 {cost:.2f}")

    db.commit()


# ==================== 汇总持仓导入 ====================

def import_holdings_summary(db, csv_path: str) -> set[str]:
    """直接导入持仓汇总，返回导入的 fund_code 集合"""
    print(f"读取文件: {csv_path}")

    imported = 0
    skipped = 0
    fund_codes = set()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for line_num, row in enumerate(reader, start=2):
            fund_code = (row.get("fund_code") or "").strip()
            shares_str = (row.get("shares") or "").strip()
            nav_str = (row.get("current_nav") or "").strip()
            profit_str = (row.get("profit") or "").strip()
            date_str = (row.get("data_date") or "").strip()
            note = (row.get("note") or "").strip() or None

            if not fund_code:
                print(f"  ⚠ 第 {line_num} 行: 缺少 fund_code，跳过")
                skipped += 1
                continue

            try:
                shares = float(shares_str)
                current_nav = float(nav_str)
                profit = float(profit_str)
            except ValueError:
                print(f"  ⚠ 第 {line_num} 行: 数值格式错误，跳过")
                skipped += 1
                continue

            # 解析日期
            try:
                data_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                print(f"  ⚠ 第 {line_num} 行: 日期={date_str} 格式错误，跳过")
                skipped += 1
                continue

            # 反算成本
            cost = current_nav * shares - profit

            holding = Holding(
                fund_code=fund_code,
                buy_nav=round(cost / shares, 4) if shares > 0 else 0,
                shares=round(shares, 2),
                first_trade_date=data_date,
                last_trade_date=data_date,
                cost=round(cost, 2),
                note=note,
            )
            db.add(holding)
            db.flush()  # 拿到 holding.id

            # 写一条 init 交易记录
            tx = Transaction(
                holding_id=holding.id,
                fund_code=fund_code,
                type="init",
                nav=current_nav,
                amount=round(cost, 2),
                shares=shares,
                trade_date=data_date,
                note=f"初始化: 成本{cost:.2f}, 收益{profit:.2f}",
            )
            db.add(tx)

            fund_codes.add(fund_code)
            imported += 1
            print(f"  {fund_code}: {shares:.2f} 份，净值 {current_nav}，盈亏 {profit:.2f}")

    db.commit()
    print(f"  汇总持仓: 导入 {imported} 条，跳过 {skipped} 条")
    return fund_codes


# ==================== 主流程 ====================

def main():
    print("=" * 50)
    print("导入基金数据")
    print("=" * 50)

    init_db()

    db = SessionLocal()
    try:
        # 清空旧数据
        db.query(Transaction).delete()
        db.query(Holding).delete()
        db.commit()
        print("已清空旧数据")
        print()

        summary_codes = set()

        # 1. 导入汇总持仓（优先级高）
        summary_path = os.path.abspath(SUMMARY_CSV)
        if os.path.exists(summary_path):
            summary_codes = import_holdings_summary(db, summary_path)
            print()

        # 2. 导入交易流水
        tx_path = os.path.abspath(TRANSACTIONS_CSV)
        if os.path.exists(tx_path):
            import_transactions(db, tx_path)
            build_holdings_from_transactions(db, exclude_codes=summary_codes)

        # 统计
        tx_count = db.query(Transaction).count()
        holding_count = db.query(Holding).count()
        print()
        print(f"导入完成！交易 {tx_count} 条，持仓 {holding_count} 只基金")

    finally:
        db.close()


if __name__ == "__main__":
    main()
