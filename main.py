"""
基金数据服务 - FastAPI 入口
启动: uvicorn main:app --reload
文档: http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI

from app.api.fund import router as fund_router

app = FastAPI(
    title="基金数据服务",
    description="基于 akshare 的基金数据查询 API",
    version="0.1.0",
)

app.include_router(fund_router, prefix="/api/v1")


@app.get("/", tags=["健康检查"])
async def root():
    return {"status": "ok", "service": "基金数据服务"}
