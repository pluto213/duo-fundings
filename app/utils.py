"""工具函数"""

from datetime import date

def get_current_quarter() -> tuple[str, str]:
    """根据当前日期计算预期的最新季度

    规则：
    - 1-3月 → 上年 Q4
    - 4-6月 → 当年 Q1
    - 7-9月 → 当年 Q2
    - 10-12月 → 当年 Q3

    Returns:
        (quarter标识, 报告期日期)
        例如: ("2026-Q2", "2026-06-30")
    """
    today = date.today()
    year = today.year
    month = today.month

    if month <= 3:
        # 1-3月，预期最新是上年 Q4
        return (f"{year - 1}-Q4", f"{year - 1}-12-31")
    elif month <= 6:
        # 4-6月，预期最新是当年 Q1
        return (f"{year}-Q1", f"{year}-03-31")
    elif month <= 9:
        # 7-9月，预期最新是当年 Q2
        return (f"{year}-Q2", f"{year}-06-30")
    else:
        # 10-12月，预期最新是当年 Q3
        return (f"{year}-Q3", f"{year}-09-30")


def get_quarter_from_date(d: date) -> tuple[str, str]:
    """从日期推算所属季度

    Args:
        d: 日期

    Returns:
        (quarter标识, 报告期日期)
    """
    year = d.year
    month = d.month

    if month <= 3:
        return (f"{year}-Q1", f"{year}-03-31")
    elif month <= 6:
        return (f"{year}-Q2", f"{year}-06-30")
    elif month <= 9:
        return (f"{year}-Q3", f"{year}-09-30")
    else:
        return (f"{year}-Q4", f"{year}-12-31")
