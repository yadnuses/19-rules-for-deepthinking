"""赛制引擎 — 支持淘汰赛、圆桌会议、混合模式。"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .database import Agent, connect, load_agents
from .debate import GroupDiscussion, RoundResult, Utterance, run_group, assess_quality_batch
from .export import export_markdown, now_iso, save_checkpoint
from .grouping import assign_groups
from .llm import call_with_retry
from .synthesis import run_synthesis
from .voting import global_vote

MAX_WORKERS = 5


# ── 数据类 ──

@dataclass
class TournamentConfig:
    mode: str = "elimination"  # "elimination" | "roundtable" | "hybrid" | "meta" | "top3"
    group_size: int = 10
    advancers_per_group: int = 2
    rounds_per_stage: int = 4
    quality_gate: bool = True
    tie_breaker: str = "faceoff"  # "faceoff" | "random"
    roundtable_rounds: int = 5  # 圆桌会议模式的轮数
    prev_session: str | None = None  # 元评论/深度对决的前轮session


@dataclass
class TournamentResult:
    session_id: str
    topic: str
    config: TournamentConfig
    groups: list[GroupDiscussion]
    winner_name: str
    winner_stance: str
    synthesis: str
    review_responses: list[dict]
    started_at: str
    completed_at: str
    advancers: list[str]


# ── 事件系统 ──

class EventBus:
    """简单的事件总线，支持CLI和Web两种输出模式。"""

    def __init__(self):
        self._handlers: list = []

    def on(self, handler):
        self._handlers.append(handler)

    def emit(self, event_type: str, data: dict):
        for handler in self._handlers:
            try:
                handler(event_type, data)
            except Exception:
                pass


def cli_event_handler(event_type: str, data: dict):
    """CLI模式的事件处理：打印到终端。"""
    if event_type == "stage_start":
        print(f"\n=== {data['name']}：{data.get('desc', '')} ===")
    elif event_type == "group_start":
        names = ', '.join(a["name"] for a in data.get("agents", []))
        print(f"  [开始] 第 {data['group_id']} 组: {names}")
    elif event_type == "group_done":
        winner = data.get("winner", ("?", 0))
        print(f"  [完成] 第 {data['group_id']} 组 胜出: {winner[0]}({winner[1]}票)")
    elif event_type == "round_end":
        top = data.get("top", [])
        top_str = ", ".join(f"{n}({v}票)" for n, v in top)
        print(f"  第{data['round']}轮[{data['round_name']}] 完成 | 票数前三: {top_str} | 改票: {data.get('changes', 0)}人")
    elif event_type == "vote_progress":
        print(f"  已投票 {data['done']}/{data['total']}")
    elif event_type == "result":
        print(f"\n  全民投票结果：")
        for name, votes in data.get("votes", []):
            print(f"    {name}：{votes}票")
    elif event_type == "winner":
        print(f"\n=== 完成 ===")
        print(f"最终胜者：{data['name']}")
        if data.get("output"):
            print(f"Markdown: {data['output']}")


# ── 核心函数 ──

def run_tournament(
    topic: str,
    config: TournamentConfig | None = None,
    db_path: Path | None = None,
    event_bus: EventBus | None = None,
    briefing: str = "",
    agent_ids: list[str] | None = None,
) -> TournamentResult:
    """运行一场完整的辩论赛事。"""
    if config is None:
        config = TournamentConfig()

    bus = event_bus or EventBus()

    session_id = f"roundtable_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = Path(__file__).resolve().parents[1] / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    con = connect(db_path)
    all_agents = load_agents(con)

    # 如果指定了agent_ids，只保留这些agent
    if agent_ids:
        agent_id_set = set(agent_ids)
        all_agents = [a for a in all_agents if a.id in agent_id_set]
        print(f"已筛选 {len(all_agents)} 个指定agent")

    # 根据模式选择参与者
    if config.mode == "meta" and config.prev_session:
        # 元评论模式：加载前轮辩论作为背景
        briefing = _load_prev_briefing(config.prev_session, topic)
        current_agents = list(all_agents)
        random.shuffle(current_agents)
    elif config.mode == "top3" and config.prev_session:
        # 前3深度对决模式
        return _run_top3_debate(
            con, all_agents, topic, config, session_id, out_dir, bus, briefing,
        )
    else:
        current_agents = list(all_agents)
        random.shuffle(current_agents)

    # 如果没有briefing，自动生成
    if not briefing:
        briefing = _generate_briefing(topic)

    started_at = now_iso()

    bus.emit("stage_start", {"name": f"圆桌派：{topic}", "desc": f"{len(current_agents)}人参与"})

    if config.mode == "roundtable":
        result = _run_roundtable(
            con, current_agents, topic, briefing, config, session_id, out_dir, bus,
        )
    elif config.mode == "hybrid":
        result = _run_hybrid(
            con, current_agents, topic, briefing, config, session_id, out_dir, bus,
        )
    else:
        # 默认淘汰赛
        result = _run_elimination(
            con, current_agents, topic, briefing, config, session_id, out_dir, bus,
        )

    result.started_at = started_at
    result.completed_at = now_iso()

    # 导出
    all_groups = result.groups
    md_path = export_markdown(
        topic=topic,
        session_id=session_id,
        started_at=result.started_at,
        completed_at=result.completed_at,
        winner_name=result.winner_name,
        winner_stance=result.winner_stance,
        synthesis=result.synthesis,
        groups=all_groups,
        review_responses=result.review_responses,
        out_dir=out_dir,
    )

    bus.emit("winner", {
        "name": result.winner_name,
        "output": str(md_path),
    })

    save_checkpoint(out_dir, session_id, {
        "session_id": session_id,
        "topic": topic,
        "winner_name": result.winner_name,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
    })

    return result


def _run_elimination(
    con, agents, topic, briefing, config, session_id, out_dir, bus,
) -> TournamentResult:
    """淘汰赛模式。"""
    current = list(agents)
    all_groups = []
    stage = 0

    while len(current) > config.group_size:
        stage += 1
        groups = assign_groups(current, config.group_size)
        valid_groups = [(i, g) for i, g in enumerate(groups) if len(g) >= 3]

        bus.emit("stage_start", {
            "name": f"第{stage}轮",
            "desc": f"{len(current)}人 → {len(valid_groups)}组",
        })

        stage_results = _run_group_batch(
            con, valid_groups, topic, briefing, bus,
        )
        all_groups.extend(stage_results)

        # 晋级
        advancer_ids = []
        for gr in stage_results:
            advancer_ids.extend(gr.advancers[:config.advancers_per_group])
        agent_map = {a.id: a for a in agents}
        current = [agent_map[aid] for aid in advancer_ids if aid in agent_map]

    # 决赛
    if len(current) > 3:
        bus.emit("stage_start", {
            "name": "决赛",
            "desc": f"{len(current)}人 → 前3",
        })
        final_group = run_group(con, current, 0, topic, briefing)
        all_groups.append(final_group)

        if final_group.final_votes:
            sorted_c = sorted(final_group.final_votes.items(), key=lambda x: -x[1])
            top3_names = [n for n, _ in sorted_c[:3]]
            top3_agents = [a for a in current if a.name_zh in top3_names]
            if len(top3_agents) < 3:
                existing_ids = {a.id for a in top3_agents}
                for a in current:
                    if a.id not in existing_ids and len(top3_agents) < 3:
                        top3_agents.append(a)
        else:
            top3_agents = current[:3]
    else:
        top3_agents = current[:3]

    # 全民投票
    return _run_global_vote(
        con, agents, top3_agents, topic, briefing, all_groups, bus,
    )


def _run_roundtable(
    con, agents, topic, briefing, config, session_id, out_dir, bus,
) -> TournamentResult:
    """圆桌会议模式 — 不淘汰，每轮重新分组。"""
    all_groups = []
    cumulative_votes: dict[str, int] = {}
    agent_map = {a.id: a for a in agents}

    for round_num in range(1, config.roundtable_rounds + 1):
        bus.emit("stage_start", {
            "name": f"第{round_num}轮圆桌",
            "desc": f"{len(agents)}人，重新分组",
        })

        current = list(agents)
        random.shuffle(current)
        groups = assign_groups(current, config.group_size)
        valid_groups = [(i, g) for i, g in enumerate(groups) if len(g) >= 3]

        stage_results = _run_group_batch(
            con, valid_groups, topic, briefing, bus,
        )
        all_groups.extend(stage_results)

        # 累计投票
        for gr in stage_results:
            for name, votes in gr.final_votes.items():
                cumulative_votes[name] = cumulative_votes.get(name, 0) + votes

    # 取累计票数前3
    sorted_all = sorted(cumulative_votes.items(), key=lambda x: -x[1])
    top3_names = [n for n, _ in sorted_all[:3]]
    top3_agents = [a for a in agents if a.name_zh in top3_names]
    if len(top3_agents) < 3:
        for a in agents:
            if a.name_zh not in top3_names and len(top3_agents) < 3:
                top3_agents.append(a)

    return _run_global_vote(
        con, agents, top3_agents, topic, briefing, all_groups, bus,
    )


def _run_hybrid(
    con, agents, topic, briefing, config, session_id, out_dir, bus,
) -> TournamentResult:
    """混合模式 — 淘汰赛筛选 + 圆桌会议深入。"""
    # 阶段1：淘汰赛（筛选到40人）
    elimination_target = 40
    current = list(agents)
    all_groups = []
    stage = 0

    while len(current) > elimination_target:
        stage += 1
        groups = assign_groups(current, config.group_size)
        valid_groups = [(i, g) for i, g in enumerate(groups) if len(g) >= 3]

        bus.emit("stage_start", {
            "name": f"海选第{stage}轮",
            "desc": f"{len(current)}人 → {len(valid_groups)}组",
        })

        stage_results = _run_group_batch(
            con, valid_groups, topic, briefing, bus,
        )
        all_groups.extend(stage_results)

        advancer_ids = []
        for gr in stage_results:
            advancer_ids.extend(gr.advancers[:config.advancers_per_group])
        agent_map = {a.id: a for a in agents}
        current = [agent_map[aid] for aid in advancer_ids if aid in agent_map]

    # 阶段2：圆桌会议
    bus.emit("stage_start", {
        "name": "圆桌会议阶段",
        "desc": f"{len(current)}人，{3}轮深入讨论",
    })

    cumulative_votes: dict[str, int] = {}
    for round_num in range(1, 4):
        random.shuffle(current)
        groups = assign_groups(current, config.group_size)
        valid_groups = [(i, g) for i, g in enumerate(groups) if len(g) >= 3]

        stage_results = _run_group_batch(
            con, valid_groups, topic, briefing, bus,
        )
        all_groups.extend(stage_results)

        for gr in stage_results:
            for name, votes in gr.final_votes.items():
                cumulative_votes[name] = cumulative_votes.get(name, 0) + votes

    sorted_all = sorted(cumulative_votes.items(), key=lambda x: -x[1])
    top3_names = [n for n, _ in sorted_all[:3]]
    top3_agents = [a for a in agents if a.name_zh in top3_names]
    if len(top3_agents) < 3:
        for a in agents:
            if a.name_zh not in top3_names and len(top3_agents) < 3:
                top3_agents.append(a)

    return _run_global_vote(
        con, agents, top3_agents, topic, briefing, all_groups, bus,
    )


def _run_group_batch(
    con, valid_groups, topic, briefing, bus,
) -> list[GroupDiscussion]:
    """并行运行一组辩论。"""
    results = []
    GROUP_BATCH = 5
    batches = [valid_groups[i:i + GROUP_BATCH] for i in range(0, len(valid_groups), GROUP_BATCH)]

    for batch_idx, batch in enumerate(batches):
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            def _run_group_task(g_idx_group):
                g_idx, group = g_idx_group
                bus.emit("group_start", {
                    "group_id": g_idx + 1,
                    "agents": [{"name": a.name_zh} for a in group],
                })
                gr = run_group(con, group, g_idx, topic, briefing)
                winner = max(gr.final_votes.items(), key=lambda x: x[1]) if gr.final_votes else ("?", 0)
                bus.emit("group_done", {"group_id": g_idx + 1, "winner": winner})
                return gr

            futures = {executor.submit(_run_group_task, gi): gi for gi in batch}
            for f in as_completed(futures):
                try:
                    results.append(f.result())
                except Exception as e:
                    g_idx = futures[f]
                    print(f"  [错误] 第 {g_idx + 1} 组失败: {e}")

        if batch_idx < len(batches) - 1:
            time.sleep(1)

    results.sort(key=lambda x: x.group_id)
    return results


def _run_global_vote(
    con, all_agents, top3_agents, topic, briefing, all_groups, bus,
) -> TournamentResult:
    """全民投票。"""
    # 获取候选人的终论发言
    finalist_statements = {}
    for agent in top3_agents:
        for gr in all_groups:
            for rr in gr.rounds:
                for utt in rr.utterances:
                    if utt.agent_id == agent.id:
                        finalist_statements[agent.name_zh] = utt.content
                        break
                if agent.name_zh in finalist_statements:
                    break
            if agent.name_zh in finalist_statements:
                break
        if agent.name_zh not in finalist_statements:
            finalist_statements[agent.name_zh] = f"（{agent.name_zh}的陈词）"

    top3_names = [a.name_zh for a in top3_agents]

    bus.emit("stage_start", {
        "name": "全民投票",
        "desc": f"{len(all_agents)}人从{len(top3_names)}位候选人中选出最终胜者",
    })

    global_votes: dict[str, int] = {n: 0 for n in finalist_statements}
    vote_details = []

    done_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(global_vote, a, finalist_statements, topic, con): a
            for a in all_agents
        }
        for f in as_completed(futures):
            try:
                voter_name, choice, reason = f.result()
                if choice in global_votes:
                    global_votes[choice] += 1
                vote_details.append((voter_name, choice, reason))
            except Exception:
                pass
            done_count += 1
            if done_count % 25 == 0 or done_count == len(all_agents):
                bus.emit("vote_progress", {"done": done_count, "total": len(all_agents)})

    global_votes_sorted = sorted(global_votes.items(), key=lambda x: -x[1])
    bus.emit("result", {"votes": global_votes_sorted})

    if not global_votes_sorted:
        winner_name = top3_agents[0].name_zh
    else:
        winner_name = global_votes_sorted[0][0]
    winner_agent = None
    for a in all_agents:
        if a.name_zh == winner_name:
            winner_agent = a
            break
    if not winner_agent:
        winner_agent = top3_agents[0]
        winner_name = top3_agents[0].name_zh

    winner_stance = finalist_statements.get(winner_name, "")

    review_responses = [
        {"agent_name": voter, "content": f"投给「{choice}」——{reason}" if reason else f"投给「{choice}」"}
        for voter, choice, reason in vote_details
    ]

    # 思想综合
    all_utterances = []
    for gr in all_groups:
        for rr in gr.rounds:
            for utt in rr.utterances:
                all_utterances.append({
                    "agent_name": utt.agent_name,
                    "content": utt.content,
                    "round": rr.round_num,
                })

    synthesis = ""
    if winner_agent:
        synthesis = run_synthesis(winner_agent, topic, all_utterances, con)

    return TournamentResult(
        session_id="",
        topic=topic,
        config=TournamentConfig(),
        groups=all_groups,
        winner_name=winner_name,
        winner_stance=winner_stance,
        synthesis=synthesis,
        review_responses=review_responses,
        started_at="",
        completed_at="",
        advancers=[a.id for a in top3_agents],
    )


def _run_top3_debate(
    con, all_agents, topic, config, session_id, out_dir, bus, briefing,
) -> TournamentResult:
    """前3深度对决模式。"""
    if not briefing and config.prev_session:
        briefing = _load_prev_briefing(config.prev_session, topic)
    if not briefing:
        briefing = _generate_briefing(topic)

    # 找到前3名（从前轮结果或默认取前3）
    top3_agents = all_agents[:3]  # 默认取前3

    # 定义深度辩论轮次
    deep_rounds = [
        {"name": "直面对手", "desc": "直接回应另外两位对手的核心论点", "char_limit": 1200, "token_limit": 1800},
        {"name": "交锋深化", "desc": "针对上一轮对手的批评进行反击或修正", "char_limit": 1200, "token_limit": 1800},
        {"name": "终极立场", "desc": "总结全部交锋，给出最终判断", "char_limit": 1500, "token_limit": 2000},
    ]

    names = [a.name_zh for a in top3_agents]
    bus.emit("stage_start", {"name": "前三深度辩论", "desc": ', '.join(names)})

    all_rounds = []
    history = ""

    for rd_idx, rd_info in enumerate(deep_rounds):
        bus.emit("stage_start", {"name": f"第{rd_idx+1}轮：{rd_info['name']}", "desc": rd_info["desc"]})
        round_result = RoundResult(round_num=rd_idx + 1, utterances=[])

        for agent in top3_agents:
            system = (
                f"你是{agent.name_zh}（{agent.identity}）。\n"
                f"你正在参与一场三人深度辩论。\n"
                "直接回应对手的观点，展示你思想的深度和独特性。"
            )
            prompt = (
                f"议题：{topic}\n\n"
                f"背景材料：\n{briefing[:3000]}\n\n"
                f"此前交锋：\n{history[-3000:] if history else '（第一轮）'}\n\n"
                f"本轮任务：{rd_info['desc']}\n\n"
                f"请发表你的观点（{rd_info['char_limit']}字以内）。\n"
                f"在最后单独一行写「选择：XXX」表示你认为谁的发言最好。"
            )
            resp = call_with_retry(
                [{"role": "user", "content": prompt}],
                system=system,
                max_tokens=rd_info["token_limit"],
                temperature=0.85,
                timeout=90,
            )
            content = resp.output.strip() if resp.ok else f"（{agent.name_zh}沉默了）"

            # 解析投票
            choice = agent.name_zh
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith("选择：") or line.startswith("选择:"):
                    choice = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    break

            utt = Utterance(
                agent_id=agent.id, agent_name=agent.name_zh,
                round_num=rd_idx + 1, content=content, choice=choice,
            )
            round_result.utterances.append(utt)
            history += f"\n【{agent.name_zh}】{content}\n"

        # 组内投票
        votes = {n: 0 for n in names}
        for utt in round_result.utterances:
            if utt.choice in votes:
                votes[utt.choice] += 1
        round_result.vote_counts = votes
        all_rounds.append(round_result)

        sorted_v = sorted(votes.items(), key=lambda x: -x[1])
        bus.emit("result", {"votes": sorted_v})

    # 全民投票
    finalist_statements = {}
    for agent in top3_agents:
        for utt in all_rounds[-1].utterances:
            if utt.agent_id == agent.id:
                finalist_statements[agent.name_zh] = utt.content
                break

    global_votes: dict[str, int] = {n: 0 for n in finalist_statements}
    vote_details = []

    done_count = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(global_vote, a, finalist_statements, topic, con): a
            for a in all_agents
        }
        for f in as_completed(futures):
            try:
                voter_name, choice, reason = f.result()
                if choice in global_votes:
                    global_votes[choice] += 1
                vote_details.append((voter_name, choice, reason))
            except Exception:
                pass
            done_count += 1
            if done_count % 25 == 0 or done_count == len(all_agents):
                bus.emit("vote_progress", {"done": done_count, "total": len(all_agents)})

    global_votes_sorted = sorted(global_votes.items(), key=lambda x: -x[1])
    bus.emit("result", {"votes": global_votes_sorted})

    if not global_votes_sorted:
        winner_name = top3_agents[0].name_zh
    else:
        winner_name = global_votes_sorted[0][0]
    winner_agent = next((a for a in top3_agents if a.name_zh == winner_name), top3_agents[0])
    winner_stance = finalist_statements.get(winner_name, "")

    all_utterances = []
    for rd in all_rounds:
        for utt in rd.utterances:
            all_utterances.append({
                "agent_name": utt.agent_name,
                "content": utt.content,
                "round": rd.round_num,
            })

    synthesis = run_synthesis(winner_agent, topic, all_utterances, con)

    review_responses = [
        {"agent_name": voter, "content": f"投给「{choice}」——{reason}" if reason else f"投给「{choice}」"}
        for voter, choice, reason in vote_details
    ]

    final_group = GroupDiscussion(
        group_id=0, agents=top3_agents,
        rounds=all_rounds, final_votes={n: v for n, v in global_votes_sorted},
        advancers=[winner_agent.id],
    )

    return TournamentResult(
        session_id=session_id, topic=topic, config=config,
        groups=[final_group], winner_name=winner_name,
        winner_stance=winner_stance, synthesis=synthesis,
        review_responses=review_responses,
        started_at="", completed_at="", advancers=[winner_agent.id],
    )


def _load_prev_briefing(session_id: str, topic: str) -> str:
    """加载前轮辩论的摘要作为briefing。"""
    results_dir = Path(__file__).resolve().parents[1] / "results" / session_id
    debate_path = results_dir / "debate.md"

    if not debate_path.exists():
        return _generate_briefing(topic)

    # 提取关键发言
    import re
    content = debate_path.read_text(encoding='utf-8')

    speeches = []
    pattern = r'\*\*([^*]+)\*\* → 认为[^：]*：\n(.*?)(?=\n\*\*[^*]+\*\* → 认为|\n### |\n## |\Z)'
    for name, text in re.findall(pattern, content, re.DOTALL):
        text = text.strip()
        if len(text) > 50:
            speeches.append(f"【{name}】{text[:400]}")

    briefing = f"以下是上一轮关于「{topic}」的辩论摘要（共{len(speeches)}条发言）：\n\n"
    briefing += "\n\n".join(speeches[:80])
    return briefing


def _generate_briefing(topic: str) -> str:
    """用LLM自动生成议题背景材料。"""
    prompt = f"""请为以下辩论议题撰写一份简洁的背景材料（800-1200字）。

议题：{topic}

要求：
1. 客观呈现问题的核心张力（不要偏向任何一方）
2. 列出关键事实和数据（如果有的话）
3. 列出3-5个核心争论点
4. 提供历史坐标（类似问题的历史先例）
5. 给出5个引导辩论参与者思考的问题

格式：Markdown，用标题分节。"""

    resp = call_with_retry(
        [{"role": "user", "content": prompt}],
        system="你是一个学术研究助手，擅长撰写议题背景材料。客观、简洁、有深度。",
        max_tokens=2048, temperature=0.5, timeout=60,
    )
    return resp.output.strip() if resp.ok else ""
