"""基金数据服务层 — 封装 akshare 调用，支持持仓缓存"""

import logging
import re
from datetime import date, datetime
from typing import Optional

import akshare as ak
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.db import SessionLocal
from app.models.db_models import FundMapping, FundStockHolding
from app.models.fund import (
    FundEstimatedReturnResponse,
    FundHoldingsResponse,
    FundInfoResponse,
    FundNavResponse,
    FundReturnResponse,
    FundRiskResponse,
    HoldingItem,
    NavPoint,
    ReturnItem,
    StockReturnItem,
)
from app.utils import get_current_quarter


# ==================== 基金持仓（带缓存） ====================

def _get_mapped_fund_code(fund_code: str) -> str:
    """查询基金映射，返回实际持仓的 ETF 代码"""
    db = SessionLocal()
    try:
        mapping = db.query(FundMapping).filter(FundMapping.fund_code == fund_code).first()
        return mapping.mapped_fund_code if mapping else fund_code
    finally:
        db.close()


def _get_cached_holdings(db: Session, fund_code: str, quarter: str) -> list[dict]:
    """从数据库查询缓存的持仓数据"""
    records = db.query(FundStockHolding).filter(
        FundStockHolding.fund_code == fund_code,
        FundStockHolding.quarter == quarter,
    ).all()

    if not records:
        return []

    return [
        {
            "stock_code": r.stock_code,
            "stock_name": r.stock_name,
            "weight": float(r.weight),
            "report_date": str(r.report_date),
        }
        for r in records
    ]


def _save_holdings_to_cache(db: Session, fund_code: str, query_code: str,
                             quarter: str, report_date: str, holdings: list[dict]):
    """保存持仓数据到缓存"""
    # 删除旧数据
    deleted = db.query(FundStockHolding).filter(
        FundStockHolding.fund_code == fund_code,
        FundStockHolding.quarter == quarter,
    ).delete()

    # 插入新数据
    for h in holdings:
        record = FundStockHolding(
            fund_code=fund_code,
            query_code=query_code,
            quarter=quarter,
            report_date=datetime.strptime(report_date, "%Y-%m-%d").date(),
            stock_code=h["stock_code"],
            stock_name=h["stock_name"],
            weight=h["weight"],
        )
        db.add(record)

    db.commit()
    logger.info(f"[{fund_code}] 缓存已更新: 删除 {deleted} 条旧记录, 插入 {len(holdings)} 条新记录")


