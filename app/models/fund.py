"""基金相关数据模型"""

from pydantic import BaseModel, Field
from typing import Optional


class HoldingItem(BaseModel):
    """单只持仓股票"""
    stock_code: str = Field(..., description="股票代码")
    stock_name: str = Field(..., description="股票名称")
    weight: float = Field(..., description="持仓占比 (0-1)")
    shares: Optional[float] = Field(None, description="持股数")
    market_value: Optional[float] = Field(None, description="持仓市值")


class FundHoldingsResponse(BaseModel):
    """基金持仓查询响应"""
    fund_code: str = Field(..., description="基金代码")
    fund_name: Optional[str] = Field(None, description="基金名称")
    report_date: Optional[str] = Field(None, description="报告期")
    holdings: list[HoldingItem] = Field(default_factory=list, description="持仓列表")
    total_count: int = Field(0, description="持仓股票数量")


class ErrorResponse(BaseModel):
    """错误响应"""
    detail: str
