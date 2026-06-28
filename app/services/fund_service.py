"""基金数据服务层 — 封装 akshare 调用"""

import akshare as ak
import pandas as pd
from typing import Optional

from app.models.fund import FundHoldingsResponse, HoldingItem


def get_fund_holdings(fund_code: str, date: str = "2025") -> FundHoldingsResponse:
    """
    获取基金持仓数据

    Args:
        fund_code: 6 位基金代码
        date: 报告期年份，如 "2025"

    Returns:
        FundHoldingsResponse

    Raises:
        ValueError: 基金代码无效或无数据
        RuntimeError: akshare 接口异常
    """
    try:
        df: pd.DataFrame = ak.fund_portfolio_hold_em(symbol=fund_code, date=date)
    except Exception as e:
        raise RuntimeError(f"akshare 接口调用失败: {e}")

    if df is None or df.empty:
        raise ValueError(f"基金 {fund_code} 在 {date} 年无持仓数据")

    # 标准化列名
    col_map = {
        "股票代码": "stock_code",
        "股票简称": "stock_name",
        "股票名称": "stock_name",
        "占净值比例": "weight",
        "占净值比": "weight",
        "持仓占比": "weight",
        "持股数": "shares",
        "持仓数量": "shares",
        "持仓市值": "market_value",
        "报告期": "report_date",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 处理 weight：百分比 → 小数
    if "weight" in df.columns:
        df["weight"] = pd.to_numeric(
            df["weight"].astype(str).str.replace("%", "", regex=False),
            errors="coerce",
        )
        if df["weight"].max() > 1:
            df["weight"] = df["weight"] / 100

    # 提取基金名称
    fund_name: Optional[str] = None
    try:
        info = ak.fund_individual_basic_info_xq(symbol=fund_code)
        if info is not None and not info.empty:
            for col in ("基金简称", "name"):
                if col in info.columns:
                    fund_name = str(info[col].iloc[0])
                    break
    except Exception:
        pass

    report_date = str(df["report_date"].iloc[0]) if "report_date" in df.columns else None

    # 构建持仓列表
    holdings: list[HoldingItem] = []
    for _, row in df.iterrows():
        w = row.get("weight", 0)
        if pd.isna(w) or w <= 0:
            continue
        holdings.append(
            HoldingItem(
                stock_code=str(row.get("stock_code", "")),
                stock_name=str(row.get("stock_name", "")),
                weight=round(float(w), 6),
                shares=float(row["shares"]) if "shares" in df.columns and pd.notna(row.get("shares")) else None,
                market_value=float(row["market_value"]) if "market_value" in df.columns and pd.notna(row.get("market_value")) else None,
            )
        )

    return FundHoldingsResponse(
        fund_code=fund_code,
        fund_name=fund_name or fund_code,
        report_date=report_date,
        holdings=holdings,
        total_count=len(holdings),
    )
