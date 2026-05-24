"""胜者综合 — 让冠军阅读200人观点，产出思想结晶。"""

from __future__ import annotations

import random
import sqlite3

from .database import Agent
from .llm import call_with_retry


def run_synthesis(
    winner: Agent,
    topic: str,
    all_utterances: list[dict[str, str]],
    con: sqlite3.Connection,
) -> str:
    """让胜者阅读200人观点，产出思想结晶。"""
    print(f"\n=== 思想综合：{winner.name_zh} 阅读200人观点 ===")

    sampled = random.sample(all_utterances, min(80, len(all_utterances)))
    perspectives = ""
    for utt in sampled:
        perspectives += f"- {utt['agent_name']}：{utt['content'][:150]}\n"

    prompt = f"""你是{winner.name_zh}。你是200位历史人物关于「{topic}」讨论的最终胜出者。

现在，你有机会阅读其他199位参与者的核心观点。以下是其中80位的代表性回答：

{perspectives}

你的任务不是简单地复述或总结，而是：
1. 找出这200人回答中真正有价值的洞见——那些触动你、挑战你、补充你的观点
2. 指出不同立场之间的张力与矛盾
3. 在此基础上，给出你对这个问题的更深理解——一个超越你最初回答的综合

这不是一篇综述文章，而是一次思想的升华。请展示你在阅读了200个灵魂的回答后，你的思考发生了什么变化。

1000-1500字。"""

    resp = call_with_retry(
        [{"role": "user", "content": prompt}],
        system=f"你是{winner.name_zh}，刚刚赢得了一场思想讨论。现在你需要展示真正的思想深度。",
        max_tokens=2048, temperature=0.8, timeout=120,
    )
    if resp.ok:
        return resp.output.strip()
    return "（综合生成失败）"
