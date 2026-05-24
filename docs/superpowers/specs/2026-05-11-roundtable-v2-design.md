# 圆桌派 v2 — 全面改进设计

日期：2026-05-11
状态：设计完成，待实现

## 目标

在现有圆桌派基础上全面改进：辩论质量、赛制投票、流程整合、输出展示、规模扩展（500+人）。

## 约束

- 保持现有200人数据库不变，用户自行扩充到500+
- LLM：mimo-v2.5-pro via 小米代理（Anthropic Messages API格式）
- 并发限制：有效并发≤20
- 不引入Redis等外部依赖，保持轻量

## 模块1：数据库扩充支持

### 自定义角色

新增 `data/custom_agents.json`：

```json
[
  {
    "name_zh": "爱丽丝",
    "name_en": "Alice",
    "identity": "21世纪的AI研究者",
    "style": "用数据和案例说话",
    "core_positions": "AI应该服务于人类自由",
    "domains": ["人工智能", "伦理学"],
    "category": "技术先驱"
  }
]
```

### database.py 改动

- `load_agents(con)` 增加 `custom_path` 参数
- 同时读取DB和JSON，按 `name_zh` 去重
- 新人物自动创建FTS5 context chunks

### 数据库扩充脚本

- `scripts/expand_agents.py`：用LLM批量生成新人物
- 按10个类别均衡生成
- 自动写入DB，自动创建context chunks

## 模块2：赛制引擎

### 新文件：engine/tournament.py

```python
@dataclass
class TournamentConfig:
    mode: str  # "elimination" | "roundtable" | "hybrid"
    group_size: int = 10
    advancers_per_group: int = 2
    rounds_per_stage: int = 4
    quality_gate: bool = True
    tie_breaker: str = "faceoff"  # "faceoff" | "random"

@dataclass
class TournamentRound:
    stage_name: str
    groups: list[GroupDiscussion]
    eliminated: list[str]
    advanced: list[str]

class Tournament:
    def __init__(self, config: TournamentConfig): ...
    def run(self, con, agents, topic, brief) -> TournamentResult: ...
```

### 淘汰赛模式（500人）

| 轮次 | 人数 | 分组 | 每组晋级 | 结果 |
|------|------|------|---------|------|
| 海选 | 500 | 50组×10人 | 2 | 100人 |
| 复赛 | 100 | 20组×5人 | 2 | 40人 |
| 半决赛 | 40 | 8组×5人 | 1 | 8人 |
| 决赛 | 8 | 1组×8人 | — | 前3名 |
| 全民投票 | 500人 | — | — | 冠军 |

### 圆桌会议模式

- 不淘汰，每轮重新随机分组
- 每轮结束后全民投票更新排名
- 跑3-5轮后取累计票数最高者

### 混合模式

- 海选用淘汰赛快速筛选（500→100→40）
- 最后阶段用圆桌会议深入讨论（40人，3轮）

### 质量门控

- 每轮辩论后，用LLM快速评估每条发言的"思想密度"
- 评估标准：是否引用具体史实、是否有独特视角、是否回应他人论点
- 评分1-5，低于3分的发言在投票时权重降低（0.5x）
- 评估prompt简短（50 tokens），批量处理，不显著增加运行时间

### 平票处理

- 当前：随机选一个
- 改为：让平票者进行1轮加赛（"faceoff"），由同组其他人投票
- 如果加赛仍然平票，才随机选择

## 模块3：辩论质量提升

### 系统prompt强化

```
你是{agent.name_zh}（{agent.identity}）。

核心规则：
- 用你自己的思想体系回答，不要用通用的哲学套话
- 引用你自己的经历、著作、历史事件来支撑论点
- 限制比喻使用：最多1个核心比喻，不要堆砌
- 不要以"诸位"、"朋友们"开头，直接切入观点
- 如果你不同意某人，指出具体的逻辑漏洞，不要泛泛而谈
```

### 历史记录优化

- 保留最近50条完整发言（不截断）
- 对更早的发言生成200字"讨论脉络摘要"
- 摘要由LLM在每轮开始前生成，缓存复用

### 反套路指令

- 交锋轮："不要说'X的观点让我想起了...'这种套话，直接回应X的核心论点"
- 深化轮："不要重新复述你的立场，直接说你改变了什么、为什么改变"
- 终论轮："不要总结前面所有人说了什么，直接给出你的最终判断"

### 发言质量评估（复用质量门控）

- 在辩论阶段同步评估
- 低质量发言标记为 `quality_score < 3`
- 投票时降低权重

## 模块4：流程整合

### 统一入口：run.py

