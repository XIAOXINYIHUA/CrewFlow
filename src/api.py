"""CrewFlow FastAPI API — 任务创建、查询、审批、导出、SSE 事件流"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from src import __version__
from src.config import settings
from src.database import close_db, init_db, ping_db
from src.graph import reset_graph
from src.models import HumanAction, HumanDecision, ResearchRequirements
from src.orm_models import ResearchRunORM
from src.repository import (
    count_runs,
    create_run,
    get_report_versions,
    get_run,
    get_run_events,
    get_sources,
    list_runs,
    save_human_decision,
    update_run_status,
)
from src.runtime import run_coordinator
from src.state import create_initial_state


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    await run_coordinator.recover_incomplete()
    yield
    await run_coordinator.shutdown()
    reset_graph()
    close_db()


app = FastAPI(title="CrewFlow API", version=__version__, lifespan=lifespan)


# ═══════════════════════════════════════════
# 标准响应模型
# ═══════════════════════════════════════════


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    run_id: str | None = None


class PaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool


# ═══════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════


class CreateRunRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    purpose: str | None = Field(None, max_length=1000)
    audience: str = "general"
    language: str = "zh-CN"
    target_words: int = Field(2500, ge=500, le=20000)
    require_human_approval: bool = True
    max_sources: int = Field(30, ge=1, le=100)
    preferred_domains: list[str] = Field(default_factory=list)
    excluded_domains: list[str] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    action: HumanAction
    feedback: str = ""


class SourceFilterRequest(BaseModel):
    status: str | None = None
    source_type: str | None = None
    min_credibility: float | None = Field(None, ge=0.0, le=1.0)


# ═══════════════════════════════════════════
# 响应模型
# ═══════════════════════════════════════════


class CreateRunResponse(BaseModel):
    run_id: str
    thread_id: str
    status: str


class RunInfoResponse(BaseModel):
    run_id: str
    topic: str
    status: str
    current_node: str | None = None
    iteration: int = 0
    require_human_approval: bool = True
    total_cost_usd: float = 0.0
    error_count: int = 0
    created_at: str
    updated_at: str
    completed_at: str | None = None


class RunListResponse(BaseModel):
    items: list[RunInfoResponse]
    pagination: PaginationMeta


class SourceResponse(BaseModel):
    id: str
    url: str
    title: str
    publisher: str | None = None
    source_type: str
    credibility_score: float
    extraction_status: str
    extraction_error: str | None = None


class ReportVersionResponse(BaseModel):
    id: str
    version: int
    created_by: str
    created_at: str
    length: int
    citation_count: int = 0


async def _require_run(run_id: str) -> ResearchRunORM:
    run = await asyncio.to_thread(get_run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


def _read_artifact_preview(location: str, limit: int = 20000) -> str:
    """Read only files inside the configured artifact directory."""
    if not location:
        return ""
    artifact_root = settings.ARTIFACTS_DIR.resolve()
    path = Path(location).resolve()
    if not path.is_relative_to(artifact_root) or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")[:limit]


# ═══════════════════════════════════════════
# SSE 事件流 (支持断线重连 last-event-id)
# ═══════════════════════════════════════════


async def event_stream(
    run_id: str,
    request: Request,
    last_event_id: int = 0,
) -> AsyncGenerator[str, None]:
    """Replay persisted events, then stream new events without rerunning the graph."""
    cursor = max(last_event_id, 0)
    while True:
        events = await asyncio.to_thread(get_run_events, run_id, cursor)
        for event in events:
            cursor = event.sequence
            yield (
                f"id: {event.sequence}\nevent: {event.event_type}\ndata: {event.payload_json}\n\n"
            )

        run = await asyncio.to_thread(get_run, run_id)
        if run is None:
            return
        if run.status in {"waiting_human", "completed", "failed", "cancelled"}:
            yield "data: [DONE]\n\n"
            return
        if await request.is_disconnected():
            return
        if not await run_coordinator.wait_for_update(run_id):
            yield ": keep-alive\n\n"


# ═══════════════════════════════════════════
# 健康检查 & 信息
# ═══════════════════════════════════════════


@app.get("/health")
async def health_check() -> dict[str, object]:
    """服务健康检查"""
    return {
        "status": "ok",
        "version": __version__,
        "has_openai_key": bool(settings.OPENAI_API_KEY),
        "has_tavily_key": bool(settings.TAVILY_API_KEY),
    }


@app.get("/ready")
async def readiness_check() -> dict[str, str]:
    """Verify dependencies required to accept research runs."""
    try:
        await asyncio.to_thread(ping_db)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc
    return {"status": "ready", "version": __version__}


@app.get("/api/v1/info")
async def api_info() -> dict[str, object]:
    """API 版本和功能信息"""
    return {
        "version": __version__,
        "features": [
            "research_runs",
            "human_review",
            "source_management",
            "claim_extraction",
            "citation_checking",
            "sse_events",
            "export_markdown",
            "export_json",
        ],
        "models": {
            "planner": settings.PLANNER_MODEL,
            "researcher": settings.RESEARCHER_MODEL,
            "writer": settings.WRITER_MODEL,
            "reviewer": settings.REVIEWER_MODEL,
        },
    }


# ═══════════════════════════════════════════
# Run CRUD
# ═══════════════════════════════════════════


@app.post("/api/v1/runs", response_model=CreateRunResponse, status_code=201)
async def create_run_endpoint(req: CreateRunRequest) -> CreateRunResponse:
    """创建研究任务并立即启动

    返回 run_id 和 thread_id。通过 GET /runs/{run_id}/events 接收实时事件。
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"

    await asyncio.to_thread(
        create_run,
        run_id,
        thread_id,
        req.topic,
        language=req.language,
        target_words=req.target_words,
        require_human_approval=req.require_human_approval,
    )
    requirements = ResearchRequirements(
        topic=req.topic,
        purpose=req.purpose,
        audience=req.audience,
        language=req.language,
        target_words=req.target_words,
        preferred_domains=req.preferred_domains,
        excluded_domains=req.excluded_domains,
        require_human_approval=req.require_human_approval,
        max_iterations=settings.MAX_ITERATIONS,
        max_queries=settings.MAX_QUERIES,
        max_sources=req.max_sources,
        max_cost_usd=settings.MAX_BUDGET_USD,
    )
    initial_state = create_initial_state(
        topic=req.topic,
        run_id=run_id,
        thread_id=thread_id,
        requirements=requirements,
        require_human_approval=req.require_human_approval,
        status="running",
    )
    try:
        await run_coordinator.start(run_id, thread_id, initial_state)
    except Exception as exc:
        await asyncio.to_thread(update_run_status, run_id, "failed")
        raise HTTPException(status_code=500, detail=f"任务启动失败: {exc}") from exc

    return CreateRunResponse(run_id=run_id, thread_id=thread_id, status="running")


