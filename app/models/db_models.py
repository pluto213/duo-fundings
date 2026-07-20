"""ORM 表定义"""

import uuid
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.db import Base


def gen_uuid() -> str:
    return uuid.uuid4().hex[:8]


class Holding(Base):
    """持仓表 — 记录每只基金的当前状态"""
    __tablename__ = "holdings"

    id = Column(String(8), primary_key=True, default=gen_uuid)
    fund_code = Column(String(6), nullable=False, index=True, comment="基金代码")
    buy_nav = Column(Numeric(10, 4), nullable=False, comment="买入均价")
    shares = Column(Numeric(14, 2), nullable=False, comment="持有份额")
    buy_date = Column(Date, nullable=False, comment="首次买入日期")
    cost = Column(Numeric(14, 2), nullable=False, comment="买入成本")
    note = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    # 关联交易流水
    transactions = relationship("Transaction", back_populates="holding", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Holding {self.fund_code} shares={self.shares}>"


class Transaction(Base):
    """交易流水表 — 记录每一笔买卖"""
    __tablename__ = "transactions"

    id = Column(String(8), primary_key=True, default=gen_uuid)
    holding_id = Column(String(8), ForeignKey("holdings.id"), nullable=True, comment="关联持仓")
    fund_code = Column(String(6), nullable=False, index=True, comment="基金代码")
    type = Column(
        Enum("buy", "sell", "dividend", "init", name="transaction_type"),
        nullable=False,
        comment="交易类型: buy/sell/dividend/init",
    )
    nav = Column(Numeric(10, 4), nullable=False, comment="交易净值")
    amount = Column(Numeric(14, 2), nullable=True, comment="交易金额")
    shares = Column(Numeric(14, 2), nullable=False, comment="交易份额（卖出为负）")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    note = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    # 关联持仓
    holding = relationship("Holding", back_populates="transactions")

    def __repr__(self):
        return f"<Transaction {self.type} {self.fund_code} {self.shares}>"
