"""结构化日志 — JSON 格式, 支持级别和上下文

所有日志统一输出为 JSON, 便于集中式日志系统 (ELK/Loki) 消费。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class StructuredFormatter(logging.Formatter):
    """JSON 结构化的日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 附加异常信息
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }

        # 附加自定义字段 (通过 extra= 传入)
        for key in ("run_id", "node", "model", "cost", "tokens", "error_type"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """配置全局日志系统

    Args:
        level: 日志级别 DEBUG / INFO / WARNING / ERROR
    """
    root = logging.getLogger("crewflow")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)

    # 关闭第三方库的 DEBUG 日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取 CrewFlow 日志器

    用法:
        logger = get_logger(__name__)
        logger.info("节点完成", extra={"node": "writer", "run_id": "run_xxx"})
    """
    return logging.getLogger(f"crewflow.{name}")


class NodeLogger:
    """节点执行日志辅助类"""

    def __init__(self, run_id: str, node_name: str):
        self.logger = get_logger(f"node.{node_name}")
        self.run_id = run_id
        self.node_name = node_name

    def start(self) -> None:
        self.logger.info(
            "节点开始",
            extra={
                "run_id": self.run_id,
                "node": self.node_name,
                "event": "start",
            },
        )

    def complete(self, **meta: object) -> None:
        self.logger.info(
            "节点完成",
            extra={
                "run_id": self.run_id,
                "node": self.node_name,
                "event": "complete",
                **meta,
            },
        )

    def error(self, error_type: str, message: str, **meta: object) -> None:
        self.logger.error(
            message,
            extra={
                "run_id": self.run_id,
                "node": self.node_name,
                "event": "error",
                "error_type": error_type,
                **meta,
            },
        )
