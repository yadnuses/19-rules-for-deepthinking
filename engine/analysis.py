"""辩论对比分析模块。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .llm import call_with_retry

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"


@dataclass
class ComparisonReport:
    session_a: str
    session_b: str
    topic: str
    winner_change: str
    viewpoint_evolution: str
    camp_analysis: str
    turning_points: str
    summary: str


def load_session_speeches(session_id: str) -> list[dict]:
    """加载一场辩论的所有发言。"""
    md_path = RESULTS_DIR / session_id / "debate.md"
    if not md_path.exists():
        return []

    content = md_path.read_text(encoding='utf-8')
    speeches = []
    pattern = r'\*\*([^*]+)\*\*(?:\s*\*\*\[改票\]\*\*)?\s*→\s*认为「([^」]+)」的回答最好：\n(.*?)(?=\n\*\*[^*]+\*\*\s*→|\n### |\n## |\Z)'
    for name, choice, text in re.findall(pattern, content, re.DOTALL):
        text = text.strip()
        if len(text) > 30:
            speeches.append({
                "name": name,
                "choice": choice,
                "content": text[:500],
            })
    return speeches


def compare_debates(session_a: str, session_b: str, topic: str) -> ComparisonReport:
    """对比两轮辩论的差异。"""
    speeches_a = load_session_speeches(session_a)
    speeches_b = load_session_speeches(session_b)

    if not speeches_a or not speeches_b:
        return ComparisonReport(
            session_a=session_a, session_b=session_b, topic=topic,
            winner_change="无法加载辩论数据",
            viewpoint_evolution="", camp_analysis="", turning_points="", summary="",
        )

    # 加载checkpoint获取胜者信息
    cp_a = _load_checkpoint(session_a)
    cp_b = _load_checkpoint(session_b)
    winner_a = cp_a.get("winner_name", "未知")
    winner_b = cp_b.get("winner_name", "未知")

    # 构建对比prompt
    sample_a = "\n".join([f"【{s['name']}】→选择{s['choice']}：{s['content'][:200]}" for s in speeches_a[:30]])
    sample_b = "\n".join([f"【{s['name']}】→选择{s['choice']}：{s['content'][:200]}" for s in speeches_b[:30]])

    prompt = f"""请对比以下两轮关于「{topic}」的辩论。

第一轮胜者：{winner_a}
第二轮胜者：{winner_b}

第一轮代表性发言（前30条）：
{sample_a[:3000]}

第二轮代表性发言（前30条）：
{sample_b[:3000]}

请从以下维度进行分析：

1. **胜者变化**：为什么胜者从{winner_a}变成了{winner_b}？（或为什么没变？）
2. **观点演变**：两轮辩论中，核心论点有什么变化？
3. **阵营分析**：哪些人物的观点发生了显著转变？
4. **关键转折点**：哪次发言可能改变了辩论走向？

请用中文回答，每点200-300字。"""

    resp = call_with_retry(
        [{"role": "user", "content": prompt}],
        system="你是辩论分析专家，擅长发现讨论中的深层变化和转折。",
        max_tokens=2000, temperature=0.5, timeout=60,
    )

    analysis = resp.output.strip() if resp.ok else "分析生成失败"

    # 解析各部分
    sections = re.split(r'\*\*\d+[.、]', analysis)
    winner_change = sections[1].strip() if len(sections) > 1 else analysis
    viewpoint_evolution = sections[2].strip() if len(sections) > 2 else ""
    camp_analysis = sections[3].strip() if len(sections) > 3 else ""
    turning_points = sections[4].strip() if len(sections) > 4 else ""

    return ComparisonReport(
        session_a=session_a,
        session_b=session_b,
        topic=topic,
        winner_change=winner_change,
        viewpoint_evolution=viewpoint_evolution,
        camp_analysis=camp_analysis,
        turning_points=turning_points,
        summary=analysis,
    )


def export_comparison_markdown(report: ComparisonReport, out_path: Path | None = None) -> Path:
    """导出对比分析为Markdown。"""
    if out_path is None:
        out_path = RESULTS_DIR / f"comparison_{report.session_a}_vs_{report.session_b}.md"

    lines = [
        f"# 辩论对比分析",
        f"",
        f"- 议题：{report.topic}",
        f"- 第一轮：{report.session_a}",
        f"- 第二轮：{report.session_b}",
        f"",
        f"## 胜者变化",
        f"",
        report.winner_change,
        f"",
    ]

    if report.viewpoint_evolution:
        lines.extend(["## 观点演变", "", report.viewpoint_evolution, ""])
    if report.camp_analysis:
        lines.extend(["## 阵营分析", "", report.camp_analysis, ""])
    if report.turning_points:
        lines.extend(["## 关键转折点", "", report.turning_points, ""])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding='utf-8')
    return out_path


def _load_checkpoint(session_id: str) -> dict:
    cp_path = RESULTS_DIR / session_id / "checkpoint.json"
    if cp_path.exists():
        try:
            return json.loads(cp_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}
