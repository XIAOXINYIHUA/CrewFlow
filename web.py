"""CrewFlow 任务工作台 — 消费 API 的闭环 UI

不再直接操作 Graph, 通过 gr.State 管理会话状态。
流程: 填表 → 开始 → 执行(流式) → 审批(显示草稿) → 继续(流式) → 完成
"""

from __future__ import annotations

import difflib
import json
import uuid
from datetime import datetime

import gradio as gr

from src.config import settings
from src.database import init_db
from src.graph import build_graph
from src.models import HumanDecision, ResearchRequirements
from src.repository import (
    create_run,
    get_report_versions,
    get_sources,
    list_runs,
    save_human_decision,
)
from src.state import create_initial_state

# ── 人类可读的阶段名称 ──
STAGE_LABELS = {
    "validate_input": "校验输入",
    "planner": "正在制定研究计划",
    "researcher": "正在搜索相关资料",
    "source_processor": "正在读取和整理来源",
    "claim_builder": "正在提取关键事实",
    "coverage_checker": "正在检查资料是否充分",
    "outline_builder": "正在组织报告结构",
    "analyst": "正在综合分析",
    "writer": "正在撰写报告",
    "citation_checker": "正在核对事实和引用",
    "reviewer": "正在进行质量审查",
    "publisher": "正在生成最终版本",
    "human_review": "等待人工审批",
}

STAGE_ORDER = [
    "validate_input",
    "planner",
    "researcher",
    "source_processor",
    "claim_builder",
    "coverage_checker",
    "outline_builder",
    "analyst",
    "writer",
    "citation_checker",
    "reviewer",
    "publisher",
]

AUDIENCE_MAP = {
    "general": "普通读者",
    "engineer": "工程师",
    "manager": "管理者",
    "executive": "高层决策者",
    "academic": "学术读者",
}
LANG_MAP = {"中文": "zh-CN", "English": "en", "日本語": "ja"}


# ═══════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════


def _stage_progress(node: str) -> float:
    if node in STAGE_ORDER:
        return (STAGE_ORDER.index(node) + 1) / len(STAGE_ORDER)
    return 0.5


def _stage_summary(node: str, sources: int = 0, iteration: int = 0) -> str:
    label = STAGE_LABELS.get(node, node)
    parts = [f"当前: {label}"]
    if sources:
        parts.append(f"来源: {sources}")
    if iteration:
        parts.append(f"第 {iteration} 轮修改")
    return " · ".join(parts)


def _fmt_issues(review) -> str:
    if not review or not review.issues:
        return "未发现质量问题。"
    lines = []
    for i in review.issues:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(i.severity, "⚪")
        lines.append(f"- {icon} **[{i.severity}] {i.description}**")
        if i.suggestion:
            lines.append(f"  - 建议: {i.suggestion}")
        if i.paragraph_ref:
            lines.append(f"  - 位置: {i.paragraph_ref}")
    return "\n".join(lines)


def on_cancel(session):
    """取消正在运行的任务"""
    run_id = session.get("run_id")
    if run_id:
        try:
            from src.repository import update_run_status

            update_run_status(run_id, "cancelled")
        except Exception:
            pass
    session["status"] = "cancelled"
    logs = session.get("logs", "") + "\n🛑 任务已取消"
    return (
        session,
        logs,
        "🛑 任务已取消",
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(interactive=True),
        gr.update(value=1.0),
    )


def on_recover(run_id: str, session: dict):
    """从数据库恢复已运行的任务 (页面刷新后)"""
    if not run_id:
        yield (
            session,
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            "",
            0,
        )
        return

    from src.repository import get_run

    run = get_run(run_id)
    if not run:
        yield (
            session,
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            "未找到任务",
            0,
        )
        return

    session.update(
        run_id=run.id,
        thread_id=run.thread_id,
        topic=run.topic,
        status=run.status,
        logs="",
        draft="",
        source_count=0,
    )

    if run.status == "completed":
        sources_md = _load_sources_md(run.id)
        versions = get_report_versions(run.id)
        report = versions[0].markdown if versions else ""
        yield (
            session,
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
            report,
            sources_md,
            "✅ 任务已完成",
            1.0,
        )
    elif run.status == "waiting_human":
        graph = build_graph()
        config = {"configurable": {"thread_id": run.thread_id}}
        state = graph.get_state(config)
        draft = state.values.get("draft", "")
        review = state.values.get("review")
        session["draft"] = draft
        rev_md = "### 审查评分\n"
        if review:
            rev_md += (
                f"- 事实: {review.factuality_score}/100\n- 引用: {review.citation_score}/100\n"
                f"- 覆盖: {review.coverage_score}/100\n- 结构: {review.structure_score}/100\n"
                f"- 结论: **{review.verdict}**\n\n### 发现的问题\n{_fmt_issues(review)}"
            )
        yield (
            session,
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            draft,
            rev_md,
            "⏸️  等待审批",
            0.9,
        )
    else:
        yield (
            session,
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            f"状态: {run.status}",
            0,
        )


