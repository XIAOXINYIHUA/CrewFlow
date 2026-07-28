"""数据库连接和会话管理"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明基类"""

    pass


# 延迟初始化
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """获取数据库引擎 (延迟初始化)"""
    global _engine
    if _engine is None:
        connect_args: dict[str, bool] = {}
        if settings.DATABASE_URL.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(
            settings.DATABASE_URL,
            connect_args=connect_args,
            echo=False,
        )
    return _engine


def get_session() -> Session:
    """获取数据库会话"""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _SessionLocal()


def init_db() -> None:
    """初始化数据库 (创建所有表)"""
    settings.ensure_dirs()
    from src.models import (  # noqa: F401 — 确保所有模型已注册
        Claim,
        Evidence,
        HumanDecision,
        NodeExecutionRecord,
        ReportVersion,
        Source,
    )

    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def ping_db() -> None:
    """Raise when the configured database is not ready."""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


def close_db() -> None:
    """关闭所有数据库连接"""
    global _engine, _SessionLocal
    if _SessionLocal is not None:
        _SessionLocal.close_all()
        _SessionLocal = None
    if _engine is not None:
        _engine.dispose()
        _engine = None
