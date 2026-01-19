from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import unified_diff
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .semver import matches, specificity_score

@dataclass(frozen=True)
class MemoryStore:
    root: Path

    @staticmethod
    def from_root(root: str | Path) -> "MemoryStore":
        return MemoryStore(root=Path(root).resolve())

    def observe(
        self,
        *,
        run_id: str | None,
        model_id: str,
        fw_version: str,
        instance_id: str | None,
        source: str,
        content: str,
    ) -> Path:
        observation = {
            "id": str(uuid.uuid4()),
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "subject": {"model_id": model_id, "fw_version": fw_version},
            "content": content,
        }
        if instance_id:
            observation["subject"]["instance_id"] = instance_id
        self._validate("observation.schema.json", observation)

        target = (
            self.root / "runs" / run_id / "observations.jsonl"
            if run_id
            else self.root / "data" / "memory" / "observations.jsonl"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(observation, ensure_ascii=False) + "\n")
        return target

    def compile_prepare(self, *, run_id: str | None, out_path: str | Path, limit: int) -> Path:
        out_path = Path(out_path)
        observations: list[dict[str, Any]] = []
        if run_id:
            observations.extend(self._read_jsonl(self.root / "runs" / run_id / "observations.jsonl"))
        observations.extend(self._read_jsonl(self.root / "data" / "memory" / "observations.jsonl"))
        observations = observations[-max(1, limit) :]

        request_id = str(uuid.uuid4())
        observation_ids = [o.get("id") for o in observations if isinstance(o.get("id"), str)]
        request: dict[str, Any] = {
            "schema_version": "0.1",
            "request_id": request_id,
            "store_root": str(self.root),
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "policy": {
                "min_confidence_profile": 0.85,
                "min_confidence_override": 0.80,
                "write_low_confidence_to_candidates": True,
                "facts_prefix_recommendations": [
                    "facts.transport.*",
                    "facts.procedure.*",
                    "facts.analysis.*",
                    "facts.known_issues.*",
                    "facts.calibration.*",
                ],
                "extraction_targets": {
                    "analysis": {
                        "default_templates_key": "facts.analysis.default_templates",
                        "allowed_templates": ["eda", "cleaning", "metrics", "anomaly", "viz", "full"],
                        "instructions": "If evidence suggests a default analysis workflow for this model+fw, write facts.analysis.default_templates as an ordered list of template keys (first is preferred).",
                    }
                },
            },
            "inputs": {
                "allowed_write_paths": [
                    "spec/memory/profiles/",
                    "spec/memory/candidates/",
                    "data/memory/overrides/",
                ],
                "forbidden_write_paths": [
                    ".git/",
                    ".github/",
                    "src/",
                    "schemas/",
                ],
            },
            "observation_ids": observation_ids,
            "observations": observations,
            "note": "Host LLM must output a STRICT JSON compile_response.json only (no prose). Use policy.extraction_targets as guidance; include provenance.observation_ids for every proposed item.",
        }
        self._validate("compile_request.schema.json", request)
        out_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        return out_path

    def compile_apply(self, *, input_path: str | Path, request_path: str | Path | None) -> None:
        data = json.loads(Path(input_path).read_text(encoding="utf-8"))
        self._validate("compile_response.schema.json", data)

        request = None
        if request_path:
            request = json.loads(Path(request_path).read_text(encoding="utf-8"))
            self._validate("compile_request.schema.json", request)
            if data.get("request_id") != request.get("request_id"):
                raise ValueError("compile_response.request_id does not match compile_request.request_id")

        policy = (request or {}).get("policy") or data.get("policy_echo") or {}
        min_conf_profile = float(policy.get("min_confidence_profile", 0.85))
        min_conf_override = float(policy.get("min_confidence_override", 0.80))
        low_to_candidates = bool(policy.get("write_low_confidence_to_candidates", True))

        available_obs_ids = self._available_observation_ids()
        used_obs_ids: set[str] = set()

        def validate_obs_ids(ids: list[str], context: str) -> None:
            missing = [oid for oid in ids if oid not in available_obs_ids]
            if missing:
                raise ValueError(f"{context}: provenance references unknown observation ids: {missing[:5]}")
            used_obs_ids.update(ids)

        def to_candidate(model_id: str, *, candidate_id: str, confidence: float, provenance: dict[str, Any], proposal: dict[str, Any], reason: str) -> dict[str, Any]:
            return {
                "id": candidate_id,
                "model_id": model_id,
                "confidence": confidence,
                "provenance": provenance,
                "proposal": proposal,
                "reason": reason,
            }

        now = datetime.now(timezone.utc).isoformat()
        changed_paths: list[str] = []
        candidates_auto: list[dict[str, Any]] = []

        for item in data.get("profiles_to_upsert", []) or []:
            model_id = item.get("model_id")
            rule = item.get("rule") or {}
            rule_id = rule.get("id")
            fw_range = rule.get("fw_range")
            confidence = rule.get("confidence")
            provenance = rule.get("provenance") or {}
            obs_ids = provenance.get("observation_ids") or []
            if not isinstance(obs_ids, list):
                raise ValueError("rule.provenance.observation_ids must be a list")

            if not model_id or not rule_id or not fw_range:
                raise ValueError("profiles_to_upsert items must include model_id + rule.id + rule.fw_range")
            if not isinstance(confidence, (int, float)):
                raise ValueError("rule.confidence must be a number in [0,1]")
            validate_obs_ids([str(x) for x in obs_ids], f"profile rule {model_id}/{rule_id}")

            if float(confidence) < min_conf_profile and low_to_candidates:
                candidates_auto.append(
                    to_candidate(
                        model_id,
                        candidate_id=f"profile::{rule_id}",
                        confidence=float(confidence),
                        provenance=provenance,
                        proposal=rule,
                        reason=f"confidence<{min_conf_profile}",
                    )
                )
                continue

            path = self.root / "spec" / "memory" / "profiles" / model_id / f"{rule_id}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            doc = {
                "schema_version": "0.1",
                "model_id": model_id,
                "rules": [
                    {
                        **rule,
                        "updated_at": now,
                    }
                ],
            }
            new_text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
            self._write_with_revision(kind="profiles", model_id=model_id, key=rule_id, path=path, new_text=new_text)
            changed_paths.append(str(path))

        for item in data.get("candidates_to_create", []) or []:
            model_id = item.get("model_id") or "unknown_model"
            candidate_id = item.get("id") or str(uuid.uuid4())
            confidence = item.get("confidence", 0.0)
            provenance = item.get("provenance") or {}
            obs_ids = provenance.get("observation_ids") or []
            if not isinstance(obs_ids, list):
                raise ValueError("candidate.provenance.observation_ids must be a list")
            validate_obs_ids([str(x) for x in obs_ids], f"candidate {model_id}/{candidate_id}")

            path = self.root / "spec" / "memory" / "candidates" / model_id / f"{candidate_id}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            doc = {"schema_version": "0.1", "model_id": model_id, "candidate": {**item, "updated_at": now}}
            text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
            self._write_with_revision(kind="candidates", model_id=model_id, key=candidate_id, path=path, new_text=text)
            changed_paths.append(str(path))

        for item in data.get("overrides_to_upsert", []) or []:
            instance_id = item.get("instance_id") or "unknown_instance"
            confidence = item.get("confidence", 0.0)
            provenance = item.get("provenance") or {}
            obs_ids = provenance.get("observation_ids") or []
            if not isinstance(obs_ids, list):
                raise ValueError("override.provenance.observation_ids must be a list")
            validate_obs_ids([str(x) for x in obs_ids], f"override {instance_id}")

            if float(confidence) < min_conf_override and low_to_candidates:
                # Overrides have no model_id; keep them as candidate grouped by a synthetic model bucket.
                model_id = "instance_overrides"
                candidate_id = f"override::{instance_id}"
                candidates_auto.append(
                    to_candidate(
                        model_id,
                        candidate_id=candidate_id,
                        confidence=float(confidence),
                        provenance=provenance,
                        proposal=item,
                        reason=f"confidence<{min_conf_override}",
                    )
                )
                continue

            path = self.root / "data" / "memory" / "overrides" / f"{instance_id}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            doc = {"schema_version": "0.1", "instance_id": instance_id, "override": {**item, "updated_at": now}}
            text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
            self._write_with_revision(kind="overrides", model_id=None, key=instance_id, path=path, new_text=text)
            changed_paths.append(str(path))

        for item in candidates_auto:
            model_id = item["model_id"]
            candidate_id = item["id"]
            path = self.root / "spec" / "memory" / "candidates" / model_id / f"{candidate_id}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            doc = {"schema_version": "0.1", "model_id": model_id, "candidate": {**item, "updated_at": now}}
            text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
            self._write_with_revision(kind="candidates", model_id=model_id, key=candidate_id, path=path, new_text=text)
            changed_paths.append(str(path))

        summary_ids = data.get("provenance_summary", {}).get("observation_ids_used") or []
        if not isinstance(summary_ids, list):
            raise ValueError("provenance_summary.observation_ids_used must be a list")
        validate_obs_ids([str(x) for x in summary_ids], "provenance_summary")
        if not used_obs_ids.issubset(set([str(x) for x in summary_ids])):
            raise ValueError("provenance_summary.observation_ids_used must include all ids referenced by rules/candidates/overrides")

        self._rebuild_index()
        self._append_history(
            {
                "ts": now,
                "kind": "compile_apply",
                "input": str(Path(input_path).resolve()),
                "request": str(Path(request_path).resolve()) if request_path else None,
                "request_id": data.get("request_id"),
                "changed_paths": changed_paths,
            }
        )

    def search(self, *, model_id: str, fw_version: str) -> list[dict[str, Any]]:
        index = self._load_index(rebuild_if_missing=True)
        candidates = index.get("profiles", {}).get(model_id, [])
        hits = []
        for entry in candidates:
            if matches(fw_version, entry["fw_range"]):
                hits.append(entry)
        hits.sort(key=lambda e: (-e.get("specificity", 0), -e.get("priority", 0)))
        print(json.dumps({"model_id": model_id, "fw_version": fw_version, "matches": hits}, ensure_ascii=False, indent=2))
        return hits

    def show(self, *, model_id: str, rule_id: str) -> None:
        path = self.root / "spec" / "memory" / "profiles" / model_id / f"{rule_id}.yaml"
        print(path.read_text(encoding="utf-8"))

    def resolve(self, *, model_id: str, fw_version: str, instance_id: str | None) -> dict[str, Any]:
        hits = self.search(model_id=model_id, fw_version=fw_version)
        effective_facts: dict[str, Any] = {}
        matched = []
        for entry in hits:
            rule = self._load_rule(entry["path"])
            matched.append({"rule_id": entry["rule_id"], "fw_range": entry["fw_range"], "path": entry["path"]})
            self._deep_merge(effective_facts, rule.get("facts") or {})

        result = {
            "schema_version": "0.1",
            "model_id": model_id,
            "fw_version": fw_version,
            "instance_id": instance_id,
            "effective_profile": {"facts": effective_facts, "matched_rules": matched},
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    def timeline(self, *, model_id: str | None, run_id: str | None, limit: int) -> None:
        events: list[dict[str, Any]] = []
        if run_id:
            events.extend(self._read_jsonl(self.root / "runs" / run_id / "observations.jsonl"))
        else:
            runs_dir = self.root / "runs"
            if runs_dir.exists():
                for p in sorted(runs_dir.glob("*/observations.jsonl")):
                    events.extend(self._read_jsonl(p))

        history = self._read_jsonl(self.root / "data" / "memory" / "history.jsonl")
        for h in history:
            h["_source_file"] = "history"
        for e in events:
            e["_source_file"] = "observation"

        combined = []
        for e in events:
            if model_id and e.get("subject", {}).get("model_id") != model_id:
                continue
            combined.append({"ts": e.get("ts"), "kind": "observation", "data": e})
        for h in history:
            combined.append({"ts": h.get("ts"), "kind": "history", "data": h})

        combined.sort(key=lambda x: x.get("ts") or "")
        combined = combined[-max(1, limit) :]
        print(json.dumps(combined, ensure_ascii=False, indent=2))

    def diff(self, *, model_id: str, rule_id: str, rev_from: str, rev_to: str) -> None:
        base = self.root / "data" / "memory" / "revisions" / "profiles" / model_id / rule_id
        a = (base / f"{rev_from}.yaml").read_text(encoding="utf-8").splitlines(keepends=True)
        b = (base / f"{rev_to}.yaml").read_text(encoding="utf-8").splitlines(keepends=True)
        diff_lines = unified_diff(a, b, fromfile=rev_from, tofile=rev_to)
        print("".join(diff_lines))

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def _available_observation_ids(self) -> set[str]:
        ids: set[str] = set()
        for o in self._read_jsonl(self.root / "data" / "memory" / "observations.jsonl"):
            if isinstance(o.get("id"), str):
                ids.add(o["id"])
        runs_dir = self.root / "runs"
        if runs_dir.exists():
            for p in runs_dir.glob("*/observations.jsonl"):
                for o in self._read_jsonl(p):
                    if isinstance(o.get("id"), str):
                        ids.add(o["id"])
        return ids

    def _load_schema(self, name: str) -> dict[str, Any]:
        data = resources.files(__package__).joinpath("schemas", name).read_bytes()
        return json.loads(data.decode("utf-8"))

    def _validate(self, schema_name: str, instance: Any) -> None:
        schema = self._load_schema(schema_name)
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
        if errors:
            msg = "; ".join([e.message for e in errors[:3]])
            raise ValueError(f"Schema validation failed ({schema_name}): {msg}")

    def _append_history(self, record: dict[str, Any]) -> None:
        path = self.root / "data" / "memory" / "history.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _sha12(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

    def _write_with_revision(self, *, kind: str, model_id: str | None, key: str, path: Path, new_text: str) -> None:
        current_text = path.read_text(encoding="utf-8") if path.exists() else None
        new_rev = self._sha12(new_text)
        from_rev = self._sha12(current_text) if current_text is not None else None

        if current_text is not None and current_text == new_text:
            return

        if kind == "profiles" and model_id:
            rev_dir = self.root / "data" / "memory" / "revisions" / "profiles" / model_id / key
        else:
            rev_dir = self.root / "data" / "memory" / "revisions" / kind / key
        rev_dir.mkdir(parents=True, exist_ok=True)

        if current_text is not None:
            old_rev_path = rev_dir / f"{from_rev}.yaml"
            if not old_rev_path.exists():
                old_rev_path.write_text(current_text, encoding="utf-8")

        new_rev_path = rev_dir / f"{new_rev}.yaml"
        if not new_rev_path.exists():
            new_rev_path.write_text(new_text, encoding="utf-8")

        path.write_text(new_text, encoding="utf-8")
        self._append_history(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": f"{kind}_upsert",
                "model_id": model_id,
                "key": key,
                "path": str(path),
                "from_rev": from_rev,
                "to_rev": new_rev,
            }
        )

    def _load_rule(self, rule_path: str) -> dict[str, Any]:
        doc = yaml.safe_load((self.root / rule_path).read_text(encoding="utf-8"))
        rules = doc.get("rules") or []
        if not rules:
            return {}
        return rules[0]

    def _rebuild_index(self) -> None:
        profiles_root = self.root / "spec" / "memory" / "profiles"
        profiles: dict[str, list[dict[str, Any]]] = {}
        if profiles_root.exists():
            for model_dir in profiles_root.iterdir():
                if not model_dir.is_dir():
                    continue
                model_id = model_dir.name
                entries: list[dict[str, Any]] = []
                for file in model_dir.glob("*.yaml"):
                    doc = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
                    for rule in doc.get("rules") or []:
                        rule_id = rule.get("id") or file.stem
                        fw_range = rule.get("fw_range") or "*"
                        priority = int(rule.get("priority") or 0)
                        confidence = rule.get("confidence")
                        entries.append(
                            {
                                "rule_id": rule_id,
                                "fw_range": fw_range,
                                "priority": priority,
                                "confidence": confidence,
                                "specificity": specificity_score(fw_range),
                                "path": str(file.relative_to(self.root)),
                            }
                        )
                profiles[model_id] = entries

        index = {"schema_version": "0.1", "generated_at": datetime.now(timezone.utc).isoformat(), "profiles": profiles}
        path = self.root / "data" / "memory" / "index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_index(self, *, rebuild_if_missing: bool) -> dict[str, Any]:
        path = self.root / "data" / "memory" / "index.json"
        if not path.exists():
            if rebuild_if_missing:
                self._rebuild_index()
            else:
                return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _deep_merge(self, target: dict[str, Any], incoming: dict[str, Any]) -> None:
        for k, v in incoming.items():
            if isinstance(v, dict) and isinstance(target.get(k), dict):
                self._deep_merge(target[k], v)  # type: ignore[index]
            else:
                target[k] = v
