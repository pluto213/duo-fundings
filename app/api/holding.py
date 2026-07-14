"""用户持仓管理 API 路由"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.holding import (
    HoldingCreate,
    HoldingListResponse,
    HoldingUpdate,
    MyHolding,
    PortfolioSummary,
)
from app.services.holding_service import (
    create_holding,
    delete_holding,
    get_portfolio_summary,
    list_holdings,
    update_holding,
)

router = APIRouter(prefix="/holding", tags=["我的持仓"])


@router.post(
    "",
    response_model=MyHolding,
    summary="新增持仓",
    description="录入一笔基金买入记录（基金代码、买入净值、份额、日期）",
    status_code=201,
)
async def add_holding(req: HoldingCreate, db: Session = Depends(get_db)):
    try:
        return create_holding(db, req)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get(
    "",
    response_model=HoldingListResponse,
    summary="持仓列表",
    description="查看所有持仓，包含每只基金的实时净值和收益率",
)
async def get_holdings(db: Session = Depends(get_db)):
    try:
        return list_holdings(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.put(
    "/{holding_id}",
    response_model=MyHolding,
    summary="修改持仓",
    description="修改持仓的份额或买入净值（加仓/减仓）",
)
async def modify_holding(holding_id: str, req: HoldingUpdate, db: Session = Depends(get_db)):
    try:
        return update_holding(db, holding_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.delete(
    "/{holding_id}",
    summary="删除持仓",
    description="删除一条持仓记录",
)
async def remove_holding(holding_id: str, db: Session = Depends(get_db)):
    try:
        delete_holding(db, holding_id)
        return {"detail": f"持仓 {holding_id} 已删除"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/summary",
    response_model=PortfolioSummary,
    summary="持仓总览",
    description="查看总资产、总收益、总收益率",
)
async def portfolio_summary(db: Session = Depends(get_db)):
    try:
        return get_portfolio_summary(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