def _fetch_holdings_from_api(fund_code: str, year: str) -> tuple[list[dict], str]:
    """从 akshare 获取持仓数据

    Returns:
        (持仓列表, 报告期日期)
    """
    query_code = _get_mapped_fund_code(fund_code)

    try:
        df = ak.fund_portfolio_hold_em(symbol=query_code, date=year)
    except Exception as e:
        raise RuntimeError(f"akshare 接口调用失败: {e}")

    if df is None or df.empty:
        raise ValueError(f"基金 {fund_code} 在 {year} 年无持仓数据")

    # 标准化列名
    col_map = {
        "股票代码": "stock_code",
        "股票名称": "stock_name",
        "占净值比例": "weight",
        "季度": "quarter_info",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # 处理 weight
    if "weight" in df.columns:
        df["weight"] = pd.to_numeric(
            df["weight"].astype(str).str.replace("%", "", regex=False),
            errors="coerce",
        )
        if df["weight"].max() > 1:
            df["weight"] = df["weight"] / 100

    # 只取最新季度的数据（akshare 可能返回多个季度）
    if "quarter_info" in df.columns:
        # 获取所有季度，按降序排列，取最新的
        quarters = df["quarter_info"].unique()
        latest_quarter = sorted(quarters, reverse=True)[0]
        df = df[df["quarter_info"] == latest_quarter].reset_index(drop=True)
        logger.info(f"[{fund_code}] 选择最新季度: {latest_quarter}")

    # 提取报告日期（从季度信息中解析）
    report_date = None
    if "quarter_info" in df.columns:
        quarter_info = str(df["quarter_info"].iloc[0])
        # 例如: "2026年1季度股票投资明细" 或 "截止至：2026-06-30"
        date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', quarter_info)
        if date_match:
            report_date = date_match.group(0)
        else:
            # 从季度信息推算
            year_match = re.search(r'(\d{4})年(\d)季度', quarter_info)
            if year_match:
                y = int(year_match.group(1))
                q = int(year_match.group(2))
                if q == 1:
                    report_date = f"{y}-03-31"
                elif q == 2:
                    report_date = f"{y}-06-30"
                elif q == 3:
                    report_date = f"{y}-09-30"
                elif q == 4:
                    report_date = f"{y}-12-31"

    if not report_date:
        report_date = f"{year}-12-31"  # 默认

    holdings = []
    for _, row in df.iterrows():
        w = row.get("weight", 0)
        if pd.isna(w) or w <= 0:
            continue
        holdings.append({
            "stock_code": str(row.get("stock_code", "")),
            "stock_name": str(row.get("stock_name", "")),
            "weight": round(float(w), 6),
        })

    return holdings, report_date


def get_fund_holdings(fund_code: str, year: str = "2026") -> FundHoldingsResponse:
    """获取基金持仓数据（带季度缓存）

    逻辑：
    1. 计算当前预期季度
    2. 查数据库缓存
    3. 有缓存 → 直接返回
    4. 无缓存 → 调用 API → 写入缓存 → 返回
    """
    # 计算当前预期季度
    quarter, expected_report_date = get_current_quarter()
    fund_name = _get_fund_name(fund_code)

    logger.info(f"[{fund_code}] 查询持仓, 季度={quarter}")

    db = SessionLocal()
    try:
        # 查缓存
        cached = _get_cached_holdings(db, fund_code, quarter)
        if cached:
            logger.info(f"[{fund_code}] 缓存命中, {len(cached)} 条持仓, 报告期={cached[0]['report_date']}")
            return FundHoldingsResponse(
                fund_code=fund_code,
                fund_name=fund_name or fund_code,
                report_date=cached[0]["report_date"],
                holdings=[
                    HoldingItem(
                        stock_code=h["stock_code"],
                        stock_name=h["stock_name"],
                        weight=h["weight"],
                    )
                    for h in cached
                ],
                total_count=len(cached),
            )

        # 无缓存，调用 API
        logger.info(f"[{fund_code}] 缓存未命中, 调用 akshare API...")
        try:
            holdings, report_date = _fetch_holdings_from_api(fund_code, year)
        except ValueError:
            raise
        except Exception as e:
            raise RuntimeError(f"接口调用失败: {e}")

        # 写入缓存
        query_code = _get_mapped_fund_code(fund_code)
        _save_holdings_to_cache(db, fund_code, query_code, quarter, report_date, holdings)
        logger.info(f"[{fund_code}] API 返回 {len(holdings)} 条持仓, 报告期={report_date}, 已写入缓存")

        return FundHoldingsResponse(
            fund_code=fund_code,
            fund_name=fund_name or fund_code,
            report_date=report_date,
            holdings=[
                HoldingItem(
                    stock_code=h["stock_code"],
                    stock_name=h["stock_name"],
                    weight=h["weight"],
                )
                for h in holdings
            ],
            total_count=len(holdings),
        )
    finally:
        db.close()


# ==================== 估算收益 ====================

def _get_stock_realtime(stock_code: str) -> dict:
    """获取股票实时行情（涨跌幅）

    Returns:
        dict: {"price": 最新价, "change_pct": 涨跌幅%, "time": 获取时间}
    """
    import subprocess
    import json
    from datetime import datetime

    symbol = stock_code.zfill(6)

    # 判断市场前缀
    if symbol.startswith('6'):
        secid = f"1.{symbol}"
    else:
        secid = f"0.{symbol}"

    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f170,f86"

    try:
        result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout)

        if data.get('data'):
            d = data['data']
            price = d.get('f43', 0) / 100 if d.get('f43') else None
            change_pct = d.get('f170', 0) / 100 if d.get('f170') else None
            # f86 是价格对应的时间戳
            price_time = datetime.fromtimestamp(d['f86']).strftime("%Y-%m-%d %H:%M:%S") if d.get('f86') else None
            return {
                "price": price,
                "change_pct": change_pct,
                "time": price_time,
            }
    except Exception as e:
        logger.warning(f"[{stock_code}] 获取实时行情失败: {e}")

    return {"price": None, "change_pct": None, "time": None}


