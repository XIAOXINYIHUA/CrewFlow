"""CrewFlow FastAPI API — 任务创建、查询、审批、导出、SSE 事件流"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from src.config import settings
from src.database import init_db
from src.graph import build_graph
from src.models import HumanDecision
from src.repository import (
    create_run,
    get_report_versions,
    get_run,
    get_sources,
    list_runs,
    save_human_decision,
    update_run_status,
)
from src.state import create_initial_state

app = FastAPI(title="CrewFlow API", version="0.2.0")


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
    action: str = Field(..., pattern="^(approve|revise|cancel)$")
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


# ═══════════════════════════════════════════
# SSE 事件流 (支持断线重连 last-event-id)
# ═══════════════════════════════════════════


async def event_stream(
    run_id: str,
    thread_id: str,
    initial_state: dict,
    last_event_id: int = 0,
) -> AsyncGenerator[str, None]:
    """SSE 事件流, 支持 last-event-id 断线重连"""
    graph = build_graph()
    config = {"configurable": {"thread_id": thread_id}}

    update_run_status(run_id, "running")
    yield f"id: 0\ndata: {json.dumps({'type': 'started', 'run_id': run_id})}\n\n"

    def _run():
        return list(graph.stream(initial_state, config=config, stream_mode="updates"))

    try:
        events = await asyncio.to_thread(_run)

        for event_id, event in enumerate(events, 1):
            if event_id <= last_event_id:
                continue  # 跳过已发送事件

            for node_name, update in event.items():
                if node_name == "__interrupt__":
                    update_run_status(run_id, "waiting_human", current_node="human_review")
                    payload = {
                        "type": "interrupt",
                        "node": "human_review",
                        "run_id": run_id,
                    }
                    yield f"id: {event_id}\ndata: {json.dumps(payload)}\n\n"
                    continue

                payload: dict = {
                    "type": "node_completed",
                    "node": node_name,
                    "run_id": run_id,
                    "status": update.get("status", "running"),
                }
                review = update.get("review")
                if review:
                    payload["review_verdict"] = review.verdict
                    payload["review_scores"] = {
                        "factuality": review.factuality_score,
                        "citation": review.citation_score,
                        "coverage": review.coverage_score,
                        "structure": review.structure_score,
                    }
                errors = update.get("errors")
                if errors:
                    payload["errors"] = [e for e in errors if e]
                yield f"id: {event_id}\ndata: {json.dumps(payload)}\n\n"

        final_state = graph.get_state(config)
        report = final_state.values.get("final_report", "")
        status = final_state.values.get("status", "completed")
        update_run_status(run_id, status)
        payload = {
            "type": "completed",
            "run_id": run_id,
            "status": status,
            "has_report": bool(report),
        }
        yield f"id: {event_id + 1}\ndata: {json.dumps(payload)}\n\n"

    except Exception as e:
        update_run_status(run_id, "failed")
        yield f"data: {json.dumps({'type': 'error', 'run_id': run_id, 'error': str(e)})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


# ═══════════════════════════════════════════
# 健康检查 & 信息
# ═══════════════════════════════════════════


@app.get("/health")
async def health_check():
    """服务健康检查"""
    return {
        "status": "ok",
        "version": "0.2.0",
        "has_openai_key": bool(settings.OPENAI_API_KEY),
        "has_tavily_key": bool(settings.TAVILY_API_KEY),
    }


@app.get("/api/v1/info")
async def api_info():
    """API 版本和功能信息"""
    return {
        "version": "0.2.0",
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


@app.on_event("startup")
async def startup():
    try:
        init_db()
        print("  [API] 数据库初始化完成")
    except Exception as e:
        print(f"  [API] 数据库初始化跳过: {e}")


@app.post("/api/v1/runs", response_model=CreateRunResponse, status_code=201)
async def create_run_endpoint(req: CreateRunRequest):
    """创建研究任务并立即启动

    返回 run_id 和 thread_id。通过 GET /runs/{run_id}/events 接收实时事件。
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"

    create_run(
        run_id=run_id,
        thread_id=thread_id,
        topic=req.topic,
        language=req.language,
        target_words=req.target_words,
        require_human_approval=req.require_human_approval,
    )

    return CreateRunResponse(run_id=run_id, thread_id=thread_id, status="queued")


