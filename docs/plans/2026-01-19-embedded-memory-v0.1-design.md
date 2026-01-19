# Embedded Memory（v0.1）设计稿

目标：提供一个面向嵌入式/设备测试领域的**通用记忆插件**，把对话、分析过程、报告中的信息自动沉淀为可审计的结构化规则，并提供查询/注入接口。DVK 只是一个可选消费者。

## 1. 核心原则（借鉴 claude-mem）

- **Evidence-first**：先记录 Observation（证据面），避免直接从聊天文本“硬写规则”导致污染。
- **Host-LLM consolidation**：由宿主（Claude Code / Codex / OpenCode）的 LLM 负责提取/压缩，插件只负责 prepare/apply。
- **Auditable memory**：规则文件可 code review、可回滚；每条规则必须有 provenance 与 confidence。
- **Low-confidence staging**：低置信写入 `candidates/`，不进权威 `profiles/`。
- **Project-local store（A）**：默认存储在当前项目内（`spec/` + `data/` + `runs/`），支持 `--store-root` 覆盖。

## 2. 适用平台与安装入口

仓库提供：
- Python 库 + CLI（跨平台核心能力）
- `.claude-plugin/`（Claude Code 薄壳；可上 marketplace）
- `.codex/INSTALL.md`（Codex 安装说明；支持 “Fetch and follow instructions...”）
- `.opencode/`（OpenCode 插件文件 + 安装说明）

## 3. 存储布局（store-root）

默认 `store-root = 当前工作目录`，也可通过 `--store-root <path>` 或 `EMBEDDED_MEMORY_ROOT=<path>` 指定。

目录约定：
- 共享规则（可提交）：`spec/memory/profiles/<model_id>/<rule_id>.yaml`
- 候选规则（低置信）：`spec/memory/candidates/<model_id>/<candidate_id>.yaml`
- 本机覆盖（默认不提交）：`data/memory/overrides/<instance_id>.yaml`
- 证据（run 内）：`runs/<run_id>/observations.jsonl`
- 证据（全局缓存）：`data/memory/observations.jsonl`
- 查询索引（可再生）：`data/memory/index.json`
- 变更历史（append-only）：`data/memory/history.jsonl`

## 4. 规则选择器（你已确认：A）

v0.1 仅保证支持以下主键：
- `model_id + fw_version`（resolve 输入）
- `fw_range` 支持：
  - 通配：`1.2.*`
  - 区间：`>=1.2.0 <1.3.0`

合并优先级（从低到高）：
1) 共享层 profiles
2) 本机层 overrides
3) 更窄 `fw_range` 优先
4) 更高 `priority` 优先

## 5. 信息分类（通用 + 嵌入式推荐前缀）

Profile/Override 内使用 `facts` 自由字典（通用），但提供嵌入式领域推荐前缀：
- `facts.transport.*`（串口/I2C/SPI/网络参数默认值、超时、重试）
- `facts.procedure.*`（命令序列补全/强制规程）
- `facts.analysis.*`（默认分析模板/指标）
- `facts.known_issues.*`（已知异常/边界条件）
- `facts.calibration.*`（校准/偏置）

## 6. 编译闭环（C：run 内写 + 全局汇总）

### 6.1 Observe（证据采集）

宿主在对话/分析/报告阶段产生 Observation，写入：
- 首选：`runs/<run_id>/observations.jsonl`（append-only）
- 无 run_id 时：`data/memory/observations.jsonl`

### 6.2 Prepare（生成 compile_request.json）

`embedded-memory compile prepare` 读取证据并生成 `compile_request.json`，供宿主 LLM 使用。

### 6.3 Consolidate（宿主 LLM 输出 compile_response.json）

宿主 LLM 必须输出严格 JSON：`compile_response.json`（只包含结构化变更提案，不直接写文件），并且：
- `request_id` 必须回填自 `compile_request.json`
- 规则/候选/覆盖项必须携带 `confidence` 与 `provenance.observation_ids`（且 observation_id 必须存在于 store 的 observations 中）
- `provenance_summary.observation_ids_used` 必须覆盖所有被引用的 observation ids（用于快速审计）

### 6.4 Apply（校验 + 落盘）

`embedded-memory compile apply`：
- 校验 `compile_response.json`（schema + 约束）
- 运行时校验 provenance 引用的 observation ids 必须存在
- 按 policy 阈值把低置信条目自动转入 `candidates/`（避免污染 `profiles/` / `overrides/`）
- 写入 profiles/candidates/overrides
- 更新 index
- 追加 history 记录

## 7. 查询能力（B）

- `search`：按 `model_id + fw_version` 命中规则摘要
- `show`：展开某条 rule + provenance
- `timeline`：按时间列出 observations + apply 历史
- `diff`：对比同一 rule 的两个 revision

## 8. CLI（v0.1 命令面）

- `embedded-memory observe ...`
- `embedded-memory compile prepare ...`
- `embedded-memory compile apply --in compile_response.json ...`
- `embedded-memory resolve --model-id ... --fw-version ...`
- `embedded-memory search ...`
- `embedded-memory show ...`
- `embedded-memory timeline ...`
- `embedded-memory diff ...`

## 9. Schemas

仓库内提供 JSON Schema：
- `schemas/observation.schema.json`
- `schemas/compile_request.schema.json`
- `schemas/compile_response.schema.json`