def _make_citations_clickable(md: str) -> str:
    """将报告中的 [Sxxx] 转为可点击锚点 (指向来源面板)"""
    import re

    def _replace(m):
        cid = m.group(1)
        return (
            f'<a href="#source-{cid}" '
            'style="text-decoration:none;color:#4f46e5;font-weight:500;" '
            f'title="查看来源 {cid}">[{cid}]</a>'
        )

    return re.sub(r"\[([a-zA-Z0-9_]+)\]", _replace, md)


def _load_sources_md(run_id: str) -> str:
    if not run_id:
        return "暂无来源数据"
    try:
        sources = get_sources(run_id)
    except Exception:
        return "来源数据暂不可用"

    if not sources:
        return "暂无来源"
    lines = [f"### 来源 ({len(sources)} 个)\n"]
    for s in sources[:25]:
        domain = s.canonical_url.split("/")[2] if "//" in s.canonical_url else s.canonical_url[:40]
        icon = {"success": "✅", "failed": "❌", "pending": "⏳"}.get(s.extraction_status, "❓")
        lines.append(
            f'<div id="source-{s.id}" '
            'style="padding:0.5rem;margin:0.3rem 0;border-left:3px solid #e5e7eb;">'
            f"{icon} <strong>{s.title or '(无标题)'}</strong><br>"
            f'<code style="font-size:0.85em;word-break:break-all;">{domain}</code> | '
            f"类型: {s.source_type} | 可信度: {s.credibility_score:.0%}<br>"
            f"状态: {s.extraction_status}</div>"
        )
    return "\n".join(lines)


# ── 任务历史 ──


def load_run_history() -> str:
    """Render the most recent persisted research runs as Markdown."""
    try:
        runs = list_runs(limit=20)
    except Exception as exc:
        return f"历史记录暂不可用：{exc}"

    if not runs:
        return "暂无历史研究。"

    status_icon = {
        "queued": "⏳",
        "running": "🔄",
        "waiting_human": "⏸️",
        "completed": "✅",
        "failed": "❌",
        "cancelled": "🛑",
    }
    lines = ["### 最近研究"]
    for run in runs:
        icon = status_icon.get(run.status, "•")
        created_at = run.created_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"- {icon} **{run.topic}** · `{run.status}` · {created_at} · `{run.id}`")
    return "\n".join(lines)


def load_recover_options() -> list[tuple[str, str]]:
    """Return dropdown choices for persisted runs."""
    try:
        runs = list_runs(limit=50)
    except Exception:
        return []
    return [(f"{run.topic[:60]} · {run.status}", run.id) for run in runs]


def load_versions(run_id: str) -> list[tuple[str, str]]:
    """Return report-version dropdown choices for a run."""
    if not run_id:
        return []
    versions = get_report_versions(run_id)
    return [
        (
            f"v{version.version} · {version.created_at:%Y-%m-%d %H:%M} · {version.created_by_node}",
            version.id,
        )
        for version in versions
    ]


def _version_map(run_id: str) -> dict[str, object]:
    return {version.id: version for version in get_report_versions(run_id)}


def load_version_content(version_id: str, session: dict) -> str:
    """Load one persisted report version."""
    if not version_id:
        return ""
    version = _version_map(session.get("run_id", "")).get(version_id)
    return version.markdown if version else "未找到该报告版本。"


def diff_versions(version_a: str, version_b: str, session: dict) -> str:
    """Render a unified Markdown diff for two persisted versions."""
    if not version_a or not version_b:
        return "请选择两个报告版本。"
    versions = _version_map(session.get("run_id", ""))
    left = versions.get(version_a)
    right = versions.get(version_b)
    if left is None or right is None:
        return "未找到选中的报告版本。"
    if version_a == version_b:
        return "两个选择指向同一版本。"

    diff = difflib.unified_diff(
        left.markdown.splitlines(),
        right.markdown.splitlines(),
        fromfile=f"v{left.version}",
        tofile=f"v{right.version}",
        lineterm="",
    )
    content = "\n".join(diff)
    return f"```diff\n{content}\n```" if content else "两个版本内容相同。"


