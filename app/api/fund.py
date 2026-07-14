"""基金相关 API 路由"""

from fastapi import APIRouter, HTTPException, Path, Query

from app.models.fund import (
    FundHoldingsResponse,
    FundInfoResponse,
    FundNavResponse,
    FundReturnResponse,
    FundRiskResponse,
)
from app.services.fund_service import (
    get_fund_holdings,
    get_fund_info,
    get_fund_nav,
    get_fund_return,
    get_fund_risk,
)

router = APIRouter(prefix="/fund", tags=["基金"])


@router.get(
    "/holdings",
    response_model=FundHoldingsResponse,
    summary="基金股票持仓",
    description="获取基金最新持仓的股票明细（代码、名称、占比）",
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


@router.get(
    "/{code}/info",
    response_model=FundInfoResponse,
    summary="基金基本信息",
    description="获取基金档案：名称、类型、规模、经理、成立日期等",
)
async def fund_info(code: str = Path(..., min_length=6, max_length=6, description="6 位基金代码")):
    try:
        return get_fund_info(code)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get(
    "/{code}/return",
    response_model=FundReturnResponse,
    summary="基金收益率",
    description="获取基金各区间收益率（近1周/1月/3月/6月/1年/3年）",
)
async def fund_return(code: str = Path(..., min_length=6, max_length=6)):
    try:
        return get_fund_return(code)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get(
    "/{code}/risk",
    response_model=FundRiskResponse,
    summary="基金风险指标",
    description="获取基金风险指标：年化波动率、最大回撤、夏普比率、当前回撤",
)
async def fund_risk(code: str = Path(..., min_length=6, max_length=6)):
    try:
        return get_fund_risk(code)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get(
    "/{code}/nav",
    response_model=FundNavResponse,
    summary="基金净值走势",
    description="获取基金历史净值数据，支持 range 参数：1m/3m/6m/1y/3y/5y/all",
)
async def fund_nav(
    code: str = Path(..., min_length=6, max_length=6),
    range: str = Query("1y", description="时间范围: 1m/3m/6m/1y/3y/5y/all"),
):
    try:
        return get_fund_nav(code, range=range)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
