# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple
from .core import Path, PathToken, ObjKey, ArrIdx
from .rules import Rules

@dataclass
class Command:
    title: str
    check: str
    unit: str

class TitleBuilder:
    def __init__(self, sep: str, prefix: str, width_by_key: Dict[str, int]):
        self.sep = sep
        self.prefix = prefix
        self.width = width_by_key

    def for_path(self, path: Path) -> str:
        parts: List[str] = []
        for t in path.tokens:
            if isinstance(t, ArrIdx):
                w = self.width.get(t.key, 1)
                parts.append(f"{t.key}[{t.idx:0{w}d}]")
            else:
                parts.append(t.key)
        base = self.sep.join(parts)
        return (f"{self.prefix}{self.sep}{base}" if self.prefix and base else (self.prefix or base))

class CheckStringBuilder:
    def build(self, path: Path) -> str:
        raise NotImplementedError

class JSONCheckStringBuilder(CheckStringBuilder):
    def build(self, path: Path) -> str:
        parts: List[str] = []
        i = "\\i"
        for t in path.tokens:
            if isinstance(t, ObjKey):
                parts.append(f"{i}&quot;{t.key}&quot;:{i}")
            elif isinstance(t, ArrIdx):
                if t.key == "$root":
                    parts.append("\\i[" + i)
                else:
                    parts.append(f"{i}&quot;{t.key}&quot;:[{i}")
                parts.append("\\i{\\i" * (t.idx + 1))
        parts.append("\\v")
        return "".join(parts)

class XMLCheckStringBuilder(CheckStringBuilder):
    def build(self, path: Path) -> str:
        parts: List[str] = []
        i = "\\i"
        for t in path.tokens:
            if isinstance(t, ObjKey):
                parts.append(f"{i}&lt;{t.key}&gt;{i}")
            elif isinstance(t, ArrIdx):
                parts.append((f"{i}&lt;{t.key}&gt;{i}") * (t.idx + 1))
        parts.append("\\v")
        return "".join(parts)

class VIHBuilder:
    def __init__(self, source, title_builder: TitleBuilder, rules: Rules, check_builder: CheckStringBuilder):
        self.source = source
        self.title_builder = title_builder
        self.rules = rules
        self.check_builder = check_builder

    @staticmethod
    def _signature(tokens: Sequence[PathToken]) -> Tuple[str, ...]:
        sig: List[str] = []
        for t in tokens:
            if isinstance(t, ArrIdx):
                if t.key != "$root":
                    sig.append(f"{t.key}[]")
            else:
                sig.append(t.key)
        return tuple(sig)

    def _format_for(self, tokens: Sequence[PathToken], decimals_by_sig: Dict[Tuple[str, ...], int]) -> str:
        u = self.rules.match_unit(tokens)
        if u and u[1]:
            return u[0]
        sig = VIHBuilder._signature(tokens)
        d = max(0, decimals_by_sig.get(sig, 0))
        base = "<v>" if d == 0 else f"<v.{d}>"
        if u and not u[1]:
            return f"{base} {u[0]}"
        return base

    def build_commands(self) -> List[Command]:
        widths = self.source.index_widths()
        leaves = list(self.source.iter_numeric_leaves())
        # aggregate decimals per signature across arrays
        decs: Dict[Tuple[str, ...], int] = {}
        for p, _v, d in leaves:
            sig = VIHBuilder._signature(p.tokens)
            decs[sig] = max(decs.get(sig, 0), d)
        out: List[Command] = []
        for p, _v, _d in leaves:
            title = self.title_builder.for_path(p)
            check = self.check_builder.build(p)
            unit = self._format_for(p.tokens, decs)
            out.append(Command(title=title, check=check, unit=unit))
        return out