```bash
# 标准辩论（默认淘汰赛）
python3 run.py "你的议题"

# 指定赛制
python3 run.py --mode elimination --agents 500 "你的议题"
python3 run.py --mode roundtable --rounds 5 "你的议题"
python3 run.py --mode hybrid "你的议题"

# 元评论（基于前轮实录）
python3 run.py --mode meta --prev-session roundtable_20260511_000950 "你的议题"

# 前3深度对决
python3 run.py --mode top3 --prev-session roundtable_20260511_004640 "你的议题"

# 配置参数
python3 run.py --group-size 10 --advancers 2 --quality-gate "你的议题"
```

### 内部结构

- `run.py`：参数解析 + 调用 `engine/tournament.py`
- `tournament.py`：全流程管理（分组→辩论→晋级→决赛→投票→综合→导出）
- `run_meta.py`、`run_top3_debate.py`：保留为便捷别名

### 旧脚本处理

- `run_meta.py` 和 `run_top3_debate.py` 的核心逻辑合并到 `tournament.py`
- 旧文件改为薄包装（thin wrapper），内部调用 `tournament.py`，保持向后兼容
- 长期可废弃

## 模块5：输出与展示

### 5a. Word导出（engine/export.py扩展）

新增 `export_word()` 函数：

```
标题页
├── 议题：...
├── 日期：...
└── 最终胜者：...

议题背景材料
├── 背景概述
└── 核心争论点

小组辩论
├── 第1组：成员列表
│   ├── 第1轮（立论）
│   │   ├── 老子：...
│   │   └── ...
│   └── ...
└── ...

决赛
├── 晋级者列表
└── 各轮发言

投票结果
├── 全民投票结果
└── 投票理由汇总

思想综合
└── 胜者综合全文
```

- 使用python-docx
- 标题用Heading样式，正文用Normal样式
- 输出路径：`results/{session_id}/debate.docx`

### 5b. Web实时可视化（web/）

```
web/
├── app.py          # Flask应用
├── static/
│   └── index.html  # 单页应用（HTML+CSS+JS）
└── templates/
    └── (unused)
```

**后端（app.py）**：
- `GET /` — 返回index.html
- `GET /api/stream` — SSE事件流，推送辩论进度
- `GET /api/status` — 当前辩论状态（JSON）
- `GET /api/results` — 历史辩论结果列表
- `GET /api/results/<session_id>` — 特定辩论的完整结果

**事件类型**：
- `group_start` — 新组开始辩论
- `utterance` — 某agent发言
- `round_end` — 某轮结束，包含投票结果
- `stage_end` — 某阶段结束，包含晋级名单
- `vote_update` — 全民投票进度更新
- `final` — 最终结果

**前端（index.html）**：
- 纯HTML/CSS/JS，无npm依赖
- Chart.js（CDN）绘制投票曲线
- 实时滚动显示agent发言
- 进度条显示当前阶段
- 响应式布局

**集成方式**：
- `tournament.py` 在关键节点调用 `emit_event(event_type, data)`
- 事件写入一个共享的事件队列
- Flask SSE端点从队列读取事件推送给前端
- CLI模式下事件只打印到终端

### 5c. 辩论对比分析（engine/analysis.py）

```python
def compare_debates(session_a: str, session_b: str, topic: str) -> ComparisonReport:
    """对比两轮辩论的差异。"""
```

**对比维度**：
- 胜者变化：谁赢了、为什么换了
- 观点演变：核心论点有什么变化
- 阵营分析：哪些agent的观点发生了转变
- 关键转折点：哪次发言改变了辩论走向

**输出**：
- Markdown对比报告
- 结构化JSON（观点指纹、阵营分布、转折点列表）

## 实现顺序

1. **模块3：辩论质量**（改prompt，最快见效）
2. **模块2：赛制引擎**（tournament.py核心）
3. **模块4：流程整合**（统一入口）
4. **模块5a：Word导出**（简单直接）
5. **模块5b：Web可视化**（独立层）
6. **模块5c：对比分析**（锦上添花）
7. **模块1：数据库扩充**（用户提供DB后集成）

## 文件清单

### 新增文件
- `engine/tournament.py` — 赛制引擎
- `engine/analysis.py` — 对比分析
- `web/app.py` — Flask Web应用
- `web/static/index.html` — Web前端
- `data/custom_agents.json` — 自定义角色
- `scripts/expand_agents.py` — 数据库扩充脚本
- `docs/superpowers/specs/2026-05-11-roundtable-v2-design.md` — 本设计文档

### 修改文件
- `engine/debate.py` — 优化prompt、历史记录、质量评估
- `engine/voting.py` — 平票处理、质量权重
- `engine/database.py` — 支持自定义角色
- `engine/export.py` — 新增Word导出
- `run.py` — 统一入口，支持多种模式
- `SKILL.md` — 更新文档

### 保留文件（不修改）
- `engine/llm.py` — LLM调用层
- `engine/grouping.py` — 分组策略
- `engine/synthesis.py` — 思想综合
- `engine/__init__.py` — 包初始化
