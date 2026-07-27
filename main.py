"""
基金数据服务 - FastAPI 入口
启动: uvicorn main:app --reload
文档: http://127.0.0.1:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.fund import router as fund_router
from app.api.holding import router as holding_router
from app.db import init_db

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化数据库"""
    init_db()
    yield

app = FastAPI(
    title="基金数据服务",
    description="基于 akshare 的基金数据查询 API",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(fund_router, prefix="/api/v1")
app.include_router(holding_router, prefix="/api/v1")


@app.get("/", tags=["健康检查"])
async def root():
    return {"status": "ok", "service": "基金数据服务"}
