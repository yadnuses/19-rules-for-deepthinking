#!/usr/bin/env python3
"""从历史人物档案markdown文件导入新agent到roundtable.db。

用法：
    python3 scripts/import_agents.py /Users/xiaoy/Downloads/历史人物档案/
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
DB_PATH = SKILL_DIR / "data" / "roundtable.db"

# 类别映射：文件名 → 数据库category
CATEGORY_MAP = {
    "01_思想与哲学": "一、思想与哲学",
    "02_科学与数学": "二、科学与数学",
    "03_政治与治理": "三、政治与治理",
    "05_文学_新增": "五、文学",
    "06_艺术_新增": "六、艺术",
    "07_工程与发明_新增": "七、工程与发明",
    "08_经济与社会科学_新增": "八、经济与社会科学",
    "10_当代关键人物_新增": "十、当代关键人物",
    "11_互联网与数字文化_新增": "十一、互联网与数字文化",
    "12_商业与企业家_新增": "十二、商业与企业家",
    "13_医学与健康_新增": "十三、医学与健康",
    "14_法律与正义_新增": "十四、法律与正义",
    "15_军事与战略_新增": "十五、军事与战略",
    "16_体育与竞技_新增": "十六、体育与竞技",
    "17_音乐与表演艺术_新增": "十七、音乐与表演艺术",
    "18_女性先锋与平权领袖_新增": "十八、女性先锋与平权领袖",
    "19_环境与生态_新增": "十九、环境与生态",
    "20_视觉艺术与建筑_新增": "二十、视觉艺术与建筑",
}

# 类别对应的默认domains
CATEGORY_DOMAINS = {
    "一、思想与哲学": ["伦理道德", "政治哲学", "宗教精神"],
    "二、科学与数学": ["科学技术", "数学"],
    "三、政治与治理": ["政治哲学", "社会治理"],
    "五、文学": ["文学艺术", "人文思想"],
    "六、艺术": ["文学艺术", "美学"],
    "七、工程与发明": ["科学技术", "工程"],
    "八、经济与社会科学": ["经济思想", "社会科学"],
    "十、当代关键人物": ["当代议题", "全球治理"],
    "十一、互联网与数字文化": ["科学技术", "数字文化"],
    "十二、商业与企业家": ["经济思想", "商业"],
    "十三、医学与健康": ["医学", "公共卫生"],
    "十四、法律与正义": ["法律", "人权"],
    "十五、军事与战略": ["军事", "战略"],
    "十六、体育与竞技": ["体育", "文化"],
    "十七、音乐与表演艺术": ["艺术", "音乐"],
    "十八、女性先锋与平权领袖": ["人权", "社会运动"],
    "十九、环境与生态": ["环境", "生态"],
    "二十、视觉艺术与建筑": ["艺术", "建筑"],
}


def slugify_zh(name: str) -> str:
    """生成一个稳定的ID。"""
    # 用md5哈希取前8位作为后缀，保证唯一性
    h = hashlib.md5(name.encode()).hexdigest()[:8]
    # 简单处理：去除空格和特殊字符
    clean = re.sub(r'[^\w]', '', name)
    return f"{clean}_{h}"


def parse_agent_profile(text: str, category: str) -> dict | None:
    """解析一个人物档案的markdown文本。"""
    lines = text.strip().split('\n')
    if not lines:
        return None

    # 提取名字和英文名
    header = lines[0]
    # 格式：## 1. 苏格拉底（Socrates，~470-399 BC）
    name_match = re.match(r'##\s+\d+\.\s+(.+?)（(.+?)）', header)
    if not name_match:
        # 尝试不带序号的格式
        name_match = re.match(r'##\s+(.+?)（(.+?)）', header)
    if not name_match:
        return None

    name_zh = name_match.group(1).strip()
    name_en_full = name_match.group(2).strip()

    # 从英文全名中提取纯英文名
    # 格式可能是：Socrates，~470-399 BC 或 Alan Turing，1912-1954
    name_en = name_en_full.split('，')[0].split(',')[0].strip()
    # 去掉可能的中文括号内容
    name_en = re.split(r'[（(]', name_en)[0].strip()

    # 提取时期
    period = ""
    period_match = re.search(r'[，,]\s*(~?\d+\s*[-–]\s*~?\d+\s*(?:BC|AD|BCE|CE)?|[~]?\d+\s*(?:BC|AD|BCE|CE))', name_en_full)
    if period_match:
        period = period_match.group(1).strip()

    # 提取身份标签
    identity = ""
    for line in lines[1:10]:
        if "一句话身份标签" in line:
            identity = line.split("：", 1)[-1].strip().strip("*").strip()
            break

    # 提取各段落内容
    content_sections = {}
    current_section = None
    current_lines = []

    for line in lines:
        if line.startswith("### "):
            if current_section:
                content_sections[current_section] = "\n".join(current_lines).strip()
            current_section = line[4:].strip()
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section:
        content_sections[current_section] = "\n".join(current_lines).strip()

    # 构建core_positions：从认知骨架中提取
    core_positions = ""
    skeleton = content_sections.get("认知骨架", "")
    if skeleton:
        # 取前500字作为核心立场摘要
        core_positions = skeleton[:500]

    # 构建style：从行为纹理中提取
    style = ""
    behavior = content_sections.get("行为纹理", "")
    if behavior:
        style = f"基于{behavior[:200]}"

    # 生成ID
    agent_id = slugify_zh(name_zh)

    # 构建debate_roles
    debate_roles = f'["{category}"]'

    # 构建domains
    domains = CATEGORY_DOMAINS.get(category, ["综合"])

    return {
        "id": agent_id,
        "name_zh": name_zh,
        "name_en": name_en,
        "period": period,
        "category": category,
        "identity": identity,
        "debate_roles": debate_roles,
        "domains": str(domains),
        "style": style,
        "core_positions": core_positions,
        "content_sections": content_sections,
    }


def parse_markdown_file(filepath: Path, category: str) -> list[dict]:
    """解析一个markdown文件中的所有人物。"""
    text = filepath.read_text(encoding='utf-8')

    # 按 ## 分割人物
    # 找到所有人物的起始位置
    agent_starts = []
    for match in re.finditer(r'^## \d+\.\s+', text, re.MULTILINE):
        agent_starts.append(match.start())

    agents = []
    for i, start in enumerate(agent_starts):
        end = agent_starts[i + 1] if i + 1 < len(agent_starts) else len(text)
        agent_text = text[start:end]
        agent = parse_agent_profile(agent_text, category)
        if agent:
            agents.append(agent)

    return agents


def create_chunks(agent: dict) -> list[dict]:
    """为一个agent创建chunks。"""
    chunks = []
    agent_id = agent["id"]
    now = datetime.now(timezone.utc).isoformat()

    # 从content_sections创建chunks
    for section_name, content in agent["content_sections"].items():
        if not content or len(content) < 50:
            continue

        # 确定layer
        layer = section_name

        # 将长文本分块（每块约500字）
        words = content
        chunk_size = 500
        for j in range(0, len(words), chunk_size):
            chunk_text = words[j:j + chunk_size]
            chunk_id = f"{agent_id}_{layer}_{j // chunk_size:03d}"
            tags = str([layer, agent["category"]])
            chunks.append({
                "id": chunk_id,
                "agent_id": agent_id,
                "layer": layer,
                "source": "",
                "text": chunk_text,
                "tags": tags,
                "token_count": len(chunk_text) // 2,  # 粗略估计
                "quality_score": 0.8,
                "created_at": now,
            })

    return chunks


def import_to_db(agents: list[dict], db_path: Path):
    """将解析出的agents和chunks导入数据库。"""
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL")
    now = datetime.now(timezone.utc).isoformat()

    agent_count = 0
    chunk_count = 0
    skipped = 0

    for agent in agents:
        # 检查是否已存在
        existing = con.execute(
            "SELECT id FROM agents WHERE name_zh = ?", (agent["name_zh"],)
        ).fetchone()
        if existing:
            skipped += 1
            continue

        # 插入agent
        try:
            con.execute("""
                INSERT INTO agents (
                    id, name_zh, name_en, period, category, identity,
                    debate_roles, domains, style, core_positions,
                    good_against, weaknesses, avatar_url,
                    data_quality_score, default_temperature, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                agent["id"], agent["name_zh"], agent["name_en"],
                agent.get("period", ""), agent["category"], agent["identity"],
                agent["debate_roles"], agent["domains"],
                agent["style"], agent["core_positions"],
                "", "", "",  # good_against, weaknesses, avatar_url
                0.8,  # data_quality_score
                0.7,  # default_temperature
                1,    # is_active
                now, now,
            ))
            agent_count += 1
        except sqlite3.IntegrityError:
            skipped += 1
            continue

        # 创建并插入chunks
        chunks = create_chunks(agent)
        for chunk in chunks:
            try:
                con.execute("""
                    INSERT INTO agent_chunks (
                        id, agent_id, layer, source, text, tags,
                        token_count, quality_score, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    chunk["id"], chunk["agent_id"], chunk["layer"],
                    chunk["source"], chunk["text"], chunk["tags"],
                    chunk["token_count"], chunk["quality_score"],
                    chunk["created_at"],
                ))
                # 同步到FTS5
                con.execute("""
                    INSERT INTO agent_chunks_fts (id, agent_id, layer, source, text, tags)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    chunk["id"], chunk["agent_id"], chunk["layer"],
                    chunk["source"], chunk["text"], chunk["tags"],
                ))
                chunk_count += 1
            except sqlite3.IntegrityError:
                pass

    con.commit()
    con.close()

    return agent_count, chunk_count, skipped


