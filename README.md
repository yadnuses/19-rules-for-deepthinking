[中文](README.zh-CN.md) · **English**

---

# 19 Rules for Deepthinking

A set of 19 behavioral rules for LLMs to improve search and information analysis quality. Not generic "be thorough" advice — every rule is derived from a specific historical thinker's methodology, tested through a 200-agent elimination debate, and validated across six rounds of real-world search comparison experiments.

## How This Was Built

### 1. The Roundtable Debate

200 historical figures — scientists, philosophers, engineers, artists, political leaders — participated in a structured elimination debate on the question:

> *"When someone asks a question, how can we transform the rules so the answer becomes more valuable?"*

The 200 were divided into 20 groups of 10. Each group went through 4 rounds (position → critique → deepening → closing), followed by cross-group playoffs. The winner was determined by a final vote across all surviving agents.

**Winner: Aaron Swartz** (tied with Linus Torvalds at 100-100, won on tiebreak).

Swartz's final synthesis — after reading every contribution from all 200 figures — forms the philosophical backbone of these rules:

> *"The value of rule transformation lies not in taking sides, but in designing a rule that forcibly exposes and contains the fundamental tension. It should be like Popper's falsification framework, always reserving the highest seat for refutation; or like Bohr's complementarity principle, allowing seemingly contradictory frameworks to coexist at a higher level."*

### 2. Rules Extraction

The debate output (1.9MB, 880 utterances) was distilled into `SKILL.md` — a human-readable educational document. Then `SKILL.md` was converted into `llm-rules.md` — compact, imperative-form behavioral guidelines that can be embedded directly into an LLM system prompt.

### 3. Empirical Validation

Every rule was tested across six rounds of controlled comparison experiments (normal search vs. rule-based search):

| Round | Question | Key Finding |
|-------|----------|-------------|
| 1 | Basic comparison | Rule-based search produced concrete data vs. vague impressions |
| 2 | Deep search | 4-layer depth progression uncovered structural tensions invisible to surface search |
| 3 | Rule utility audit | All 22 original rules triggered; 7 overlapped pairs identified and merged to 19 |
| 4 | "Medical industry gaps" | Rule 7 (define concepts first) caught a critical error: "gaps" had been narrowed to just "talent gaps" — proper operationalization revealed 6 distinct gap dimensions |
| 5 | "AI's next wave" | Rule 2 (falsification first) exposed that the top 3 funded sectors (foundation models, humanoid robots, general AI agents) had the worst unit economics |
| 6 | "Are degrees losing value?" | Rules 13-18 transformed a polarized yes/no debate into a structural analysis: the premium hadn't disappeared, it had bifurcated |

## The 19 Rules

### Core Principles (always active)

| # | Rule | Source |
|---|------|--------|
| 1 | Rewrite vague questions into falsifiable conditional questions | Pasteur |
| 2 | Prioritize falsification — expose assumptions, search counterexamples first | Popper |
| 3 | Use publicly verifiable data sources, not single-authority opinions | Pasteur |
| 4 | Adapt search strategy based on intermediate results | Shannon, Kissinger |

### Query Reformulation

| # | Rule | Source |
|---|------|--------|
| 5 | Replace abstract terms with operational definitions before searching | Wittgenstein, Sontag |
| 6 | Supplement missing constraints (time range, resource limits, conflicts) | Machiavelli |
| 7 | Define core concepts before deduction | Locke, Rawls |

### Information Filtering

| # | Rule | Source |
|---|------|--------|
| 8 | No vague quantifiers ("many," "some," "everyone agrees") | Hayek |
| 9 | Cross-confirm every conclusion with ≥3 independent sources | Pasteur, Nightingale |
| 10 | Annotate every data point with original source and date | Nightingale, Hayek |

### Search Depth

| # | Rule | Source |
|---|------|--------|
| 11 | Progress through depth layers: surface → structured → reverse | Kissinger |
| 12 | Generate finer-grained sub-queries when contradictions emerge | Kissinger, Shannon |

### Anti-Bias

| # | Rule | Source |
|---|------|--------|
| 13 | Include strongest supporting AND opposing arguments at equal length | Swartz (synthesizing Popper + Bohr) |
| 14 | State explicitly under what conditions the conclusion fails | Popper, Lovelace |
| 15 | Never use popularity or consensus as evidence of correctness | Hayek, Sontag |

### Output Gates (self-check before every answer)

| # | Rule | Source |
|---|------|--------|
| 16 | Verifiability — label unverifiable claims as speculation | Pasteur |
| 17 | Conflicts of interest — flag sources with vested interests | Sontag, Carson |
| 18 | Sample scope — flag survivorship bias when only success cases exist | Nightingale, Taleb |
| 19 | Search blind spots — self-audit whether the search rules distorted the answer | Sontag, Swartz |

## Intellectual Genealogy

The 19 rules trace back to **14 core contributors** spanning **10 debate groups**:

| Contributor | Group | Contributed Rules |
|-------------|-------|-------------------|
| Louis Pasteur | 1 | 1, 3, 9, 16 |
| Karl Popper | 2 | 2, 13, 14 |
| Claude Shannon | 1 | 4, 12 |
| Henry Kissinger | 1 | 4, 11, 12 |
| Ludwig Wittgenstein | 2 | 5 |
| Susan Sontag | 1 | 5, 17, 19 |
| Niccolò Machiavelli | 1 | 6 |
| John Locke | 1 | 7 |
| John Rawls | 1 | 7 |
| Friedrich Hayek | 1 | 8, 10, 15 |
| Florence Nightingale | 2 | 9, 10, 18 |
| Aaron Swartz | 16 (Finals) | 13, 19 |
| Ada Lovelace | 16 | 14 |
| Nassim Taleb | 10 | 18 |

Additional contributors whose ideas shaped the overall framework: **Daniel Kahneman** (System 1/2 — anti-bias architecture), **Confucius** (contextual adaptation), **Rachel Carson** (tracing systemic interconnections), **Niels Bohr** (complementarity — allowing contradictory frameworks to coexist).

For the full intellectual genealogy with direct quotes from each debate contribution, see [`简体中文版本/llm-rules-construction.md`](简体中文版本/llm-rules-construction.md).

## Design Philosophy

Three principles guided the rules' construction:

1. **Prohibitive over prescriptive** (Hayek): Rules say what NOT to do, clearing cognitive obstacles rather than narrowing search paths.
2. **Falsification over verification** (Popper): Every rule is designed to surface what's wrong with a conclusion, not what's right about it.
3. **Self-referential closure** (Sontag, Swartz): Rule 19 ensures the rule system itself cannot become a new tyranny — it must audit its own blind spots.

## File Structure

```
19-rules-for-deepthinking/
├── README.md
├── 简体中文版本/
│   ├── SKILL.md                       ← Educational document from debate output
│   ├── llm-rules.md                   ← 19 behavioral rules (for LLM embedding)
│   └── llm-rules-construction.md      ← Full intellectual genealogy with debate quotes
└── English version/
    ├── SKILL-en.md                    ← English translation of SKILL.md
    └── llm-rules-en.md                ← English version of the 19 rules
```

## Usage

To use these rules with an LLM, embed `llm-rules.md` (Chinese) or `llm-rules-en.md` (English) into the system prompt or as a behavioral guideline document. The rules are designed to be self-executing — each rule specifies both a trigger condition and a required action.

## License

MIT
