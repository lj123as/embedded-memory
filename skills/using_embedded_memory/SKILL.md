---
name: using_embedded_memory
description: "Embedded Memory: observe -> (host LLM consolidate) -> apply -> query/resolve"
---

# Embedded Memory (v0.1)

This plugin stores **auditable embedded/device-testing knowledge** inside the current project (or `EMBEDDED_MEMORY_ROOT`).

## Concepts

- **Observation**: append-only evidence from chat/analysis/report (`observations.jsonl`)
- **Profile**: reusable rules keyed by `model_id + fw_range` (`spec/memory/profiles/`)
- **Override**: local/instance-specific facts (`data/memory/overrides/`)
- **Candidate**: low-confidence proposal (`spec/memory/candidates/`)

## Workflow (recommended)

1) Record observations during work:

```bash
python -m embedded_memory observe --run-id "<run_id>" --model-id "<model>" --fw-version "<fw>" --source chat --content "..."
python -m embedded_memory observe --run-id "<run_id>" --model-id "<model>" --fw-version "<fw>" --source report --content "key findings..."
```

2) Prepare a compile request:

```bash
python -m embedded_memory compile prepare --run-id "<run_id>" --out compile_request.json
```

3) Use your host LLM (Claude Code / Codex / OpenCode) to read `compile_request.json` and produce **STRICT JSON** `compile_response.json`.

4) Apply the response (schema-validated) to write profiles/candidates/overrides and update index/history:

```bash
python -m embedded_memory compile apply --in compile_response.json
```

5) Query:

```bash
python -m embedded_memory search --model-id "<model>" --fw-version "<fw>"
python -m embedded_memory resolve --model-id "<model>" --fw-version "<fw>"
python -m embedded_memory timeline --model-id "<model>"
```

## Notes

- v0.1 intentionally avoids vector DB / embeddings. The source of truth is files + provenance.
- Low-confidence items should be written to `candidates/` (not `profiles/`).