def _run_graph(session: dict, resume: dict | None = None):
    """执行图并 yield 事件 (核心生成器)"""
    graph = build_graph()
    thread_id = session["thread_id"]
    config = {"configurable": {"thread_id": thread_id}}
    logs = session.get("logs", "")
    src_count = session.get("source_count", 0)

    if resume:
        from langgraph.types import Command

        events = list(graph.stream(Command(resume=resume), config=config, stream_mode="updates"))
    else:
        state = create_initial_state(
            topic=session["topic"],
            run_id=session["run_id"],
            thread_id=thread_id,
            requirements=session["requirements"],
            require_human_approval=session["require_human_approval"],
        )
        events = list(graph.stream(state, config=config, stream_mode="updates"))

    for event in events:
        for node, upd in event.items():
            # ── interrupt ──
            if node == "__interrupt__":
                gs = graph.get_state(config)
                draft = gs.values.get("draft", "")
                review = gs.values.get("review")

                session["status"] = "waiting_human"
                session["draft"] = draft
                logs += "⏸️  等待人工审批...\n"

                rev_md = "### 审查评分\n"
                if review:
                    rev_md += (
                        f"- 事实: {review.factuality_score}/100\n"
                        f"- 引用: {review.citation_score}/100\n"
                        f"- 覆盖: {review.coverage_score}/100\n"
                        f"- 结构: {review.structure_score}/100\n"
                        f"- 结论: **{review.verdict}**\n\n"
                        f"### 发现的问题\n{_fmt_issues(review)}"
                    )
                yield (
                    session,
                    logs,
                    draft,
                    rev_md,
                    gr.update(visible=True),  # review_panel
                    gr.update(visible=False),  # progress_panel
                    gr.update(visible=False),  # final_panel
                    _stage_summary("human_review", src_count),
                    gr.update(value=0.9),
                    gr.update(interactive=True),
                )
                return  # 暂停

            # ── 普通节点 ──
            status = upd.get("status", "")
            label = STAGE_LABELS.get(node, node)

            if upd.get("sources"):
                src_count += len(upd["sources"])
            if status == "completed":
                logs += f"✅ {label}\n"
            elif status == "failed":
                logs += f"❌ {label}\n"
                for e in upd.get("errors", []):
                    if e:
                        logs += f"  ⚠️  {e}\n"
            else:
                logs += f"  ➡️ {label}\n"

            review = upd.get("review")
            if review:
                logs += (
                    f"  📋 {review.verdict} (事实:{review.factuality_score} "
                    f"引用:{review.citation_score})\n"
                )
            if upd.get("claims"):
                logs += f"  📌 {len(upd['claims'])} 条结论\n"

            yield (
                session,
                logs,
                "",
                "",
                gr.update(visible=False),
                gr.update(visible=True),
                gr.update(visible=False),
                _stage_summary(node, src_count),
                gr.update(value=_stage_progress(node)),
                gr.update(interactive=False),
            )

    # ── 完成 ──
    gs = graph.get_state(config)
    report = gs.values.get("final_report", "")
    status = gs.values.get("status", "completed")
    session["status"] = status
    logs += "\n✅ 研究完成！" if report else "\n⚠️ 未生成报告"
    sources_md = _load_sources_md(session["run_id"])

    yield (
        session,
        logs,
        "",
        "",
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=True),
        "✅ 研究完成",
        gr.update(value=1.0),
        gr.update(interactive=True),
    )

    # 最终报告
    yield (
        session,
        logs,
        report,
        sources_md,
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=True),
        "✅ 研究完成",
        gr.update(value=1.0),
        gr.update(interactive=True),
    )


# ═══════════════════════════════════════════════════════
# 事件处理
# ═══════════════════════════════════════════════════════


