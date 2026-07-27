"""OpenTelemetry 可观测性集成

用于端到端调用链追踪, 跟踪每个节点执行、LLM 调用和搜索请求。
需要安装: pip install opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-langchain
"""

from __future__ import annotations

import os
from typing import Any

from src.config import settings


def is_tracing_enabled() -> bool:
    """检查是否启用了 OpenTelemetry"""
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""))


def setup_tracing(service_name: str = "crewflow") -> None:
    """初始化 OpenTelemetry tracing

    需要在应用启动时调用一次。
    配置方式:
      OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
      OTEL_SERVICE_NAME=crewflow

    如果不配置, tracing 不会自动启用。
    """
    if not is_tracing_enabled():
        print("  [Tracing] 未配置 OTEL_EXPORTER_OTLP_ENDPOINT, 跳过")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource

        resource = Resource(attributes={SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)

        exporter = OTLPSpanExporter()
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)

        trace.set_tracer_provider(provider)
        print(f"  [Tracing] OpenTelemetry 已启用, 导出到 {os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')}")
    except ImportError as e:
        print(f"  [Tracing] 导入失败 (需安装 opentelemetry 包): {e}")
    except Exception as e:
        print(f"  [Tracing] 初始化失败: {e}")


def get_tracer(name: str = "crewflow"):
    """获取 tracer 实例

    用法:
        tracer = get_tracer()
        with tracer.start_as_current_span("node.writer") as span:
            span.set_attribute("run_id", run_id)
            ...
    """
    from opentelemetry import trace
    return trace.get_tracer(name)


# ═══════════════════════════════════════════
# 跨度帮助函数
# ═══════════════════════════════════════════

def record_node_span(
    node_name: str,
    run_id: str,
    status: str = "completed",
    attributes: dict[str, Any] | None = None,
) -> None:
    """记录节点执行跨度 (手动模式)

    当 LangChain 自动 instrumentation 不可用时使用。
    """
    if not is_tracing_enabled():
        return

    tracer = get_tracer()
    with tracer.start_as_current_span(f"node.{node_name}") as span:
        span.set_attribute("run_id", run_id)
        span.set_attribute("node", node_name)
        span.set_attribute("status", status)
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v) if not isinstance(v, (int, float, bool)) else v)