def get_fund_estimated_return(fund_code: str) -> FundEstimatedReturnResponse:
    """估算基金今日实时收益

    逻辑：
    1. 获取基金持仓（从缓存）
    2. 获取每只股票的实时涨跌幅
    3. 按持仓权重加权计算基金今日估算涨跌幅
    """
    # 获取持仓（使用缓存）
    holdings_response = get_fund_holdings(fund_code)
    fund_name = holdings_response.fund_name
    report_date = holdings_response.report_date

    if not holdings_response.holdings:
        return FundEstimatedReturnResponse(
            fund_code=fund_code,
            fund_name=fund_name,
            report_date=report_date,
            estimated_return=None,
            holdings=[],
        )

    logger.info(f"[{fund_code}] 估算今日收益, 持仓数={len(holdings_response.holdings)}")

    # 获取每只股票的实时涨跌幅
    stock_returns: list[StockReturnItem] = []
    weighted_return = 0.0
    total_weight = 0.0

    for h in holdings_response.holdings:
        realtime = _get_stock_realtime(h.stock_code)
        price = realtime.get("price")
        change_pct = realtime.get("change_pct")
        price_time = realtime.get("time")

        if change_pct is not None:
            # 涨跌幅是百分比，转为小数
            stock_return = change_pct / 100
            weighted_return += stock_return * h.weight
            total_weight += h.weight
        else:
            stock_return = None

        stock_returns.append(StockReturnItem(
            stock_code=h.stock_code,
            stock_name=h.stock_name,
            weight=h.weight,
            report_price=None,
            current_price=round(price, 2) if price else None,
            price_time=price_time,
            stock_return=round(stock_return, 4) if stock_return is not None else None,
        ))

    # 计算估算收益率
    estimated_return = weighted_return / total_weight if total_weight > 0 else None

    if estimated_return is not None:
        logger.info(f"[{fund_code}] 今日估算涨幅: {estimated_return:.2%}")
    else:
        logger.info(f"[{fund_code}] 无法估算收益")

    return FundEstimatedReturnResponse(
        fund_code=fund_code,
        fund_name=fund_name,
        report_date=report_date,
        estimated_return=round(estimated_return, 4) if estimated_return is not None else None,
        holdings=stock_returns,
    )


# ==================== 基金信息 ====================

def get_fund_info(fund_code: str) -> FundInfoResponse:
    """获取基金基本信息"""
    try:
        df = ak.fund_individual_basic_info_xq(symbol=fund_code)
    except Exception as e:
        raise RuntimeError(f"akshare 接口调用失败: {e}")

    if df is None or df.empty:
        raise ValueError(f"基金 {fund_code} 不存在")

    info = dict(zip(df["item"], df["value"]))

    return FundInfoResponse(
        fund_code=fund_code,
        fund_name=str(info.get("基金名称", fund_code)),
        fund_full_name=_str(info.get("基金全称")),
        fund_type=_str(info.get("基金类型")),
        inception_date=_str(info.get("成立时间")),
        scale=_str(info.get("最新规模")),
        company=_str(info.get("基金公司")),
        manager=_str(info.get("基金经理")),
        benchmark=_str(info.get("业绩比较基准")),
    )


# ==================== 收益表现 ====================

def get_fund_return(fund_code: str) -> FundReturnResponse:
    """获取基金各区间收益率"""
    nav_df = _get_nav_df(fund_code)
    if nav_df is None or nav_df.empty:
        raise ValueError(f"基金 {fund_code} 无净值数据")

    fund_name = _get_fund_name(fund_code)
    latest = nav_df.iloc[-1]
    latest_date = str(latest["date"])
    latest_nav = float(latest["nav"])

    now = latest["date"]
    periods = {
        "近1周": 7,
        "近1月": 30,
        "近3月": 90,
        "近6月": 180,
        "近1年": 365,
        "近3年": 1095,
    }

    returns: list[ReturnItem] = []
    for name, days in periods.items():
        target_date = now - timedelta(days=days)
        mask = nav_df["date"] >= target_date
        if mask.any():
            start_nav = float(nav_df.loc[mask].iloc[0]["nav"])
            ret = (latest_nav - start_nav) / start_nav
            returns.append(ReturnItem(period=name, return_rate=round(ret, 4)))
        else:
            returns.append(ReturnItem(period=name, return_rate=None))

    return FundReturnResponse(
        fund_code=fund_code,
        fund_name=fund_name,
        nav_date=latest_date,
        nav=latest_nav,
        returns=returns,
    )


