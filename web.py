"""CrewFlow Gradio Web UI"""

import uuid
import gradio as gr
from dotenv import load_dotenv

from src.graph import build_graph

load_dotenv()


def run_crew(topic: str):
    """运行 CrewFlow 并流式返回进度"""
    if not topic.strip():
        yield "请输入研究课题", ""
        return

    graph = build_graph()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    logs = ""
    final_report = ""

    try:
        for event in graph.stream(
            {"topic": topic, "step": "init", "iteration": 0},
            config=config,
            stream_mode="updates",
        ):
            for node_name, update in event.items():
                if node_name == "__interrupt__":
                    continue

                step_names = {
                    "researcher": "🔍 Researcher 搜集中...",
                    "analyst": "📊 Analyst 分析中...",
                    "writer": "✍️ Writer 撰写中...",
                    "reviewer": "🔎 Reviewer 审查中...",
                }
                status = step_names.get(node_name, node_name)
                logs += f"{status}\n"
                yield logs, ""

        # 获取最终结果
        final_state = graph.get_state(config)
        final_report = final_state.values.get("final_report", "未生成报告")
        logs += "✅ 流程完成！"
        yield logs, final_report

    except Exception as e:
        logs += f"\n❌ 错误: {e}"
        yield logs, ""


# 构建 Gradio UI
with gr.Blocks(title="CrewFlow") as demo:
    gr.Markdown(
        "# CrewFlow - Multi-Agent 协作研究系统\n"
        "**Researcher** → **Analyst** → **Writer** → **Reviewer**"
    )

    with gr.Row():
        with gr.Column(scale=1):
            topic_input = gr.Textbox(
                label="研究课题",
                placeholder="例：2025年 AI Agent 技术发展趋势",
                lines=2,
            )
            run_btn = gr.Button("🚀 启动研究团队", variant="primary")

        with gr.Column(scale=2):
            progress = gr.Textbox(label="进度", lines=8, interactive=False)
            report = gr.Markdown(label="最终报告")

    run_btn.click(fn=run_crew, inputs=[topic_input], outputs=[progress, report])


if __name__ == "__main__":
    demo.launch(share=False)
