"""Interactive CLI for the general BizInsight SupervisorAgent."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from agentscope.message import UserMsg

from bizinsight.agents.supervisor import build_supervisor_agent
from bizinsight.app import build_dashscope_model
from bizinsight.config import BizInsightSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--question",
        help="Run one question and exit; omit for an interactive conversation.",
    )
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    settings = BizInsightSettings()
    agent = build_supervisor_agent(
        model=build_dashscope_model(settings),
        project_root=root,
        settings=settings,
    )

    async def ask(text: str) -> None:
        response = await agent.reply(UserMsg(name="user", content=text))
        print(response.get_text_content())

    if args.question:
        await ask(args.question)
        return

    print("BizInsight Supervisor 已启动。输入 exit 或 quit 退出。")
    while True:
        try:
            question = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if question.lower() in {"exit", "quit"}:
            return
        if question:
            await ask(question)


def main() -> None:
    # Windows consoles default to GBK; model replies may contain emoji or
    # other non-GBK characters, and piped interactive input may arrive as
    # UTF-8. Reconfigure both streams to UTF-8 with replacement so neither
    # printing nor keyword routing breaks on encodable content.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_main())


if __name__ == "__main__":
    main()
