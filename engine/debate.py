"""辩论引擎 — 4轮结构化辩论（立论→交锋→深化→终论）。"""

from __future__ import annotations

import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from .database import Agent, build_context
from .llm import call_with_retry
from .voting import global_vote

GROUP_WORKERS = 3
MAX_WORKERS = 4

# ── 质量评估 ──

def assess_quality_batch(utterances: list[Utterance], topic: str) -> dict[str, float]:
    """批量评估发言质量，返回 {agent_id: score}。评分1-5。"""
    if not utterances:
        return {}

    # 构建评估prompt
    entries = []
    for utt in utterances:
        entries.append(f"【{utt.agent_name}】{utt.content[:300]}")

    prompt = f"""请评估以下关于「{topic}」的辩论发言质量。

评估标准：
- 是否引用具体史实或个人经历（而非泛泛而谈）
- 是否有独特视角（而非通用的哲学套话）
- 是否回应了他人论点（而非自说自话）
- 思想密度（每句话是否都在推进论证）

请为每条发言打分（1-5分），输出JSON格式：
{{"名字": 分数, ...}}

发言：
{chr(10).join(entries[:10])}"""

    resp = call_with_retry(
        [{"role": "user", "content": prompt}],
        system="你是辩论质量评估专家。只输出JSON，不要解释。",
        max_tokens=300, temperature=0.3, timeout=30,
    )

    scores = {}
    if resp.ok:
        import json
        try:
            # 提取JSON
            text = resp.output.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            parsed = json.loads(text)
            for utt in utterances:
                if utt.agent_name in parsed:
                    scores[utt.agent_id] = float(parsed[utt.agent_name])
        except (json.JSONDecodeError, ValueError):
            pass

    # 默认分数3.0
    for utt in utterances:
        if utt.agent_id not in scores:
            scores[utt.agent_id] = 3.0

    return scores

# ── 轮次设计 ──

ROUNDS = [
    (1, "立论",
     "从你的思想立场出发，回答核心问题。用你的历史经验、你对人性的理解来回答。不要泛泛而谈。",
     600, 1280),
    (2, "交锋",
     "你看到了同组其他人的回答。请选择一个最触动你或最值得质疑的观点，直接回应。\n"
     "要求：指出对方具体的逻辑漏洞或事实偏差，不要说'X的观点让我想起了...'这种套话。\n"
     "如果你引用历史事件，请具体到时间、地点、人物。",
     800, 1536),
    (3, "深化",
     "讨论进入深水区。请重新审视你最初的立场。\n"
     "要求：不要重新复述你的立场，直接说你改变了什么、为什么改变。如果没改变，说清楚为什么其他人的论点没能说服你。",
     1000, 1800),
    (4, "终论",
     "最后一轮。请用最精炼的语言，给出你对这个问题的最终判断。\n"
     "要求：不要总结前面所有人说了什么，直接给出你的最终判断和最核心的一个理由。",
     800, 1536),
]


@dataclass
class Utterance:
    agent_id: str
    agent_name: str
    round_num: int
    choice: str
    content: str
    changed: bool = False


@dataclass
class RoundResult:
    round_num: int
    utterances: list[Utterance]
    vote_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class GroupDiscussion:
    group_id: int
    agents: list[Agent]
    rounds: list[RoundResult] = field(default_factory=list)
    final_votes: dict[str, int] = field(default_factory=dict)
    advancers: list[str] = field(default_factory=list)
    quality_scores: dict[str, float] = field(default_factory=dict)  # agent_id -> score


def _build_prompt(
    agent: Agent,
    round_num: int,
    round_desc: str,
    topic: str,
    group: list[Agent],
    prev_utterances: list[Utterance],
    context: str,
    brief: str,
    discussion_summary: str = "",
) -> list[dict[str, str]]:
    agent_names = [a.name_zh for a in group]

    history = ""
    if prev_utterances:
        lines = []
        # 保留最近50条完整发言
        for utt in prev_utterances[-50:]:
            change_mark = " [改票]" if utt.changed else ""
            lines.append(f"第{utt.round_num}轮 {utt.agent_name}{change_mark} → 认为「{utt.choice}」的回答最好：{utt.content[:400]}")
        history = "\n".join(lines)

    brief_section = f"\n\n议题背景：\n{brief[:2000]}" if brief else ""

    # 对更早的发言使用摘要
    summary_section = ""
    if discussion_summary:
        summary_section = f"\n\n更早讨论的摘要：\n{discussion_summary}\n"

    history_section = ""
    if history:
        history_section = f"\n\n之前的讨论：\n{summary_section}{history}"

    if round_num == 1:
        user_prompt = f"""议题：{topic}

{brief_section}

你的个人资料：
{context if context else '（无额外资料）'}

同组其他人：{', '.join(agent_names)}

请以 {agent.name_zh} 的身份回答：{topic}
用你的历史经验、你对人性的理解来回答。不要泛泛而谈。

在发言末尾，另起一行写「选择：{agent.name_zh}」表示你认为谁的回答最好。"""
    else:
        user_prompt = f"""议题：{topic}

{history_section}

你的个人资料：
{context if context else '（无额外资料）'}

本轮任务：{round_desc}

请以 {agent.name_zh} 的身份发言。你可以坚持之前的选择，也可以改变。
在发言末尾，另起一行写「选择：XXX」表示你认为谁的回答最好（XXX必须是同组成员之一）。"""

    return [{"role": "user", "content": user_prompt}]


