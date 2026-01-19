# Embedded Memory (v0.1)

An embedded/device-testing focused memory plugin that records **observations** (chat/analysis/report), consolidates them into **auditable rules** via host LLM output, and provides **query + resolve** APIs for downstream tools (e.g. DVK).

Key principles:
- Evidence-first: append-only `observations.jsonl`
- Consolidation: host LLM produces a strict `compile_response.json`
- Apply: local tool validates + writes `profiles/` (rules), `candidates/`, `overrides/`
- Query: `search/show/timeline/diff`

This repo is designed to work across:
- Claude Code (via `.claude-plugin/`)
- Codex CLI (via `.codex/INSTALL.md`)
- OpenCode (via `.opencode/`)

## Install

### Claude Code

Marketplace installs are recommended (add this plugin to your marketplace repo):
- See `.claude-plugin/INSTALL.md`

### Codex

Fetch and follow instructions from:
`https://raw.githubusercontent.com/<OWNER>/<REPO>/main/.codex/INSTALL.md`

### OpenCode

Fetch and follow instructions from:
`https://raw.githubusercontent.com/<OWNER>/<REPO>/main/.opencode/INSTALL.md`

## Quick usage (CLI)

Run from a project directory (or set `EMBEDDED_MEMORY_ROOT`):

```bash
python -m embedded_memory observe --run-id "run-001" --model-id "example_model" --fw-version "1.2.3" --source chat --content "UART default baudrate is 115200"
python -m embedded_memory compile prepare --run-id "run-001" --out compile_request.json
# Host LLM produces compile_response.json (STRICT JSON) that includes request_id + provenance
python -m embedded_memory compile apply --in compile_response.json --request compile_request.json
python -m embedded_memory search --model-id "example_model" --fw-version "1.2.3"
```