def main():
    if len(sys.argv) < 2:
        print("用法: python3 scripts/import_agents.py /path/to/历史人物档案/")
        sys.exit(1)

    archive_dir = Path(sys.argv[1])
    if not archive_dir.exists():
        print(f"目录不存在: {archive_dir}")
        sys.exit(1)

    all_agents = []

    for md_file in sorted(archive_dir.glob("*.md")):
        # 从文件名提取类别
        stem = md_file.stem
        category = CATEGORY_MAP.get(stem)
        if not category:
            # 尝试从文件内容提取类别
            text = md_file.read_text(encoding='utf-8')[:200]
            for key, cat in CATEGORY_MAP.items():
                if key.split('_', 1)[0] in text:
                    category = cat
                    break
        if not category:
            print(f"跳过未识别的文件: {md_file.name}")
            continue

        agents = parse_markdown_file(md_file, category)
        print(f"  {md_file.name}: 解析出 {len(agents)} 人 (类别: {category})")
        all_agents.extend(agents)

    print(f"\n共解析出 {len(all_agents)} 人")

    # 导入数据库
    print(f"导入数据库: {DB_PATH}")
    agent_count, chunk_count, skipped = import_to_db(all_agents, DB_PATH)

    print(f"\n=== 导入完成 ===")
    print(f"新增agent: {agent_count}")
    print(f"新增chunk: {chunk_count}")
    print(f"跳过(已存在): {skipped}")

    # 验证总数
    con = sqlite3.connect(str(DB_PATH))
    total = con.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    total_chunks = con.execute("SELECT COUNT(*) FROM agent_chunks").fetchone()[0]
    con.close()
    print(f"数据库总agent数: {total}")
    print(f"数据库总chunk数: {total_chunks}")


if __name__ == "__main__":
    main()
