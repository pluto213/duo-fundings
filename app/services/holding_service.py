"""用户持仓管理服务层 — 数据库版本"""

from datetime import date
from typing import Optional

import akshare as ak
from sqlalchemy.orm import Session

from app.models.db_models import Holding, Transaction
from app.models.holding import (
    HoldingCreate,
    HoldingListResponse,
    HoldingUpdate,
    MyHolding,
    PortfolioSummary,
)


# ==================== 内部工具 ====================

def _get_current_nav(fund_code: str) -> Optional[float]:
    """获取基金最新净值"""
    try:
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if df is not None and not df.empty:
            return float(df.iloc[-1]["单位净值"])
    except Exception:
        pass
    return None


def _get_fund_name(fund_code: str) -> Optional[str]:
    """获取基金名称"""
    try:
        df = ak.fund_individual_basic_info_xq(symbol=fund_code)
        if df is not None and not df.empty:
            mapping = dict(zip(df["item"], df["value"]))
            return str(mapping.get("基金名称", fund_code))
    except Exception:
        pass
    return None


def _calc_return(db: Session, h: Holding, current_nav: float) -> dict:
    """计算持仓收益

    Returns:
        dict with keys: cost, current_value, profit, return_rate
    """
    cost = float(h.cost)
    shares = float(h.shares)
    current_value = current_nav * shares if current_nav else None

    if current_value is None:
        return {"cost": cost, "current_value": None, "profit": None, "return_rate": None}

    profit = current_value - cost

    if cost > 0:
        # 正常情况：收益 / 成本
        return_rate = profit / cost
    elif cost < 0:
        # 成本为负：已收回本金，用原始投入计算
        # 原始投入 = 买入总金额（从 transactions 汇总）
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


def _to_my_holding(db: Session, h: Holding) -> MyHolding:
    """将 ORM 对象转为响应模型，补充实时数据"""
    current_nav = _get_current_nav(h.fund_code)
    fund_name = _get_fund_name(h.fund_code)
    result = _calc_return(db, h, current_nav)

    return MyHolding(
        id=h.id,
        fund_code=h.fund_code,
        fund_name=fund_name,
        buy_nav=float(h.buy_nav),
        shares=float(h.shares),
        buy_date=str(h.buy_date),
        cost=round(result["cost"], 2),
        current_nav=round(current_nav, 4) if current_nav else None,
        current_value=round(result["current_value"], 2) if result["current_value"] else None,
        profit=round(result["profit"], 2) if result["profit"] is not None else None,
        return_rate=round(result["return_rate"], 4) if result["return_rate"] is not None else None,
    )


# ==================== CRUD ====================

def create_holding(db: Session, req: HoldingCreate) -> MyHolding:
    """新增持仓"""
    cost = req.buy_nav * req.shares

    # 创建持仓记录
    holding = Holding(
        fund_code=req.fund_code,
        buy_nav=req.buy_nav,
        shares=req.shares,
        buy_date=req.buy_date,
        cost=cost,
    )
    db.add(holding)
    db.flush()  # 拿到 holding.id

    # 创建交易流水
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


def list_holdings(db: Session) -> HoldingListResponse:
    """查询所有持仓"""
    holdings = db.query(Holding).all()
    items = [_to_my_holding(db, h) for h in holdings]
    return HoldingListResponse(holdings=items, total_count=len(items))


def update_holding(db: Session, holding_id: str, req: HoldingUpdate) -> MyHolding:
    """修改持仓（加仓/减仓）"""
    holding = db.query(Holding).filter(Holding.id == holding_id).first()
    if not holding:
        raise ValueError(f"持仓 {holding_id} 不存在")

    old_shares = float(holding.shares)

    # 更新份额
    if req.shares is not None:
        new_shares = req.shares
        diff = new_shares - old_shares

        # 记录交易流水
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

    # 更新买入净值
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

    # 收益率：用原始投入计算（避免负成本干扰）
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
