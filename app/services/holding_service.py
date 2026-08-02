"""用户持仓管理服务层 — 数据库版本，支持净值缓存和并行请求"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.db_models import FundInfo, FundNavCache, Holding, Transaction
from app.models.holding import (
    HoldingCreate,
    HoldingListResponse,
    HoldingUpdate,
    MyHolding,
    PortfolioSummary,
)
from app.services.fund_service import calc_fund_estimated_return

logger = logging.getLogger(__name__)


# ==================== 内部工具 ====================

def _get_fund_name(db: Session, fund_code: str) -> Optional[str]:
    """获取基金名称（优先从缓存读取）"""
    fund_info = db.query(FundInfo).filter(FundInfo.fund_code == fund_code).first()
    if fund_info:
        return fund_info.fund_name
    return None


def _get_cached_nav(db: Session, fund_code: str) -> Optional[tuple[float, str]]:
    """从缓存获取基金净值

    Returns:
        (净值, 净值日期) 或 None
    """
    nav_cache = db.query(FundNavCache).filter(FundNavCache.fund_code == fund_code).first()
    if nav_cache:
        return float(nav_cache.nav), str(nav_cache.nav_date)
    return None


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
    # 从缓存获取净值
    nav_result = _get_cached_nav(db, h.fund_code)
    current_nav = nav_result[0] if nav_result else None
    nav_date = nav_result[1] if nav_result else None

    fund_name = _get_fund_name(db, h.fund_code)
    result = _calc_return(db, h, current_nav)

    # 估算收益（可选）
    estimated_return = None
    if with_estimate:
        estimated_return = calc_fund_estimated_return(h.fund_code)

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
