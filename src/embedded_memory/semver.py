from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int

    @staticmethod
    def parse(text: str) -> "SemVer":
        text = text.strip()
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
        if m:
            return SemVer(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = re.search(r"(\d+)\.(\d+)", text)
        if m:
            return SemVer(int(m.group(1)), int(m.group(2)), 0)
        m = re.search(r"(\d+)", text)
        if m:
            return SemVer(int(m.group(1)), 0, 0)
        raise ValueError(f"Invalid version: {text!r}")


def _parse_fw_range(expr: str) -> tuple[str, object]:
    expr = expr.strip()
    if "*" in expr:
        parts = expr.split(".")
        fixed = []
        for part in parts:
            if part == "*":
                break
            fixed.append(int(re.sub(r"\D", "", part)))
        return ("wildcard", tuple(fixed))

    tokens = expr.split()
    constraints: list[tuple[str, SemVer]] = []
    for token in tokens:
        m = re.match(r"(<=|>=|<|>)(.+)", token)
        if not m:
            continue
        op = m.group(1)
        ver = SemVer.parse(m.group(2))
        constraints.append((op, ver))
    if constraints:
        return ("range", constraints)

    return ("exact", SemVer.parse(expr))


def specificity_score(expr: str) -> int:
    kind, payload = _parse_fw_range(expr)
    if kind == "exact":
        return 30
    if kind == "range":
        return 20 + len(payload)  # type: ignore[arg-type]
    if kind == "wildcard":
        return 10 + len(payload)  # type: ignore[arg-type]
    return 0


def matches(version: str, fw_range: str) -> bool:
    v = SemVer.parse(version)
    kind, payload = _parse_fw_range(fw_range)

    if kind == "exact":
        return v == payload  # type: ignore[return-value]

    if kind == "wildcard":
        fixed = payload  # type: ignore[assignment]
        if len(fixed) >= 1 and v.major != fixed[0]:
            return False
        if len(fixed) >= 2 and v.minor != fixed[1]:
            return False
        if len(fixed) >= 3 and v.patch != fixed[2]:
            return False
        return True

    if kind == "range":
        constraints = payload  # type: ignore[assignment]
        for op, target in constraints:
            if op == ">=" and not (v >= target):
                return False
            if op == "<=" and not (v <= target):
                return False
            if op == ">" and not (v > target):
                return False
            if op == "<" and not (v < target):
                return False
        return True

    return False

