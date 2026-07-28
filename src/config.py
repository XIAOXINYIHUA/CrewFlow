"""CrewFlow 配置模块 — 所有配置集中管理"""

import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _resolve_path(value: str | None, default: Path, *, base: Path | None = None) -> Path:
    """Resolve an optional environment path consistently across local and container runs."""
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    return path.resolve()


_BASE_DIR = _resolve_path(os.getenv("CREWFLOW_BASE_DIR"), Path.cwd())


class Settings:
    """应用配置，优先从环境变量读取"""

    # ── API Keys ──
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # ── 模型路由 ──
    PLANNER_MODEL: str = os.getenv("CREWFLOW_PLANNER_MODEL", "gpt-4o-mini")
    RESEARCHER_MODEL: str = os.getenv("CREWFLOW_RESEARCHER_MODEL", "gpt-4o-mini")
    WRITER_MODEL: str = os.getenv("CREWFLOW_WRITER_MODEL", "gpt-4o-mini")
    REVIEWER_MODEL: str = os.getenv("CREWFLOW_REVIEWER_MODEL", "gpt-4o-mini")
    CLAIM_BUILDER_MODEL: str = os.getenv("CREWFLOW_CLAIM_BUILDER_MODEL", "gpt-4o-mini")
    FACT_CHECKER_MODEL: str = os.getenv("CREWFLOW_FACT_CHECKER_MODEL", "gpt-4o-mini")

    # ── 模型参数 ──
    MAX_RETRIES: int = int(os.getenv("CREWFLOW_MAX_RETRIES", "3"))
    REQUEST_TIMEOUT: int = int(os.getenv("CREWFLOW_REQUEST_TIMEOUT", "60"))

    # ── 路径 ──
    BASE_DIR: Path = _BASE_DIR
    OUTPUT_DIR: Path = _resolve_path(
        os.getenv("CREWFLOW_OUTPUT_DIR"), BASE_DIR / "output", base=BASE_DIR
    )
    ARTIFACTS_DIR: Path = _resolve_path(
        os.getenv("CREWFLOW_ARTIFACTS_DIR"), BASE_DIR / "data" / "artifacts", base=BASE_DIR
    )
    CHECKPOINT_DB: Path = _resolve_path(
        os.getenv("CREWFLOW_CHECKPOINT_DB"),
        BASE_DIR / "data" / "checkpoints" / "crewflow.sqlite",
        base=BASE_DIR,
    )

    # ── 运行时限制 ──
    MAX_ITERATIONS: int = int(os.getenv("CREWFLOW_MAX_ITERATIONS", "3"))
    MAX_QUERIES: int = int(os.getenv("CREWFLOW_MAX_QUERIES", "12"))
    MAX_SOURCES: int = int(os.getenv("CREWFLOW_MAX_SOURCES", "30"))
    MAX_BUDGET_USD: Decimal | None = (
        Decimal(os.getenv("CREWFLOW_MAX_BUDGET_USD", "0"))
        if os.getenv("CREWFLOW_MAX_BUDGET_USD")
        else None
    )

    # ── 数据库 ──
    DATABASE_URL: str = os.getenv(
        "CREWFLOW_DATABASE_URL",
        f"sqlite:///{BASE_DIR / 'data' / 'crewflow.db'}",
    )

    # ── 默认值 ──
    DEFAULT_LANGUAGE: str = os.getenv("CREWFLOW_DEFAULT_LANGUAGE", "zh-CN")
    DEFAULT_TARGET_WORDS: int = int(os.getenv("CREWFLOW_TARGET_WORDS", "2500"))

    # ── 服务 ──
    HOST: str = os.getenv("CREWFLOW_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("CREWFLOW_PORT", "8000"))
    WEB_HOST: str = os.getenv("CREWFLOW_WEB_HOST", "0.0.0.0")
    WEB_PORT: int = int(os.getenv("CREWFLOW_WEB_PORT", "7860"))

    def ensure_dirs(self) -> None:
        """确保输出和缓存目录存在"""
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        self.CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