def _speak(
    agent: Agent, round_num: int, round_desc: str,
    topic: str, group: list[Agent], prev_utterances: list[Utterance],
    con: sqlite3.Connection, char_limit: int, token_limit: int, brief: str,
) -> Utterance:
    context = build_context(con, agent)
    messages = _build_prompt(
        agent, round_num, round_desc, topic,
        group, prev_utterances, context, brief,
    )
    system_prompt = (
        f"你是{agent.name_zh}（{agent.identity}）。\n"
        f"你正在参与一场关于「{topic}」的深度对话。\n\n"
        "核心规则：\n"
        "- 用你自己的思想体系回答，不要用通用的哲学套话\n"
        "- 引用你自己的经历、著作、历史事件来支撑论点\n"
        "- 限制比喻使用：最多1个核心比喻，不要堆砌\n"
        "- 不要以'诸位'、'朋友们'开头，直接切入观点\n"
        "- 如果你不同意某人，指出具体的逻辑漏洞，不要泛泛而谈\n"
        "- 保持角色一致性，但要像一个真实的人在思考，而不是在表演"
    )
    resp = call_with_retry(
        messages,
        system=system_prompt,
        max_tokens=token_limit, temperature=0.85, timeout=90,
    )
    content = resp.output.strip() if resp.ok else f"[{agent.name_zh}发言失败]"

    # Clean prefix
    for prefix in [f"{agent.name_zh}：", f"{agent.name_zh}:", f"**{agent.name_zh}**"]:
        if content.startswith(prefix):
            content = content[len(prefix):].strip()

    # Parse choice
    choice = agent.name_zh
    choice_match = re.search(r'选择[：:]\s*[「]?([^」\n]+)[」]?\s*$', content)
    if not choice_match:
        choice_match = re.search(r'选择[：:]\s*(.+?)(?:\n|$)', content)
    if choice_match:
        extracted = choice_match.group(1).strip()
        valid_names = {a.name_zh for a in group}
        if extracted in valid_names:
            choice = extracted
        else:
            for name in valid_names:
                if name in extracted or extracted in name:
                    choice = name
                    break
    else:
        for a in group:
            if a.name_zh != agent.name_zh and f"认同{a.name_zh}" in content:
                choice = a.name_zh
                break

    changed = False
    if prev_utterances:
        for utt in reversed(prev_utterances):
            if utt.agent_id == agent.id:
                if utt.choice != choice:
                    changed = True
                break

    return Utterance(
        agent_id=agent.id, agent_name=agent.name_zh,
        round_num=round_num, choice=choice, content=content, changed=changed,
    )


def run_group(
    con: sqlite3.Connection,
    group: list[Agent],
    group_id: int,
    topic: str,
    brief: str = "",
) -> GroupDiscussion:
    """Run a 4-round group discussion."""
    result = GroupDiscussion(group_id=group_id, agents=group)
    all_utterances: list[Utterance] = []

    executor = ThreadPoolExecutor(max_workers=GROUP_WORKERS)
    try:
        for round_num, round_name, round_desc, char_limit, token_limit in ROUNDS:
            round_utts = []

            for batch_start in range(0, len(group), GROUP_WORKERS):
                batch = group[batch_start:batch_start + GROUP_WORKERS]
                futures = {
                    executor.submit(
                        _speak, agent, round_num, round_desc,
                        topic, group, all_utterances, con,
                        char_limit, token_limit, brief,
                    ): agent
                    for agent in batch
                }
                for f in as_completed(futures):
                    try:
                        round_utts.append(f.result())
                    except Exception as exc:
                        agent = futures[f]
                        round_utts.append(Utterance(
                            agent_id=agent.id, agent_name=agent.name_zh,
                            round_num=round_num, choice=agent.name_zh,
                            content=f"[{agent.name_zh}发言失败: {str(exc)[:60]}]",
                        ))

            agent_order = {a.id: i for i, a in enumerate(group)}
            round_utts.sort(key=lambda n: agent_order.get(n.agent_id, 999))

            vote_counts: dict[str, int] = {}
            for utt in round_utts:
                vote_counts[utt.choice] = vote_counts.get(utt.choice, 0) + 1

            rr = RoundResult(
                round_num=round_num,
                utterances=round_utts,
                vote_counts=dict(sorted(vote_counts.items(), key=lambda x: -x[1])),
            )
            result.rounds.append(rr)
            all_utterances.extend(round_utts)

            # 质量评估
            try:
                scores = assess_quality_batch(round_utts, topic)
                result.quality_scores.update(scores)
            except Exception:
                pass

            top = list(rr.vote_counts.items())[:3]
            top_str = ", ".join(f"{n}({v}票)" for n, v in top)
            changes = sum(1 for u in round_utts if u.changed)
            print(f"  第{round_num}轮[{round_name}] 完成 | 票数前三: {top_str} | 改票: {changes}人")

    finally:
        executor.shutdown(wait=False)

    if result.rounds:
        result.final_votes = result.rounds[-1].vote_counts

    if result.final_votes:
        winner = max(result.final_votes.items(), key=lambda x: x[1])
        for a in group:
            if a.name_zh == winner[0]:
                result.advancers = [a.id]
                break
        if not result.advancers:
            result.advancers = [group[0].id]

    return result
