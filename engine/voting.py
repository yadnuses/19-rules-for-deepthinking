"""投票系统 — 含反偏机制（随机模板、反从众、候选人顺序随机）。"""

from __future__ import annotations

import random
import re
import sqlite3

from .database import Agent
from .llm import call_with_retry

# ── 反偏投票模板 ──

_VOTE_TEMPLATES = [
    "请从你自己的思想立场出发，选出你最认同的那个人。不是「谁说得最漂亮」，而是「谁的判断与你的世界观最接近」。",
    "请选出最让你意外、但又说服了你的候选人。不是选你本来就同意的，而是选那个改变了你想法的人。",
    "想象你必须和其中一人一起面对这个抉择。你会选择谁作为你的同行者？不是谁最聪明，而是谁你最信任。",
    "先排除盲区最大的那位候选人，然后在剩下两人中选出你更认同的。",
    "假设五百年后回头看这场讨论，谁的判断最可能被历史证明是正确的？",
]


def global_vote(
    voter: Agent,
    candidates: dict[str, str],
    topic: str,
    con: sqlite3.Connection,
) -> tuple[str, str, str]:
    """One agent votes among top candidates. Returns (voter_name, choice, reason)."""
    # 随机排列候选人顺序
    items = list(candidates.items())
    random.shuffle(items)
    candidates_text = ""
    for i, (name, stance) in enumerate(items, 1):
        candidates_text += f"\n候选人{i}：{name}\n{stance[:500]}\n"
    name_list = [n for n, _ in items]

    # 随机投票模板 + 反从众提示
    template = random.choice(_VOTE_TEMPLATES)
    anti_herd = ""
    if random.random() < 0.5:
        anti_herd = "\n注意：如果你觉得大多数人都会选同一个候选人，请认真考虑其他候选人是否有被忽视的洞见。"

    prompt = f"""你是{voter.name_zh}。200位历史人物讨论了「{topic}」，经过层层讨论，剩下以下3位候选人：

{candidates_text}

{template}{anti_herd}

用1-2句话说明你的理由。

格式：
选择：XXX
理由：XXX"""

    resp = call_with_retry(
        [{"role": "user", "content": prompt}],
        system=f"你是{voter.name_zh}，保持角色一致性。",
        max_tokens=200, temperature=0.7, timeout=30,
    )
    if resp.ok:
        content = resp.output.strip()
        choice = name_list[0]
        choice_match = re.search(r'选择[：:]\s*[「]?([^」\n]+)[」]?\s*', content)
        if choice_match:
            extracted = choice_match.group(1).strip()
            for name in candidates:
                if name in extracted or extracted in name:
                    choice = name
                    break
        reason = ""
        reason_match = re.search(r'理由[：:]\s*(.+)', content)
        if reason_match:
            reason = reason_match.group(1).strip()
        return voter.name_zh, choice, reason
    return voter.name_zh, name_list[0], ""