@app.get("/api/v1/runs/{run_id}", response_model=RunInfoResponse)
async def get_run_endpoint(run_id: str) -> RunInfoResponse:
    """查询单个任务状态"""
    run = await _require_run(run_id)

    info = run.to_dict()
    return RunInfoResponse(
        run_id=info["run_id"],
        topic=info["topic"],
        status=info["status"],
        current_node=info.get("current_node"),
        iteration=info.get("iteration", 0),
        require_human_approval=info.get("require_human_approval", True),
        total_cost_usd=info.get("total_cost_usd", 0.0),
        error_count=info.get("error_count", 0),
        created_at=info["created_at"],
        updated_at=info["updated_at"],
        completed_at=info.get("completed_at"),
    )


@app.get("/api/v1/runs", response_model=RunListResponse)
async def list_runs_endpoint(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(
        None, pattern="^(queued|running|waiting_human|completed|failed|cancelled)$"
    ),
) -> RunListResponse:
    """列出任务, 支持分页和状态筛选"""
    page, total = await asyncio.gather(
        asyncio.to_thread(list_runs, limit, offset, status),
        asyncio.to_thread(count_runs, status),
    )
    has_more = (offset + limit) < total

    items = [
        RunInfoResponse(
            run_id=r.id,
            topic=r.topic,
            status=r.status,
            current_node=r.current_node,
            iteration=r.iteration,
            require_human_approval=r.require_human_approval,
            total_cost_usd=r.total_cost_usd,
            error_count=r.error_count,
            created_at=r.created_at.isoformat(),
            updated_at=r.updated_at.isoformat(),
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
        )
        for r in page
    ]
    return RunListResponse(
        items=items,
        pagination=PaginationMeta(total=total, limit=limit, offset=offset, has_more=has_more),
    )


