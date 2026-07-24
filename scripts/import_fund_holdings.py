"""
导入 fund_holdings_init.csv 到数据库
用法: python scripts/import_fund_holdings.py
"""

import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db import SessionLocal, init_db
from app.models.db_models import FundStockHolding

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
HOLDINGS_CSV = os.path.join(DATA_DIR, "fund_holdings_init.csv")


def main():
    print("=" * 50)
    print("导入基金持仓数据到数据库")
    print("=" * 50)

    init_db()

    db = SessionLocal()
    try:
        if not os.path.exists(HOLDINGS_CSV):
            print(f"文件不存在: {HOLDINGS_CSV}")
            return

        # 清空旧数据
        db.query(FundStockHolding).delete()
        db.commit()
        print("已清空旧数据")

        imported = 0
        skipped = 0

        with open(HOLDINGS_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fund_code = (row.get("fund_code") or "").strip()
                report_date_str = (row.get("report_date") or "").strip()
                stock_code = (row.get("stock_code") or "").strip()
                stock_name = (row.get("stock_name") or "").strip()
                weight_str = (row.get("weight") or "").strip()
                status = (row.get("status") or "").strip()

                if not fund_code or not stock_code or status != "ok":
                    skipped += 1
                    continue

                try:
                    weight = float(weight_str)
                except ValueError:
                    skipped += 1
                    continue

                # 解析报告日期
                try:
                    report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()
                except ValueError:
                    report_date = datetime.now().date()

                # 计算季度标识
                quarter = f"{report_date.year}-Q{(report_date.month - 1) // 3 + 1}"

                record = FundStockHolding(
                    fund_code=fund_code,
                    query_code=fund_code,  # CSV 中已经是映射后的数据
                    quarter=quarter,
                    report_date=report_date,
                    stock_code=stock_code,
                    stock_name=stock_name,
                    weight=weight,
                )
                db.add(record)
                imported += 1

        db.commit()

        # 统计
        fund_count = db.query(FundStockHolding.fund_code).distinct().count()
        print(f"\n导入完成！")
        print(f"  持仓记录: {imported} 条")
        print(f"  跳过: {skipped} 条")
        print(f"  基金数量: {fund_count} 只")

    finally:
        db.close()


if __name__ == "__main__":
    main()