def on_start(topic, purpose, audience, lang, words, max_src, domains, approval, session):
    """开始研究 (非流式, 准备阶段)"""
    if not topic.strip():
        return (
            session,
            "",
            gr.update(interactive=True),
            "⚠️ 课题不能为空",
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            "",
            0,
        )

    lang_code = LANG_MAP.get(lang, "zh-CN")
    preferred = [d.strip() for d in domains.split(",") if d.strip()] if domains else []

    req = ResearchRequirements(
        topic=topic,
        purpose=purpose or None,
        audience=audience,
        language=lang_code,
        target_words=words,
        max_sources=max_src,
        preferred_domains=preferred,
        require_human_approval=approval,
    )

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"

    try:
        init_db()
        create_run(
            run_id=run_id,
            thread_id=thread_id,
            topic=topic,
            language=lang_code,
            require_human_approval=approval,
        )
    except Exception as e:
        print(f"  DB: {e}")

    session.update(
        run_id=run_id,
        thread_id=thread_id,
        topic=topic,
        requirements=req,
        require_human_approval=approval,
        status="running",
        logs="",
        draft="",
        source_count=0,
    )

    return (
        session,
        "",
        gr.update(interactive=False),
        "🚀 任务已创建，开始研究...",
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(visible=False),
        _stage_summary("planner"),
        0.0,
    )


def on_start_stream(session):
    """流式执行"""
    if session.get("status") != "running":
        return
    yield from _run_graph(session)


# ── 审批 ──


def _approve_action(action, feedback, session):
    """统一审批处理 (生成器)"""
    if session.get("status") != "waiting_human":
        yield (
            session,
            "",
            gr.update(visible=True),
            "⚠️ 状态异常，无法审批",
            "",
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            0,
            gr.update(interactive=True),
        )
        return

    if action == "revise" and not feedback.strip():
        yield (
            session,
            "",
            gr.update(visible=True),
            "⚠️ 退回修改时必须填写修改意见",
            "",
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            0,
            gr.update(interactive=True),
        )
        return

    # 记录
    decision = HumanDecision(action=action, feedback=feedback)
    try:
        save_human_decision(session["run_id"], decision)
    except Exception:
        pass

    session["status"] = "cancelled" if action == "cancel" else "running"
    logs = session.get("logs", "") + f"\n👤 人工决策: {action}"
    if feedback:
        logs += f"\n   意见: {feedback[:80]}"
    session["logs"] = logs

    if action == "cancel":
        yield (
            session,
            "",
            gr.update(visible=False),
            "🛑 任务已取消",
            "",
            gr.update(visible=False),
            gr.update(visible=True),
            "",
            0,
            gr.update(interactive=True),
        )
        return

    # 恢复图
    yield from _run_graph(session, resume={"action": action, "feedback": feedback})


# ── 导出 ──