# ═══════════════════════════════════════════
# SSE 实时事件
# ═══════════════════════════════════════════


@app.get("/api/v1/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    after: int = Query(0, ge=0, description="Replay events after this sequence"),
) -> StreamingResponse:
    """运行事件 SSE 流

    前端使用 EventSource 连接。
    支持断线重连: 通过 Last-Event-ID header 从断点继续。
    """
    run = await _require_run(run_id)

    # 断线重连
    last_event_id = after
    if request.headers.get("last-event-id"):
        try:
            last_event_id = int(request.headers["last-event-id"])
        except (ValueError, TypeError):
            pass

    return StreamingResponse(
        event_stream(run.id, request, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ═══════════════════════════════════════════
# 人工审批
# ═══════════════════════════════════════════


@app.post("/api/v1/runs/{run_id}/review")
async def review_run(run_id: str, req: ReviewRequest) -> dict[str, str]:
    """人工审批任务

    只有 waiting_human 状态的任务可以审批。
    合法动作: approve (发布), revise (退回修改), cancel (取消)
    """
    run = await _require_run(run_id)

    if run.status != "waiting_human":
        raise HTTPException(
            status_code=400,
            detail=f"任务状态为 {run.status}, 不可审批。仅 waiting_human 可审批。",
        )

    if req.action == "revise" and not req.feedback.strip():
        raise HTTPException(status_code=400, detail="退回修改时必须提供 feedback")

    decision = HumanDecision(action=req.action, feedback=req.feedback)
    await asyncio.to_thread(save_human_decision, run_id, decision)

    if req.action == "cancel":
        await run_coordinator.cancel(run_id)
        new_status = "cancelled"
    else:
        from langgraph.types import Command

        started = await run_coordinator.start(
            run_id,
            run.thread_id,
            Command(resume={"action": req.action, "feedback": req.feedback}),
            event_type="resumed",
        )
        if not started:
            raise HTTPException(status_code=409, detail="任务已在恢复或运行中")
        new_status = "running"

    return {
        "run_id": run_id,
        "action": req.action,
        "new_status": new_status,
        "feedback": req.feedback,
    }


# ═══════════════════════════════════════════
# 来源查询
# ═══════════════════════════════════════════


@app.get("/api/v1/runs/{run_id}/sources")
async def get_run_sources(
    run_id: str,
    source_type: str | None = Query(None),
    min_credibility: float | None = Query(None, ge=0.0, le=1.0),
    status: str | None = Query(None, pattern="^(pending|success|failed)$"),
    limit: int = Query(50, ge=1, le=200),
) -> list[SourceResponse]:
    """获取研究的来源列表, 支持筛选"""
    await _require_run(run_id)

    sources = await asyncio.to_thread(get_sources, run_id)

    # 筛选
    if source_type:
        sources = [s for s in sources if s.source_type == source_type]
    if min_credibility is not None:
        sources = [s for s in sources if s.credibility_score >= min_credibility]
    if status:
        sources = [s for s in sources if s.extraction_status == status]

    return [
        SourceResponse(
            id=s.id,
            url=s.canonical_url,
            title=s.title,
            publisher=s.publisher,
            source_type=s.source_type,
            credibility_score=s.credibility_score,
            extraction_status=s.extraction_status,
            extraction_error=s.extraction_error,
        )
        for s in sources[:limit]
    ]


@app.get("/api/v1/runs/{run_id}/sources/{source_id}")
async def get_source_detail(run_id: str, source_id: str) -> dict[str, object]:
    """获取单个来源详情, 含提取的正文"""
    await _require_run(run_id)

    sources = await asyncio.to_thread(get_sources, run_id)
    for s in sources:
        if s.id == source_id:
            content = await asyncio.to_thread(_read_artifact_preview, s.content_location)

            return {
                "id": s.id,
                "url": s.canonical_url,
                "title": s.title,
                "publisher": s.publisher,
                "author": s.author,
                "published_at": s.published_at.isoformat() if s.published_at else None,
                "retrieved_at": s.retrieved_at.isoformat() if s.retrieved_at else None,
                "source_type": s.source_type,
                "credibility_score": s.credibility_score,
                "extraction_status": s.extraction_status,
                "extraction_error": s.extraction_error,
                "content_preview": content[:5000] if content else None,
            }

    raise HTTPException(status_code=404, detail=f"Source {source_id} not found")


# ═══════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════


@app.get("/api/v1/runs/{run_id}/reports")
async def get_run_reports(run_id: str) -> list[ReportVersionResponse]:
    """获取报告版本列表"""
    await _require_run(run_id)
    versions = await asyncio.to_thread(get_report_versions, run_id)
    return [
        ReportVersionResponse(
            id=v.id,
            version=v.version,
            created_by=v.created_by_node,
            created_at=v.created_at.isoformat(),
            length=len(v.markdown),
        )
        for v in versions
    ]


@app.get("/api/v1/runs/{run_id}/reports/{version_id}")
async def get_report_detail(run_id: str, version_id: str) -> dict[str, object]:
    """获取某版本报告的完整内容"""
    await _require_run(run_id)
    versions = await asyncio.to_thread(get_report_versions, run_id)
    for v in versions:
        if v.id == version_id:
            return {
                "id": v.id,
                "run_id": run_id,
                "version": v.version,
                "created_by": v.created_by_node,
                "created_at": v.created_at.isoformat(),
                "markdown": v.markdown,
                "length": len(v.markdown),
            }
    raise HTTPException(status_code=404, detail=f"Version {version_id} not found")


# ═══════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════


@app.get("/api/v1/runs/{run_id}/export", response_model=None)
async def export_report(
    run_id: str,
    format: Literal["markdown", "json"] = Query("markdown"),
) -> PlainTextResponse | dict[str, object]:
    """导出最终报告

    支持格式: markdown, json
    JSON 格式包含来源和 Claim 映射, 便于其他系统继续使用。
    """
    run = await _require_run(run_id)

    versions = await asyncio.to_thread(get_report_versions, run_id)
    if not versions:
        raise HTTPException(status_code=404, detail="该任务没有报告版本")

    latest = versions[0]

    if format == "json":
        sources = await asyncio.to_thread(get_sources, run_id)
        return {
            "run_id": run_id,
            "topic": run.topic,
            "status": run.status,
            "report": latest.markdown,
            "metadata": {
                "version": latest.version,
                "created_at": latest.created_at.isoformat(),
                "created_by": latest.created_by_node,
                "total_versions": len(versions),
            },
            "sources": [
                {
                    "id": s.id,
                    "url": s.canonical_url,
                    "title": s.title,
                    "type": s.source_type,
                    "credibility": s.credibility_score,
                }
                for s in sources
            ],
            "exported_at": datetime.now().isoformat(),
            "crewflow_version": __version__,
        }

    return PlainTextResponse(
        content=latest.markdown,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="report_{run_id}.md"',
        },
    )


@app.get("/api/v1/runs/{run_id}/export/versions")
async def export_all_versions(run_id: str) -> list[dict[str, object]]:
    """导出所有报告版本 (JSON)"""
    await _require_run(run_id)
    versions = await asyncio.to_thread(get_report_versions, run_id)
    return [
        {
            "version": v.version,
            "created_by": v.created_by_node,
            "created_at": v.created_at.isoformat(),
            "length": len(v.markdown),
            "preview": v.markdown[:500],
        }
        for v in versions
    ]


# ═══════════════════════════════════════════
# 任务操作
# ═══════════════════════════════════════════


@app.post("/api/v1/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict[str, str]:
    """取消任务"""
    run = await asyncio.to_thread(get_run, run_id)
    if not run:
        raise HTTPException(status_code=404)
    if run.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"任务已{run.status}, 无法取消")
    await run_coordinator.cancel(run_id)
    return {"run_id": run_id, "status": "cancelled"}


# ═══════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
