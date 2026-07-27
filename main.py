"""CrewFlow CLI 入口 - 终端运行多 Agent 协作"""

from __future__ import annotations

import uuid
from datetime import datetime
from dotenv import load_dotenv

from src.graph import build_graph
from src.state import create_initial_state

load_dotenv()


def main():
    """CLI 模式运行 CrewFlow"""
    print("=" * 60)
    print("  CrewFlow v0.2 - Multi-Agent 协作研究系统")
    print("    Validate → Researcher → Analyst → Writer → Reviewer")
    print("    → Publisher / Human Review")
    print("=" * 60)

    topic = input("\n请输入研究课题: ").strip()
    if not topic:
        print("课题不能为空")
        return

    print(f"\n课题: {topic}")
    print("启动研究团队...\n")

    # 构建图 (应用启动时构建一次)
    graph = build_graph()

    # 创建运行 ID 和 thread_id
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"

    # 配置
    config = {
        "configurable": {"thread_id": thread_id},
    }

    # 初始状态
    initial_state = create_initial_state(
        topic=topic,
        run_id=run_id,
        thread_id=thread_id,
        require_human_approval=False,  # CLI 模式默认不需要人工审批
    )

    # 执行
    try:
        for event in graph.stream(
            initial_state,
            config=config,
            stream_mode="updates",
        ):
            for node_name, update in event.items():
                if node_name == "__interrupt__":
                    print("  ⏸️  等待人工输入...")
                    continue
                status = update.get("status", "")
                if status == "completed":
                    print(f"  ✅ [{node_name}] 完成")
                elif status == "failed":
                    print(f"  ❌ [{node_name}] 失败: {update.get('errors', [''])}")
                else:
                    print(f"  → [{node_name}] 完成")

                # 显示错误
                errors = update.get("errors", [])
                if errors:
                    for err in errors:
                        print(f"    ⚠️  {err}")

        # 获取最终状态
        final_state = graph.get_state(config)
        report = final_state.values.get("final_report")

        if report:
            print("\n" + "=" * 60)
            print("  最终报告")
            print("=" * 60)
            preview = report[:1000]
            print(preview)
            if len(report) > 1000:
                print(f"\n  ... (共 {len(report)} 字, 已保存至 output/)")
        else:
            status = final_state.values.get("status", "unknown")
            print(f"\n⚠️ 未能生成最终报告 (状态: {status})")
            errors = final_state.values.get("errors", [])
            if errors:
                for err in errors:
                    print(f"  ⚠️  {err}")

    except KeyboardInterrupt:
        print("\n\n中断执行")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
