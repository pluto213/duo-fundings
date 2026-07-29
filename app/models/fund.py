"""基金相关数据模型"""

from pydantic import BaseModel, Field
from typing import Optional


# ==================== 基金持仓（股票） ====================

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


# ==================== 基金信息 ====================

class FundInfoResponse(BaseModel):
    """基金基本信息"""
    fund_code: str = Field(..., description="基金代码")
    fund_name: str = Field(..., description="基金名称")
    fund_full_name: Optional[str] = Field(None, description="基金全称")
    fund_type: Optional[str] = Field(None, description="基金类型")
    inception_date: Optional[str] = Field(None, description="成立日期")
    scale: Optional[str] = Field(None, description="最新规模")
    company: Optional[str] = Field(None, description="基金公司")
    manager: Optional[str] = Field(None, description="基金经理")
    benchmark: Optional[str] = Field(None, description="业绩比较基准")


# ==================== 收益表现 ====================

class ReturnItem(BaseModel):
    """区间收益"""
    period: str = Field(..., description="区间名称")
    return_rate: Optional[float] = Field(None, description="收益率 (小数)")


class FundReturnResponse(BaseModel):
    """基金收益率响应"""
    fund_code: str
    fund_name: Optional[str] = None
    nav_date: Optional[str] = Field(None, description="最新净值日期")
    nav: Optional[float] = Field(None, description="最新单位净值")
    returns: list[ReturnItem] = Field(default_factory=list, description="各区间收益率")


# ==================== 风险指标 ====================

class FundRiskResponse(BaseModel):
    """基金风险指标"""
    fund_code: str
    fund_name: Optional[str] = None
    nav_date: Optional[str] = None
    volatility: Optional[float] = Field(None, description="年化波动率")
    max_drawdown: Optional[float] = Field(None, description="最大回撤 (小数)")
    max_drawdown_start: Optional[str] = Field(None, description="最大回撤起始日期")
    max_drawdown_end: Optional[str] = Field(None, description="最大回撤最低点日期")
    sharpe_ratio: Optional[float] = Field(None, description="夏普比率 (无风险利率按2%)")
    current_drawdown: Optional[float] = Field(None, description="当前回撤")


# ==================== 净值走势 ====================

class NavPoint(BaseModel):
    """净值数据点"""
    date: str
    nav: float = Field(..., description="单位净值")
    daily_return: Optional[float] = Field(None, description="日增长率")


class FundNavResponse(BaseModel):
    """基金净值走势响应"""
    fund_code: str
    fund_name: Optional[str] = None
    range: str = Field(..., description="时间范围")
    data: list[NavPoint] = Field(default_factory=list)
    total_count: int = 0


# ==================== 估算收益 ====================

class StockReturnItem(BaseModel):
    """单只股票的收益情况"""
    stock_code: str = Field(..., description="股票代码")
    stock_name: str = Field(..., description="股票名称")
    weight: float = Field(..., description="持仓占比")
    report_price: Optional[float] = Field(None, description="报告期收盘价")
    current_price: Optional[float] = Field(None, description="当前价格")
    price_time: Optional[str] = Field(None, description="价格获取时间")
    stock_return: Optional[float] = Field(None, description="个股涨跌幅（小数）")


class FundEstimatedReturnResponse(BaseModel):
    """基金估算收益响应"""
    fund_code: str = Field(..., description="基金代码")
    fund_name: Optional[str] = Field(None, description="基金名称")
    report_date: Optional[str] = Field(None, description="持仓报告期")
    estimated_return: Optional[float] = Field(None, description="估算收益率")
    holdings: list[StockReturnItem] = Field(default_factory=list, description="各股票收益明细")


# ==================== 错误 ====================

class ErrorResponse(BaseModel):
    """错误响应"""
    detail: str
