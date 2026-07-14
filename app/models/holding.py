"""用户持仓管理数据模型"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import date


class HoldingCreate(BaseModel):
    """新增持仓请求"""
    fund_code: str = Field(..., min_length=6, max_length=6, description="基金代码")
    buy_nav: float = Field(..., gt=0, description="买入净值")
    shares: float = Field(..., gt=0, description="持有份额")
    buy_date: date = Field(..., description="买入日期")


class HoldingUpdate(BaseModel):
    """修改持仓请求（加仓/减仓）"""
    shares: Optional[float] = Field(None, gt=0, description="新份额（覆盖原值）")
    buy_nav: Optional[float] = Field(None, gt=0, description="新买入净值")


class MyHolding(BaseModel):
    """单条持仓记录"""
    id: str = Field(..., description="持仓ID")
    fund_code: str
    fund_name: Optional[str] = None
    buy_nav: float
    shares: float
    buy_date: str
    cost: float = Field(..., description="买入成本")
    current_nav: Optional[float] = Field(None, description="当前净值")
    current_value: Optional[float] = Field(None, description="当前市值")
    profit: Optional[float] = Field(None, description="浮动盈亏")
    return_rate: Optional[float] = Field(None, description="持仓收益率")


class HoldingListResponse(BaseModel):
    """持仓列表响应"""
    holdings: list[MyHolding] = Field(default_factory=list)
    total_count: int = 0


class PortfolioSummary(BaseModel):
    """持仓总览"""
    total_cost: float = Field(0, description="总投入成本")
    total_value: float = Field(0, description="当前总市值")
    total_profit: float = Field(0, description="总浮动盈亏")
    total_return_rate: float = Field(0, description="总收益率")
    fund_count: int = Field(0, description="持有基金数量")
