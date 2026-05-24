# 圆桌派 v2 — 实现计划

基于设计文档：`2026-05-11-roundtable-v2-design.md`

## 阶段1：辩论质量提升（最快见效）

### 1.1 强化系统prompt（engine/debate.py）
- [ ] 重写 `_speak()` 中的system prompt，加入反套路规则
- [ ] 每轮使用不同的system prompt（交锋轮加"直接回应"、终论轮加"不要总结"）
- [ ] 测试：跑1组对比新旧prompt的发言质量

### 1.2 历史记录优化（engine/debate.py）
- [ ] `_build_prompt()` 中保留最近50条完整发言
- [ ] 对更早的发言生成200字摘要（用LLM，缓存到GroupDiscussion中）
- [ ] 测试：跑1组验证摘要质量和上下文长度

### 1.3 质量评估（engine/quality.py 新文件）
- [ ] `assess_quality(agent, utterance, topic) -> float`：用LLM快速评估发言质量
- [ ] 评估prompt：50 tokens，评分1-5
- [ ] 批量评估：每轮结束后并行评估10条发言
- [ ] 在GroupDiscussion中记录quality_scores

## 阶段2：赛制引擎（engine/tournament.py）

### 2.1 核心框架
- [ ] 定义 TournamentConfig、TournamentRound、TournamentResult 数据类
- [ ] 实现 Tournament.run() 主流程
- [ ] 实现事件回调机制（emit_event）

### 2.2 淘汰赛模式
- [ ] 实现多轮淘汰：海选→复赛→半决赛→决赛
- [ ] 每轮自动计算分组数和晋级比例
- [ ] 支持配置：--group-size, --advancers

### 2.3 圆桌会议模式
- [ ] 实现不分组辩论：每轮重新随机分组
- [ ] 每轮结束后全民投票更新排名
- [ ] 支持配置：--rounds

### 2.4 混合模式
- [ ] 海选阶段用淘汰赛
- [ ] 最后阶段切换为圆桌会议

### 2.5 平票加赛
- [ ] 检测平票情况
- [ ] 让平票者进行1轮faceoff
- [ ] faceoff由同组其他人投票

### 2.6 质量门控集成
- [ ] 在辩论阶段调用质量评估
- [ ] 低质量发言在投票时降低权重（0.5x）

## 阶段3：流程整合（run.py）

### 3.1 统一入口
- [ ] 重写 run.py 的 argparse，支持 --mode, --prev-session, --agents 等参数
- [ ] 根据 mode 调用 Tournament 的不同模式
- [ ] meta 和 top3 模式通过 --prev-session 加载前轮数据

### 3.2 旧脚本薄包装
- [ ] run_meta.py 改为调用 tournament.py 的 meta 模式
- [ ] run_top3_debate.py 改为调用 tournament.py 的 top3 模式

## 阶段4：Word导出（engine/export.py）

### 4.1 export_word() 函数
- [ ] 标题页（议题、日期、胜者）
- [ ] 议题背景材料
- [ ] 各轮辩论（按组、按轮次）
- [ ] 投票结果
- [ ] 思想综合
- [ ] 输出到 results/{session_id}/debate.docx

## 阶段5：Web可视化（web/）

### 5.1 Flask后端（web/app.py）
- [ ] GET / — 返回index.html
- [ ] GET /api/stream — SSE事件流
- [ ] GET /api/status — 当前状态
- [ ] GET /api/results — 历史结果列表
- [ ] GET /api/results/<session_id> — 完整结果

### 5.2 事件系统集成
- [ ] engine/events.py — 事件总线（EventBus类）
- [ ] tournament.py 在关键节点 emit 事件
- [ ] Flask SSE 从事件队列读取推送
- [ ] CLI模式下事件打印到终端

### 5.3 前端（web/static/index.html）
- [ ] 实时辩论进度条
- [ ] agent发言滚动显示
- [ ] 投票曲线图（Chart.js）
- [ ] 响应式布局

## 阶段6：对比分析（engine/analysis.py）

### 6.1 compare_debates()
- [ ] 加载两轮辩论的checkpoint和debate.md
- [ ] 用LLM生成对比分析：胜者变化、观点演变、阵营分析、关键转折点
- [ ] 输出Markdown对比报告

### 6.2 观点指纹提取
- [ ] 从每条发言中提取核心论点摘要
- [ ] 存储为结构化JSON

## 阶段7：数据库集成

### 7.1 自定义角色支持
- [ ] data/custom_agents.json 格式定义
- [ ] database.py 的 load_agents() 支持JSON导入
- [ ] 按 name_zh 去重

### 7.2 扩充数据库集成
- [ ] 用户提供扩充后的DB
- [ ] 验证DB schema兼容性
- [ ] 测试500人规模运行

## 依赖

- python-docx（已安装）
- Flask（需安装：pip3 install flask）
- Chart.js（CDN引入，无需npm）

## 预估工作量

| 阶段 | 预估时间 | 复杂度 |
|------|---------|--------|
| 1. 辩论质量 | 30分钟 | 低 |
| 2. 赛制引擎 | 60分钟 | 高 |
| 3. 流程整合 | 30分钟 | 中 |
| 4. Word导出 | 20分钟 | 低 |
| 5. Web可视化 | 90分钟 | 高 |
| 6. 对比分析 | 30分钟 | 中 |
| 7. 数据库集成 | 15分钟 | 低 |
| **总计** | **~4小时** | |
