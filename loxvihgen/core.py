# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Sequence, Tuple

@dataclass(frozen=True)
class ObjKey:
    key: str

@dataclass(frozen=True)
class ArrIdx:
    key: str  # container/repeated child tag
    idx: int  # 0-based

PathToken = ObjKey | ArrIdx

class Path:
    def __init__(self, tokens: List[PathToken]):
        self.tokens = tokens

    def signature(self) -> Tuple[str, ...]:
        sig: List[str] = []
        for t in self.tokens:
            if isinstance(t, ArrIdx):
                if t.key != "$root":
                    sig.append(f"{t.key}[]")
            else:
                sig.append(t.key)
        return tuple(sig)

    def suffix_keys(self) -> List[str]:
        return [t.key for t in self.tokens if getattr(t, "key", None) and t.key != "$root"]

    def for_title(self, widths: dict[str,int], sep: str, prefix: str) -> str:
        parts: List[str] = []
        for t in self.tokens:
            if isinstance(t, ArrIdx):
                w = widths.get(t.key, 1)
                parts.append(f"{t.key}[{t.idx:0{w}d}]")
            else:
                parts.append(t.key)
        base = sep.join(parts)
        return (f"{prefix}{sep}{base}" if prefix and base else (prefix or base))
