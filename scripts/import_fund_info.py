"""
导入基金基本信息到数据库
用法: python scripts/import_fund_info.py
"""

import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import akshare as ak
from app.db import SessionLocal, init_db
from app.models.db_models import FundInfo, Holding

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def get_all_fund_codes() -> list[str]:
    """从 holdings 表获取所有基金代码"""
    db = SessionLocal()
    try:
        codes = db.query(Holding.fund_code).distinct().all()
        return [c[0] for c in codes]
    finally:
        db.close()


def get_fund_info_from_api(fund_code: str) -> dict:
    """从 akshare 获取基金基本信息"""
    try:
        df = ak.fund_individual_basic_info_xq(symbol=fund_code)
        if df is not None and not df.empty:
            mapping = dict(zip(df["item"], df["value"]))
            return {
                "fund_code": fund_code,
                "fund_name": str(mapping.get("基金名称", fund_code)),
                "fund_type": str(mapping.get("基金类型", "")) or None,
                "company": str(mapping.get("基金公司", "")) or None,
                "manager": str(mapping.get("基金经理", "")) or None,
            }
    except Exception as e:
        print(f"  获取失败: {e}")
    return None


def main():
    print("=" * 50)
    print("导入基金基本信息")
    print("=" * 50)

    init_db()

    # 获取所有基金代码
    fund_codes = get_all_fund_codes()
    print(f"共 {len(fund_codes)} 只基金")
    print()

    db = SessionLocal()
    try:
        imported = 0
        failed = 0

        for i, code in enumerate(fund_codes, 1):
            print(f"[{i}/{len(fund_codes)}] {code} ...", end=" ")

            # 检查是否已存在
            existing = db.query(FundInfo).filter(FundInfo.fund_code == code).first()
            if existing:
                print(f"已存在: {existing.fund_name}")
                continue

            # 从 API 获取
            info = get_fund_info_from_api(code)
            if info:
                fund_info = FundInfo(**info)
                db.add(fund_info)
                imported += 1
                print(f"✓ {info['fund_name']}")
            else:
                failed += 1
                print("❌ 获取失败")

            # 避免请求过快
            time.sleep(0.3)

        db.commit()
        print(f"\n导入完成！新增 {imported} 条，失败 {failed} 条")

    finally:
        db.close()


if __name__ == "__main__":
    main()
