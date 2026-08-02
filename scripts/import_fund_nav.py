"""
导入基金净值数据到数据库
用法: python scripts/import_fund_nav.py
"""

import sys
import time
from datetime import datetime

sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__file__)))

import akshare as ak
from app.db import SessionLocal, init_db
from app.models.db_models import FundNavCache, Holding


def get_all_fund_codes() -> list[str]:
    """从 holdings 表获取所有基金代码"""
    db = SessionLocal()
    try:
        codes = db.query(Holding.fund_code).distinct().all()
        return [c[0] for c in codes]
    finally:
        db.close()


def get_fund_nav(fund_code: str) -> tuple[float, str] | None:
    """获取基金最新净值

    Returns:
        (净值, 日期) 或 None
    """
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            nav = float(latest["单位净值"])
            nav_date = str(latest["净值日期"])[:10]  # 只取日期部分
            return nav, nav_date
    except Exception as e:
        print(f"  获取失败: {e}")
    return None


def main():
    print("=" * 50)
    print("导入基金净值数据")
    print("=" * 50)

    init_db()

    # 获取所有基金代码
    fund_codes = get_all_fund_codes()
    print(f"共 {len(fund_codes)} 只基金")
    print()

    db = SessionLocal()
    try:
        imported = 0
        updated = 0
        failed = 0

        for i, code in enumerate(fund_codes, 1):
            print(f"[{i}/{len(fund_codes)}] {code} ...", end=" ")

            # 获取净值
            result = get_fund_nav(code)
            if not result:
                failed += 1
                print("❌ 获取失败")
                continue

            nav, nav_date = result

            # 检查是否已存在
            existing = db.query(FundNavCache).filter(FundNavCache.fund_code == code).first()
            if existing:
                # 更新
                existing.nav = nav
                existing.nav_date = datetime.strptime(nav_date, "%Y-%m-%d").date()
                updated += 1
                print(f"✓ 更新: {nav} ({nav_date})")
            else:
                # 新增
                nav_cache = FundNavCache(
                    fund_code=code,
                    nav=nav,
                    nav_date=datetime.strptime(nav_date, "%Y-%m-%d").date(),
                )
                db.add(nav_cache)
                imported += 1
                print(f"✓ 新增: {nav} ({nav_date})")

            # 避免请求过快
            time.sleep(0.3)

        db.commit()
        print(f"\n导入完成！新增 {imported} 条，更新 {updated} 条，失败 {failed} 条")

    finally:
        db.close()


if __name__ == "__main__":
    main()
