"""数据库读取模块 — 支持DB + 自定义JSON。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "roundtable.db"
CUSTOM_PATH = Path(__file__).resolve().parents[1] / "data" / "custom_agents.json"


@dataclass
class Agent:
    id: str
    name_zh: str
    name_en: str
    identity: str
    debate_roles: list[str]
    domains: list[str]
    style: str
    core_positions: list[str]
    category: str = ""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _json_field(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _slugify(name: str) -> str:
    h = hashlib.md5(name.encode()).hexdigest()[:8]
    clean = re.sub(r'[^\w]', '', name)
    return f"{clean}_{h}"


def _load_custom_agents(custom_path: Path | None = None) -> list[Agent]:
    """Load custom agents from JSON file."""
    path = custom_path or CUSTOM_PATH
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return []

    agents = []
    for item in data:
        agent_id = item.get("id") or _slugify(item["name_zh"])
        agents.append(Agent(
            id=agent_id,
            name_zh=item["name_zh"],
            name_en=item.get("name_en", ""),
            identity=item.get("identity", ""),
            debate_roles=item.get("debate_roles", []),
            domains=item.get("domains", []),
            style=item.get("style", ""),
            core_positions=item.get("core_positions", []),
            category=item.get("category", ""),
        ))
    return agents


def load_agents(
    con: sqlite3.Connection,
    custom_path: Path | None = None,
) -> list[Agent]:
    """Load all active agents from database + custom JSON."""
    rows = con.execute(
        """SELECT id, name_zh, name_en, identity, debate_roles, domains,
                  style, core_positions, category
           FROM agents WHERE is_active = 1 ORDER BY id"""
    ).fetchall()

    db_agents = [
        Agent(
            id=r["id"], name_zh=r["name_zh"], name_en=r["name_en"] or "",
            identity=r["identity"] or "",
            debate_roles=_json_field(r["debate_roles"], []),
            domains=_json_field(r["domains"], []),
            style=r["style"] or "",
            core_positions=_json_field(r["core_positions"], []),
            category=r["category"] or "",
        )
        for r in rows
    ]

    # 合并自定义角色，按name_zh去重
    existing_names = {a.name_zh for a in db_agents}
    custom_agents = _load_custom_agents(custom_path)
    for agent in custom_agents:
        if agent.name_zh not in existing_names:
            db_agents.append(agent)
            existing_names.add(agent.name_zh)

    return db_agents


def get_chunks(con: sqlite3.Connection, agent_id: str, limit: int = 4) -> list[dict]:
    """Get top-quality chunks for an agent."""
    rows = con.execute(
        """SELECT id, layer, source, text FROM agent_chunks
           WHERE agent_id = ? ORDER BY quality_score DESC LIMIT ?""",
        (agent_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def build_context(con: sqlite3.Connection, agent: Agent) -> str:
    """Build agent context string from database chunks."""
    chunks = get_chunks(con, agent.id, limit=4)
    parts = [f"[{c.get('layer', '')}] {c.get('text', '')[:300]}" for c in chunks]
    return "\n".join(parts) if parts else ""