@app.get("/api/v1/runs/{run_id}", response_model=RunInfoResponse)
async def get_run_endpoint(run_id: str):
    """查询单个任务状态"""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

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
):
    """列出任务, 支持分页和状态筛选"""
    all_runs = list_runs(limit=limit + offset, offset=0)

    # 状态筛选
    if status:
        filtered = [r for r in all_runs if r.status == status]
    else:
        filtered = all_runs

    # 分页
    page = filtered[offset : offset + limit]
    total = len(filtered)
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
async def stream_run_events(run_id: str, request: Request):
    """运行事件 SSE 流

    前端使用 EventSource 连接。
    支持断线重连: 通过 Last-Event-ID header 从断点继续。
    """
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run.status in ("completed", "failed", "cancelled"):
        payload = {"type": "done", "run_id": run_id, "status": run.status}
        return PlainTextResponse(
            content=f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n",
            media_type="text/event-stream",
        )

    # 断线重连
    last_event_id = 0
    if request.headers.get("last-event-id"):
        try:
            last_event_id = int(request.headers["last-event-id"])
        except (ValueError, TypeError):
            pass

    initial_state = create_initial_state(
        topic=run.topic,
        run_id=run.id,
        thread_id=run.thread_id,
        require_human_approval=run.require_human_approval,
    )

    return StreamingResponse(
        event_stream(run.id, run.thread_id, initial_state, last_event_id=last_event_id),
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
async def review_run(run_id: str, req: ReviewRequest):
    """人工审批任务

    只有 waiting_human 状态的任务可以审批。
    合法动作: approve (发布), revise (退回修改), cancel (取消)
    """
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run.status != "waiting_human":
        raise HTTPException(
            status_code=400,
            detail=f"任务状态为 {run.status}, 不可审批。仅 waiting_human 可审批。",
        )

    decision = HumanDecision(action=req.action, feedback=req.feedback)
    save_human_decision(run_id, decision)

    # 恢复图执行
    graph = build_graph()
    config = {"configurable": {"thread_id": run.thread_id}}

    try:
        from langgraph.types import Command

        graph.invoke(
            Command(resume={"action": req.action, "feedback": req.feedback}),
            config=config,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复图执行失败: {e}")

    new_status = "cancelled" if req.action == "cancel" else "running"
    update_run_status(run_id, new_status)

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
):
    """获取研究的来源列表, 支持筛选"""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    sources = get_sources(run_id)

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
async def get_source_detail(run_id: str, source_id: str):
    """获取单个来源详情, 含提取的正文"""
    if not get_run(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    sources = get_sources(run_id)
    for s in sources:
        if s.id == source_id:
            content = ""
            if s.content_location:
                try:
                    import os.path

                    if os.path.exists(s.content_location):
                        with open(s.content_location, encoding="utf-8") as f:
                            content = f.read()[:20000]
                except Exception:
                    pass

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
async def get_run_reports(run_id: str):
    """获取报告版本列表"""
    if not get_run(run_id):
        raise HTTPException(status_code=404)
    versions = get_report_versions(run_id)
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
async def get_report_detail(run_id: str, version_id: str):
    """获取某版本报告的完整内容"""
    if not get_run(run_id):
        raise HTTPException(status_code=404)
    versions = get_report_versions(run_id)
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


@app.get("/api/v1/runs/{run_id}/export")
async def export_report(run_id: str, format: str = "markdown"):
    """导出最终报告

    支持格式: markdown, json
    JSON 格式包含来源和 Claim 映射, 便于其他系统继续使用。
    """
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    versions = get_report_versions(run_id)
    if not versions:
        raise HTTPException(status_code=404, detail="该任务没有报告版本")

    latest = versions[0]

    if format == "json":
        sources = get_sources(run_id)
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
            "crewflow_version": "0.2.0",
        }

    return PlainTextResponse(
        content=latest.markdown,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="report_{run_id}.md"',
        },
    )


@app.get("/api/v1/runs/{run_id}/export/versions")
async def export_all_versions(run_id: str):
    """导出所有报告版本 (JSON)"""
    if not get_run(run_id):
        raise HTTPException(status_code=404)
    versions = get_report_versions(run_id)
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
async def cancel_run(run_id: str):
    """取消任务"""
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404)
    if run.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"任务已{run.status}, 无法取消")
    update_run_status(run_id, "cancelled")
    return {"run_id": run_id, "status": "cancelled"}


# ═══════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
