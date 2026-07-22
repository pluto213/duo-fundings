"""
导入基金映射数据
用法: python scripts/import_mapping.py
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db import SessionLocal, init_db
from app.models.db_models import FundMapping

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MAPPING_CSV = os.path.join(DATA_DIR, "fund_mapping.csv")


def main():
    print("=" * 50)
    print("导入基金映射数据")
    print("=" * 50)

    init_db()

    db = SessionLocal()
    try:
        # 清空旧数据
        db.query(FundMapping).delete()
        db.commit()

        if not os.path.exists(MAPPING_CSV):
            print(f"文件不存在: {MAPPING_CSV}")
            return

        imported = 0
        with open(MAPPING_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fund_code = (row.get("fund_code") or "").strip()
                mapped_code = (row.get("mapped_fund_code") or "").strip()
                note = (row.get("note") or "").strip() or None

                if not fund_code or not mapped_code:
                    continue

                mapping = FundMapping(
                    fund_code=fund_code,
                    mapped_fund_code=mapped_code,
                    note=note,
                )
                db.add(mapping)
                imported += 1
                print(f"  {fund_code} → {mapped_code}")

        db.commit()
        print(f"\n导入完成！共 {imported} 条映射")

    finally:
        db.close()


if __name__ == "__main__":
    main()
