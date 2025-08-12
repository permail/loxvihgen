# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from .core import PathToken

@dataclass
class UnitRule:
    pattern: str
    tokens: List[str]
    unit: str
    order: int

class Rules:
    def __init__(self, rules: List[UnitRule]):
        self.rules = rules

    @staticmethod
    def load(path: Optional[Path]) -> "Rules":
        rules: List[UnitRule] = []
        if path and path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            overrides = obj.get("overrides", []) if isinstance(obj, dict) else []
            for i, it in enumerate(overrides):
                if isinstance(it, dict) and isinstance(it.get("pattern"), str) and isinstance(it.get("unit"), str):
                    toks = [tok for tok in it["pattern"].replace("[]", "").split(".") if tok]
                    if toks:
                        rules.append(UnitRule(pattern=it["pattern"], tokens=toks, unit=it["unit"], order=i))
        return Rules(rules)

    def match_unit(self, path_tokens: Sequence[PathToken]) -> Optional[Tuple[str, bool]]:
        reduced = [t.key for t in path_tokens if getattr(t, "key", None) and t.key != "$root"]
        best: Tuple[int, int, UnitRule] | None = None
        for r in self.rules:
            m = len(r.tokens)
            if m == 0 or m > len(reduced):
                continue
            if reduced[-m:] == r.tokens:
                cand = (m, -r.order, r)
                if best is None or cand > best:
                    best = cand
        if not best:
            return None
        rule = best[2]
        if rule.unit.lstrip().startswith("<"):
            return (rule.unit, True)
        return (rule.unit, False)

def generate_rules_skeleton(source) -> str:
    pats: List[str] = []
    seen: set[str] = set()
    for p, _v, _d in source.iter_numeric_leaves():
        pat = ".".join([t.key for t in p.tokens if getattr(t, "key", None) and t.key != "$root"])
        if pat not in seen:
            seen.add(pat)
            pats.append(pat)
    pats.sort()
    lines = ["{", "  \"overrides\": ["]
    for i, p in enumerate(pats):
        comma = "," if i < len(pats) - 1 else ""
        lines.append(f'    {{"pattern":"{p}","unit":""}}{comma}')
    lines.append("  ]")
    lines.append("}")
    return "/n".join(lines)