def on_export(fmt, report, topic):
    if not report:
        return gr.update(), "报告为空"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic[:20]) or "report"
    out = settings.OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    if "Markdown" in fmt:
        p = out / f"{safe}_{ts}.md"
        p.write_text(report, encoding="utf-8")
        return str(p), f"✅ 已保存: {p.name}"
    if "JSON" in fmt:
        p = out / f"{safe}_{ts}.json"
        p.write_text(
            json.dumps(
                {"report": report, "topic": safe, "exported_at": ts}, ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        return str(p), f"✅ 已保存: {p.name}"
    return gr.update(), "不支持的格式"


# ═══════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════

CSS = """
.container { max-width: 960px; margin: auto; }
.report-box { border: 1px solid #d0d5dd; border-radius: 8px; padding: 1.5rem; background: #fafafa; }
"""

with gr.Blocks(title="CrewFlow", fill_height=True) as demo:
    ss = gr.State(
        {
            "run_id": None,
            "thread_id": None,
            "topic": "",
            "requirements": None,
            "require_human_approval": True,
            "status": "idle",
            "logs": "",
            "draft": "",
            "source_count": 0,
        }
    )

    gr.Markdown("# CrewFlow 深度研究\n从真实来源生成可验证的研究报告。")

    # ── 输入 / 历史 ──
    with gr.Column(visible=True) as input_panel:
        with gr.Tabs() as main_tabs:
            with gr.TabItem("🚀 新研究"):
                with gr.Group():
                    topic_i = gr.Textbox(
                        label="研究课题 *",
                        placeholder="例: 2025年生成式 AI 对软件工程效率的影响",
                        lines=2,
                    )
                    with gr.Row():
                        purpose_i = gr.Textbox(
                            label="研究目的", placeholder="内部决策 / 市场分析 / 学术论文", scale=2
                        )
                        audience_i = gr.Dropdown(
                            label="目标读者",
                            choices=[
                                ("普通读者", "general"),
                                ("工程师", "engineer"),
                                ("管理者", "manager"),
                                ("高层决策者", "executive"),
                                ("学术读者", "academic"),
                            ],
                            value="general",
                            scale=1,
                        )
                    with gr.Row():
                        lang_i = gr.Dropdown(
                            label="语言",
                            choices=["中文", "English", "日本語"],
                            value="中文",
                            scale=1,
                        )
                        words_i = gr.Slider(
                            label="报告长度",
                            minimum=500,
                            maximum=10000,
                            value=2500,
                            step=500,
                            scale=2,
                        )
                    with gr.Accordion("高级设置", open=False):
                        max_src_i = gr.Slider(
                            label="最大来源数", minimum=5, maximum=100, value=30, step=5
                        )
                        approval_i = gr.Checkbox(label="需要人工审批", value=True)
                        domains_i = gr.Textbox(
                            label="首选域名 (逗号分隔)",
                            placeholder="gov.cn, reuters.com, arxiv.org",
                        )
                    start_btn = gr.Button("🚀 开始研究", variant="primary", size="lg")
                    start_msg = gr.Markdown("")

            with gr.TabItem("📂 历史研究"):
                history_md = gr.Markdown("加载中...")
                recover_dd = gr.Dropdown(label="选择任务", choices=[])
                recover_btn = gr.Button("🔄 恢复任务", variant="secondary", size="sm")
                recover_msg = gr.Markdown("")

    # ── 进度 ──
    with gr.Column(elem_classes="container", visible=False) as progress_panel:
        stage_md = gr.Markdown("### 准备中...")
        progress_bar = gr.Slider(
            minimum=0,
            maximum=1,
            value=0,
            step=0.01,
            interactive=False,
            show_label=False,
            container=False,
        )
        with gr.Accordion("📋 运行日志", open=False):
            log_out = gr.Textbox(label="", lines=8, max_lines=20, interactive=False)
        cancel_btn = gr.Button("🛑 取消任务", variant="stop", size="sm")
        cancel_msg = gr.Markdown("", visible=False)

    # ── 审批 ──
    with gr.Column(visible=False) as review_panel:
        gr.Markdown("## 👤 报告审阅")
        with gr.Tabs():
            with gr.TabItem("📄 报告正文"):
                draft_md = gr.Markdown("加载中...", elem_classes="report-box")
            with gr.TabItem("🔎 审查意见"):
                review_md = gr.Markdown("")
        with gr.Group():
            gr.Markdown("### 你的决定")
            feedback_i = gr.Textbox(
                label="修改意见 (退回时必填)", placeholder="请指明需要补充哪些内容...", lines=2
            )
            with gr.Row():
                approve_btn = gr.Button(
                    "✅ 批准并发布", variant="primary", size="sm", min_width=160
                )
                revise_btn = gr.Button("📝 退回修改", variant="secondary", size="sm", min_width=160)
                cancel_review_btn = gr.Button("🛑 取消", variant="stop", size="sm", min_width=120)
            review_status = gr.Markdown("")

    # ── 完成 ──
    with gr.Column(visible=False) as final_panel:
        with gr.Tabs():
            with gr.TabItem("📄 最终报告"):
                final_md = gr.Markdown("", elem_classes="report-box")
            with gr.TabItem("🔗 来源"):
                sources_md = gr.Markdown("等待报告生成...")
            with gr.TabItem("📋 版本历史"):
                with gr.Row():
                    v1_dd = gr.Dropdown(label="版本 1", choices=[], scale=1)
                    v2_dd = gr.Dropdown(label="版本 2", choices=[], scale=1)
                diff_btn = gr.Button("📊 比较差异", size="sm", variant="secondary")
                diff_output = gr.Markdown("选择两个版本后点击比较")
        with gr.Row():
            export_fmt = gr.Dropdown(
                label="格式",
                choices=["Markdown (.md)", "JSON (.json)"],
                value="Markdown (.md)",
                scale=1,
            )
            export_btn = gr.Button("💾 下载", variant="secondary", scale=1)
        export_file = gr.File(label="下载", visible=True)
        export_msg = gr.Markdown("")

    # ── 任务恢复 (隐藏, 通过 URL 参数使用) ──
    recover_input = gr.Textbox(visible=False, label="恢复任务 ID")

    # ═══════════════════════════════════════
    # 事件
    # ═══════════════════════════════════════

    # 开始 (准备+流式)
    click1 = start_btn.click(
        fn=on_start,
        inputs=[
            topic_i,
            purpose_i,
            audience_i,
            lang_i,
            words_i,
            max_src_i,
            domains_i,
            approval_i,
            ss,
        ],
        outputs=[
            ss,
            start_msg,
            start_btn,
            start_msg,
            input_panel,
            progress_panel,
            review_panel,
            stage_md,
            progress_bar,
        ],
    ).then(
        fn=on_start_stream,
        inputs=[ss],
        outputs=[
            ss,
            log_out,
            draft_md,
            review_md,
            review_panel,
            progress_panel,
            final_panel,
            stage_md,
            progress_bar,
            start_btn,
        ],
    )

    # 取消 (运行中)
    cancel_btn.click(
        fn=on_cancel,
        inputs=[ss],
        outputs=[ss, log_out, cancel_msg, progress_panel, final_panel, start_btn, progress_bar],
    )

    # 恢复任务 (从 DB 重载)
    recover_input.change(
        fn=on_recover,
        inputs=[recover_input, ss],
        outputs=[
            ss,
            input_panel,
            progress_panel,
            final_panel,
            final_md,
            sources_md,
            stage_md,
            progress_bar,
        ],
    )

    # 审批
    def _make_action_handler(action):
        def fn(feedback, session):
            yield from _approve_action(action, feedback, session)

        return fn

    # 我们需要将所有审批输出合并
    APPROVE_OUTPUTS = [
        ss,
        review_status,
        review_panel,
        review_panel,
        final_panel,
        final_panel,
        draft_md,
        review_md,
        log_out,
        stage_md,
        progress_bar,
        start_btn,
    ]
    # 实际上先简化: approve 和 cancel 最终跳转到 final_panel
    # revise 跳回 progress_panel

    approve_btn.click(
        fn=lambda fb, s: next(_approve_action("approve", fb, s)),
        inputs=[feedback_i, ss],
        outputs=[ss, review_status],
    ).then(
        fn=lambda s: (
            _load_sources_md(s.get("run_id", "")),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
        ),
        inputs=[ss],
        outputs=[sources_md, review_panel, progress_panel, final_panel],
    )

    revise_btn.click(
        fn=_make_action_handler("revise"),
        inputs=[feedback_i, ss],
        outputs=[
            ss,
            review_status,
            draft_md,
            review_md,
            review_panel,
            progress_panel,
            final_panel,
            stage_md,
            progress_bar,
            start_btn,
        ],
    )

    cancel_review_btn.click(
        fn=lambda fb, s: next(_approve_action("cancel", fb, s)),
        inputs=[feedback_i, ss],
        outputs=[ss, review_status],
    ).then(
        fn=lambda: (
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
            "🛑 任务已取消",
        ),
        outputs=[review_panel, progress_panel, final_panel, final_md],
    )

    # 导出
    export_btn.click(
        fn=on_export, inputs=[export_fmt, final_md, topic_i], outputs=[export_file, export_msg]
    )

    # 加载历史
    def _load_history():
        return load_run_history(), gr.update(choices=load_recover_options())

    demo.load(fn=_load_history, outputs=[history_md, recover_dd])

    # 恢复任务 (从下拉选择)
    recover_btn.click(
        fn=lambda rid: rid,
        inputs=[recover_dd],
        outputs=[recover_input],
    ).then(
        fn=on_recover,
        inputs=[recover_input, ss],
        outputs=[
            ss,
            input_panel,
            progress_panel,
            final_panel,
            final_md,
            sources_md,
            stage_md,
            progress_bar,
        ],
    )

    # 加载版本 (完成时)
    def _load_versions(session, report):
        if not report:
            return gr.update(choices=[["", "无版本"]]), gr.update(choices=[["", "无版本"]])
        opts = load_versions(session.get("run_id", ""))
        value = opts[0][1] if opts else ""
        return gr.update(choices=opts, value=value), gr.update(choices=opts)

    final_md.change(
        fn=_load_versions,
        inputs=[ss, final_md],
        outputs=[v1_dd, v2_dd],
    )

    # 查看版本
    v1_dd.change(fn=load_version_content, inputs=[v1_dd, ss], outputs=[final_md])

    # 版本差异
    diff_btn.click(fn=diff_versions, inputs=[v1_dd, v2_dd, ss], outputs=[diff_output])

    # 完成时自动更新来源
    final_md.change(
        fn=lambda s, r: _load_sources_md(s.get("run_id", "")),
        inputs=[ss, final_md],
        outputs=[sources_md],
    )

if __name__ == "__main__":
    demo.launch(
        server_name=settings.WEB_HOST,
        server_port=settings.WEB_PORT,
        share=False,
        css=CSS,
        theme=gr.themes.Soft(),
    )
