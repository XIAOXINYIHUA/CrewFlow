"""CrewFlow CLI 入口 - 终端运行多 Agent 协作"""

import uuid
from dotenv import load_dotenv
from langgraph.types import Command

from src.graph import build_graph

load_dotenv()


def main():
    """CLI 模式运行 CrewFlow"""
    print("=" * 60)
    print("  CrewFlow - Multi-Agent 协作研究系统")
    print("  Researcher → Analyst → Writer → Reviewer")
    print("=" * 60)

    topic = input("\n请输入研究课题: ").strip()
    if not topic:
        print("课题不能为空")
        return

    print(f"\n课题: {topic}")
    print("启动研究团队...\n")

    # 构建图
    graph = build_graph()

    # 配置（含 thread_id 用于状态持久化）
    config = {
        "configurable": {"thread_id": str(uuid.uuid4())},
    }

    # 执行
    try:
        for event in graph.stream(
            {"topic": topic, "step": "init", "iteration": 0},
            config=config,
            stream_mode="updates",
        ):
            for node_name, update in event.items():
                if node_name != "__interrupt__":
                    print(f"  → [{node_name}] 完成")

        # 获取最终状态
        final_state = graph.get_state(config)
        report = final_state.values.get("final_report")

        if report:
            print("\n" + "=" * 60)
            print("  最终报告")
            print("=" * 60)
            print(report)
        else:
            print("\n⚠️ 未能生成最终报告")

    except KeyboardInterrupt:
        print("\n\n中断执行")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")


if __name__ == "__main__":
    main()
