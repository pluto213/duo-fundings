"""基金相关 API 路由"""

from fastapi import APIRouter, HTTPException, Query

from app.models.fund import FundHoldingsResponse
from app.services.fund_service import get_fund_holdings

router = APIRouter(prefix="/fund", tags=["基金"])


@router.get(
    "/holdings",
    response_model=FundHoldingsResponse,
    summary="查询基金持仓",
    description="根据基金代码获取最新持仓数据（股票代码、名称、占比等）",
)
async def fund_holdings(
    code: str = Query(..., min_length=6, max_length=6, description="6 位基金代码"),
    date: str = Query("2025", description="报告期年份"),
):
    try:
        return get_fund_holdings(code, date=date)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
