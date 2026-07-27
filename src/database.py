"""数据库连接和会话管理"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from src.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明基类"""
    pass


# 延迟初始化
_engine = None
_SessionLocal = None


def get_engine():
    """获取数据库引擎 (延迟初始化)"""
    global _engine
    if _engine is None:
        connect_args = {}
        if settings.DATABASE_URL.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            settings.DATABASE_URL,
            connect_args=connect_args,
            echo=False,
        )
    return _engine


def get_session():
    """获取数据库会话"""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _SessionLocal()


def init_db():
    """初始化数据库 (创建所有表)"""
    from src.models import (  # noqa: F401 — 确保所有模型已注册
        Source, Claim, Evidence, ReportVersion,
        HumanDecision, NodeExecutionRecord,
    )

    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def close_db():
    """关闭所有数据库连接"""
    global _engine, _SessionLocal
    if _SessionLocal:
        _SessionLocal.close_all()
        _SessionLocal = None
    if _engine:
        _engine.dispose()
        _engine = None
