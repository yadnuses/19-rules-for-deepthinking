"""分组策略 — 按类别均衡分配agent到各组。"""

from __future__ import annotations

import random

from .database import Agent

# 完整类别列表（按编号排序）
CATEGORIES = [
    "一、思想与哲学", "二、科学与数学", "三、政治与治理",
    "四、宗教与精神", "五、文学", "六、艺术",
    "七、工程与发明", "八、经济与社会科学", "九、探索与连接",
    "十、当代关键人物", "十一、互联网与数字文化",
    "十二、商业与企业家", "十三、医学与健康", "十四、法律与正义",
    "十五、军事与战略", "十六、体育与竞技", "十七、音乐与表演艺术",
    "十八、女性先锋与平权领袖", "十九、环境与生态", "二十、视觉艺术与建筑",
]


def assign_groups(agents: list[Agent], group_size: int) -> list[list[Agent]]:
    """Assign agents to groups, balanced by category."""
    by_cat: dict[str, list[Agent]] = {}
    for a in agents:
        by_cat.setdefault(a.category, []).append(a)
    for cat in by_cat:
        random.shuffle(by_cat[cat])

    # 动态获取实际存在的类别，按CATEGORIES顺序排列
    active_cats = [c for c in CATEGORIES if c in by_cat]
    # 添加不在预定义列表中的类别
    for cat in by_cat:
        if cat not in active_cats:
            active_cats.append(cat)

    num_groups = len(agents) // group_size + (1 if len(agents) % group_size else 0)
    groups: list[list[Agent]] = [[] for _ in range(num_groups)]
    cat_idx: dict[str, int] = {c: 0 for c in active_cats}

    for g_idx in range(num_groups):
        cats_used = set()
        while len(groups[g_idx]) < group_size:
            placed = False
            for cat in active_cats:
                idx = cat_idx.get(cat, 0)
                agents_in_cat = by_cat.get(cat, [])
                if idx < len(agents_in_cat) and cat not in cats_used:
                    groups[g_idx].append(agents_in_cat[idx])
                    cat_idx[cat] = idx + 1
                    cats_used.add(cat)
                    placed = True
                    break
            if not placed:
                for cat in active_cats:
                    idx = cat_idx.get(cat, 0)
                    agents_in_cat = by_cat.get(cat, [])
                    if idx < len(agents_in_cat):
                        groups[g_idx].append(agents_in_cat[idx])
                        cat_idx[cat] = idx + 1
                        break
                else:
                    break
        if len(groups[g_idx]) < group_size:
            remaining = []
            for cat in active_cats:
                idx = cat_idx.get(cat, 0)
                remaining.extend(by_cat.get(cat, [])[idx:])
            random.shuffle(remaining)
            groups[g_idx].extend(remaining[: group_size - len(groups[g_idx])])

    return [g for g in groups if g]
