"""用户持仓管理服务层 — 数据库版本，支持净值缓存和并行请求"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.db_models import FundInfo, FundNavCache, FundStockHolding, Holding, Transaction
from app.models.holding import (
    HoldingCreate,
    HoldingListResponse,
    HoldingUpdate,
    MyHolding,
    PortfolioSummary,
    StockHoldingItem,
)
from app.services.fund_service import _get_stock_realtime

logger = logging.getLogger(__name__)


# ==================== 内部工具 ====================

def _get_fund_name(db: Session, fund_code: str) -> Optional[str]:
    """获取基金名称（优先从缓存读取）"""
    fund_info = db.query(FundInfo).filter(FundInfo.fund_code == fund_code).first()
    if fund_info:
        return fund_info.fund_name
    return None


def _is_nav_fresh(nav_date: date) -> bool:
    """判断净值数据是否新鲜

    规则：
    - 周一：周五的数据算新鲜
    - 周二-周五：昨天或今天的数据算新鲜
    - 周六/周日：周五的数据算新鲜
    """
    today = date.today()
    weekday = today.weekday()  # 0=周一, 6=周日

    if weekday == 0:  # 周一
        # 周五、周六、周日的数据都算新鲜
        return nav_date >= today - timedelta(days=3)
    elif weekday in (5, 6):  # 周六/周日
        # 周五的数据算新鲜
        friday = today - timedelta(days=(weekday - 4))
        return nav_date >= friday
    else:  # 周二-周五
        # 昨天或今天的数据算新鲜
        return nav_date >= today - timedelta(days=1)


def _get_or_update_nav(db: Session, fund_code: str) -> Optional[tuple[float, str]]:
    """获取基金净值（带缓存逻辑）

    Returns:
        (净值, 净值日期) 或 None
    """
    import akshare as ak

    # 查缓存
    nav_cache = db.query(FundNavCache).filter(FundNavCache.fund_code == fund_code).first()

    # 检查是否新鲜
    if nav_cache and _is_nav_fresh(nav_cache.nav_date):
        return float(nav_cache.nav), str(nav_cache.nav_date)

    # 缓存不存在或已过期，从 API 获取
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            nav = float(latest["单位净值"])
            nav_date_str = str(latest["净值日期"])[:10]
            nav_date = datetime.strptime(nav_date_str, "%Y-%m-%d").date()

            if nav_cache:
                # 更新
                nav_cache.nav = nav
                nav_cache.nav_date = nav_date
                logger.info(f"[{fund_code}] 净值缓存已更新: {nav} ({nav_date})")
            else:
                # 新增
                new_cache = FundNavCache(
                    fund_code=fund_code,
                    nav=nav,
                    nav_date=nav_date,
                )
                db.add(new_cache)
                logger.info(f"[{fund_code}] 净值缓存已创建: {nav} ({nav_date})")

            db.commit()
            return nav, str(nav_date)
    except Exception as e:
        logger.warning(f"[{fund_code}] 获取净值失败: {e}")

    # API 也失败了，返回旧缓存（如果有）
    if nav_cache:
        return float(nav_cache.nav), str(nav_cache.nav_date)

    return None


def _get_fund_estimate_data(db: Session, fund_code: str) -> tuple[Optional[float], list[StockHoldingItem]]:
    """获取基金估算数据（一次 API 调用，返回估算收益和股票持仓）

    Returns:
        (estimated_return, stock_holdings)
    """
    from app.utils import get_current_quarter

    quarter, _ = get_current_quarter()

    # 获取基金持仓
    holdings = db.query(FundStockHolding).filter(
        FundStockHolding.fund_code == fund_code,
        FundStockHolding.quarter == quarter,
    ).all()

    if not holdings:
        return None, []

    # 获取每只股票的实时行情（只调用一次）
    stock_data = {}  # stock_code -> {"price", "change_pct", "time"}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(_get_stock_realtime, h.stock_code): h.stock_code
            for h in holdings
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                stock_data[code] = future.result()
            except Exception:
                stock_data[code] = {"price": None, "change_pct": None, "time": None}

    # 构建股票持仓列表
    stock_holdings = []
    for h in holdings:
        data = stock_data.get(h.stock_code, {})
        price = data.get("price")
        change_pct = data.get("change_pct")
        price_time = data.get("time")

        stock_holdings.append(StockHoldingItem(
            stock_code=h.stock_code,
            stock_name=h.stock_name,
            weight=float(h.weight),
            current_price=round(price, 2) if price else None,
            change_pct=round(change_pct, 2) if change_pct is not None else None,
            price_time=price_time,
        ))

    # 按权重排序
    stock_holdings.sort(key=lambda x: x.weight, reverse=True)

    # 计算估算收益
    weighted_return = 0.0
    total_weight = 0.0
    for h in holdings:
        data = stock_data.get(h.stock_code, {})
        change_pct = data.get("change_pct")
        if change_pct is not None:
            weighted_return += (change_pct / 100) * float(h.weight)
            total_weight += float(h.weight)

    estimated_return = weighted_return / total_weight if total_weight > 0 else None

    if estimated_return is not None:
        logger.info(f"[{fund_code}] 今日估算涨幅: {estimated_return:.2%}")
    else:
        logger.info(f"[{fund_code}] 无法估算收益")

    return estimated_return, stock_holdings


def _calc_return(db: Session, h: Holding, current_nav: float) -> dict:
    """计算持仓收益"""
    cost = float(h.cost)
    shares = float(h.shares)
    current_value = current_nav * shares if current_nav else None

    if current_value is None:
        return {"cost": cost, "current_value": None, "profit": None, "return_rate": None}

    profit = current_value - cost

    if cost > 0:
        return_rate = profit / cost
    elif cost < 0:
        total_buy = sum(
            float(tx.amount)
            for tx in db.query(Transaction).filter(
                Transaction.fund_code == h.fund_code,
                Transaction.type == "buy",
            ).all()
        )
        return_rate = (current_value + abs(cost)) / total_buy if total_buy > 0 else 0
    else:
        return_rate = 0

    return {
        "cost": cost,
        "current_value": current_value,
        "profit": profit,
        "return_rate": return_rate,
    }


def _to_my_holding(db: Session, h: Holding, with_estimate: bool = False) -> MyHolding:
    """将 ORM 对象转为响应模型"""
    # 获取净值（带缓存逻辑）
    nav_result = _get_or_update_nav(db, h.fund_code)
    current_nav = nav_result[0] if nav_result else None
    nav_date = nav_result[1] if nav_result else None

    fund_name = _get_fund_name(db, h.fund_code)
    result = _calc_return(db, h, current_nav)

    # 估算收益和持仓股票信息（可选）
    estimated_return = None
    stock_holdings = None
    if with_estimate:
        estimated_return, stock_holdings = _get_fund_estimate_data(db, h.fund_code)

    return MyHolding(
        id=h.id,
        fund_code=h.fund_code,
        fund_name=fund_name,
        buy_nav=float(h.buy_nav),
        shares=float(h.shares),
        first_trade_date=str(h.first_trade_date),
        last_trade_date=str(h.last_trade_date),
        cost=round(result["cost"], 2),
        current_nav=round(current_nav, 4) if current_nav else None,
        nav_date=nav_date,
        current_value=round(result["current_value"], 2) if result["current_value"] else None,
        profit=round(result["profit"], 2) if result["profit"] is not None else None,
        return_rate=round(result["return_rate"], 4) if result["return_rate"] is not None else None,
        estimated_return=round(estimated_return, 4) if estimated_return is not None else None,
        stock_holdings=stock_holdings,
    )


# ==================== CRUD ====================

def create_holding(db: Session, req: HoldingCreate) -> MyHolding:
    """新增持仓"""
    cost = req.buy_nav * req.shares

    holding = Holding(
        fund_code=req.fund_code,
        buy_nav=req.buy_nav,
        shares=req.shares,
        first_trade_date=req.buy_date,
        last_trade_date=req.buy_date,
        cost=cost,
    )
    db.add(holding)
    db.flush()

    tx = Transaction(
        holding_id=holding.id,
        fund_code=req.fund_code,
        type="buy",
        nav=req.buy_nav,
        amount=cost,
        shares=req.shares,
        trade_date=req.buy_date,
    )
    db.add(tx)
    db.commit()
    db.refresh(holding)

    return _to_my_holding(db, holding)


def list_holdings(db: Session, with_estimate: bool = False) -> HoldingListResponse:
    """查询所有持仓"""
    holdings = db.query(Holding).all()

    if with_estimate:
        # 并行获取估算收益
        items = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(_to_my_holding, db, h, True): h
                for h in holdings
            }
            for future in as_completed(futures):
                try:
                    items.append(future.result())
                except Exception as e:
                    h = futures[future]
                    logger.error(f"[{h.fund_code}] 处理失败: {e}")
                    items.append(_to_my_holding(db, h, False))
    else:
        items = [_to_my_holding(db, h) for h in holdings]

    return HoldingListResponse(holdings=items, total_count=len(items))


def update_holding(db: Session, holding_id: str, req: HoldingUpdate) -> MyHolding:
    """修改持仓（加仓/减仓）"""
    holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise ValueError(f"持仓 {holding_id} 不存在")

    old_shares = float(holding.shares)

    if req.shares is not None:
        new_shares = req.shares
        diff = new_shares - old_shares

        tx_type = "buy" if diff > 0 else "sell"
        tx = Transaction(
            holding_id=holding.id,
            fund_code=holding.fund_code,
            type=tx_type,
            nav=float(holding.buy_nav),
            amount=abs(diff) * float(holding.buy_nav),
            shares=diff,
            trade_date=date.today(),
        )
        db.add(tx)

        holding.shares = new_shares
        holding.cost = float(holding.buy_nav) * new_shares

    if req.buy_nav is not None:
        holding.buy_nav = req.buy_nav
        holding.cost = req.buy_nav * float(holding.shares)

    db.commit()
    db.refresh(holding)

    return _to_my_holding(db, holding)


def delete_holding(db: Session, holding_id: str) -> bool:
    """删除持仓"""
    holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise ValueError(f"持仓 {holding_id} 不存在")

    db.delete(holding)
    db.commit()
    return True


def get_portfolio_summary(db: Session) -> PortfolioSummary:
    """持仓总览"""
    holdings = db.query(Holding).all()
    if not holdings:
        return PortfolioSummary()

    items = [_to_my_holding(db, h) for h in holdings]

    total_cost = sum(h.cost for h in items)
    total_value = sum(h.current_value for h in items if h.current_value is not None)
    total_profit = total_value - total_cost

    total_buy = sum(
        float(tx.amount)
        for tx in db.query(Transaction).filter(Transaction.type == "buy").all()
    )
    total_return_rate = total_profit / total_buy if total_buy > 0 else 0

    return PortfolioSummary(
        total_cost=round(total_cost, 2),
        total_value=round(total_value, 2),
        total_profit=round(total_profit, 2),
        total_return_rate=round(total_return_rate, 4),
        fund_count=len(items),
    )
