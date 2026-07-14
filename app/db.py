"""数据库引擎 + Session 管理"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from app.config import DATABASE_URL, DB_ECHO

# 创建引擎
engine = create_engine(DATABASE_URL, echo=DB_ECHO)

# Session 工厂
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ORM 模型基类
class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖注入：获取数据库 Session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """创建所有表（首次运行时调用）"""
    Base.metadata.create_all(bind=engine)
