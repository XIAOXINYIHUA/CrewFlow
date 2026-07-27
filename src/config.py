"""CrewFlow 配置模块 — 所有配置集中管理"""

import os
from pathlib import Path
from decimal import Decimal


class Settings:
    """应用配置，优先从环境变量读取"""

    # ── API Keys ──
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_BASE: str = os.getenv(
        "OPENAI_API_BASE", "https://api.openai.com/v1"
    )
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
    BASE_DIR: Path = Path(
        os.getenv("CREWFLOW_BASE_DIR", str(Path.cwd()))
    )
    OUTPUT_DIR: Path = BASE_DIR / "output"
    ARTIFACTS_DIR: Path = BASE_DIR / "data" / "artifacts"

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

    def ensure_dirs(self) -> None:
        """确保输出和缓存目录存在"""
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