# ==================== 风险指标 ====================

def get_fund_risk(fund_code: str) -> FundRiskResponse:
    """计算基金风险指标（波动率、最大回撤、夏普比率）"""
    nav_df = _get_nav_df(fund_code)
    if nav_df is None or nav_df.empty:
        raise ValueError(f"基金 {fund_code} 无净值数据")

    fund_name = _get_fund_name(fund_code)
    latest = nav_df.iloc[-1]

    # 日收益率
    nav_series = nav_df["nav"]
    daily_returns = nav_series.pct_change().dropna()

    # 年化波动率
    volatility = float(daily_returns.std() * np.sqrt(252))

    # 最大回撤
    cummax = nav_series.cummax()
    drawdown = (nav_series - cummax) / cummax
    max_dd = float(drawdown.min())
    max_dd_end_idx = drawdown.idxmin()
    max_dd_start_idx = nav_series[:max_dd_end_idx].idxmax()

    # 当前回撤
    current_dd = float(drawdown.iloc[-1])

    # 夏普比率（无风险利率 2%）
    annual_return = float(daily_returns.mean() * 252)
    sharpe = (annual_return - 0.02) / volatility if volatility > 0 else 0

    return FundRiskResponse(
        fund_code=fund_code,
        fund_name=fund_name,
        nav_date=str(latest["date"]),
        volatility=round(volatility, 4),
        max_drawdown=round(max_dd, 4),
        max_drawdown_start=str(nav_df.loc[max_dd_start_idx, "date"]),
        max_drawdown_end=str(nav_df.loc[max_dd_end_idx, "date"]),
        sharpe_ratio=round(sharpe, 4),
        current_drawdown=round(current_dd, 4),
    )


# ==================== 净值走势 ====================

RANGE_DAYS = {
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "3y": 1095,
    "5y": 1825,
    "all": None,
}


def get_fund_nav(fund_code: str, range: str = "1y") -> FundNavResponse:
    """获取基金净值走势"""
    if range not in RANGE_DAYS:
        raise ValueError(f"无效的 range 参数，可选: {', '.join(RANGE_DAYS.keys())}")

    nav_df = _get_nav_df(fund_code)
    if nav_df is None or nav_df.empty:
        raise ValueError(f"基金 {fund_code} 无净值数据")

    fund_name = _get_fund_name(fund_code)

    # 按时间范围过滤
    days = RANGE_DAYS[range]
    if days is not None:
        cutoff = nav_df["date"].max() - timedelta(days=days)
        nav_df = nav_df[nav_df["date"] >= cutoff]

    data = [
        NavPoint(
            date=str(row["date"]),
            nav=round(float(row["nav"]), 4),
            daily_return=round(float(row["daily_return"]), 4) if pd.notna(row.get("daily_return")) else None,
        )
        for _, row in nav_df.iterrows()
    ]

    return FundNavResponse(
        fund_code=fund_code,
        fund_name=fund_name,
        range=range,
        data=data,
        total_count=len(data),
    )


# ==================== 内部工具函数 ====================

def _get_fund_name(fund_code: str) -> Optional[str]:
    """获取基金名称（简单版）"""
    try:
        info = ak.fund_individual_basic_info_xq(symbol=fund_code)
        if info is not None and not info.empty:
            mapping = dict(zip(info["item"], info["value"]))
            return str(mapping.get("基金名称", fund_code))
    except Exception:
        pass
    return None


def _get_nav_df(fund_code: str) -> Optional[pd.DataFrame]:
    """获取净值走势 DataFrame，统一列名"""
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
    except Exception as e:
        raise RuntimeError(f"akshare 接口调用失败: {e}")

    if df is None or df.empty:
        return None

    df = df.rename(columns={"净值日期": "date", "单位净值": "nav", "日增长率": "daily_return"})
    df["date"] = pd.to_datetime(df["date"])
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")
    return df.dropna(subset=["nav"]).reset_index(drop=True)


def _str(val) -> Optional[str]:
    """安全转字符串，NA/None 返回 None"""
    if val is None or (isinstance(val, str) and val in ("<NA>", "nan", "")):
        return None
    return str(val)
