# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from .core import ObjKey, ArrIdx, Path, PathToken

NumberLeaf = Tuple[Path, float, int]  # (path, value, decimals)

class HierSource:
    """Structure-only view. No Loxone-specific logic here."""
    def iter_numeric_leaves(self) -> Iterable[NumberLeaf]:
        raise NotImplementedError
    def index_widths(self) -> Dict[str, int]:
        raise NotImplementedError

class JSONSource(HierSource):
    def __init__(self, root: Any):
        self.root = root
        self._widths = self._calc_widths(root)

    @staticmethod
    def sniff_and_make(text: str) -> "JSONSource":
        return JSONSource(json.loads(text))

    @staticmethod
    def _is_number(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    @staticmethod
    def _count_decimals(val: float) -> int:
        s = str(val)
        if "e" in s or "E" in s:
            s = format(val, ".12f").rstrip("0").rstrip(".")
        return len(s.split(".")[1]) if "." in s else 0

    @staticmethod
    def _calc_widths(node: Any) -> Dict[str, int]:
        lengths: Dict[str, int] = {}
        def walk(n: Any) -> None:
            if isinstance(n, dict):
                for k, v in n.items():
                    if isinstance(v, list):
                        lengths[k] = max(lengths.get(k, 0), len(v))
                        for it in v:
                            walk(it)
                    else:
                        walk(v)
            elif isinstance(n, list):
                for it in n:
                    walk(it)
        walk(node)
        return {k: max(1, len(str(max(0, ln - 1)))) for k, ln in lengths.items()}

    def iter_numeric_leaves(self) -> Iterable[NumberLeaf]:
        def walk(n: Any, pref: List[PathToken]):
            if isinstance(n, dict):
                for k, v in n.items():
                    if isinstance(v, list):
                        for i, it in enumerate(v):
                            yield from walk(it, pref + [ArrIdx(k, i)])
                    else:
                        yield from walk(v, pref + [ObjKey(k)])
            elif isinstance(n, list):
                for i, v in enumerate(n):
                    yield from walk(v, pref + [ArrIdx("$root", i)])
            else:
                if JSONSource._is_number(n):
                    # ``_count_decimals`` expects the original representation to
                    # determine the number of fractional digits.  Converting an
                    # integer to ``float`` first would always introduce a ".0"
                    # and therefore report one decimal place for integers.
                    fv = float(n)
                    yield (Path(pref.copy()), fv, JSONSource._count_decimals(n))
        yield from walk(self.root, [])

    def index_widths(self) -> Dict[str, int]:
        return dict(self._widths)

class XMLSource(HierSource):
    def __init__(self, root: ET.Element):
        self.root = root
        self._widths = self._calc_widths(root)

    @staticmethod
    def sniff_and_make(text: str) -> "XMLSource":
        return XMLSource(ET.fromstring(text))

    @staticmethod
    def _try_parse_number(s: Optional[str]) -> Optional[float]:
        if s is None: return None
        t = s.strip()
        if not t: return None
        try:
            return float(t.replace(",", "."))
        except Exception:
            return None

    @staticmethod
    def _count_decimals(val: float) -> int:
        s = str(val)
        if "e" in s or "E" in s:
            s = format(val, ".12f").rstrip("0").rstrip(".")
        return len(s.split(".")[1]) if "." in s else 0

    @staticmethod
    def _calc_widths(elem: ET.Element) -> Dict[str, int]:
        lengths: Dict[str, int] = {}
        def walk(e: ET.Element):
            children = list(e)
            tags: Dict[str, int] = {}
            for ch in children:
                tags[ch.tag] = tags.get(ch.tag, 0) + 1
            for tag, cnt in tags.items():
                if cnt > 1:
                    lengths[tag] = max(lengths.get(tag, 0), cnt)
            for ch in children:
                walk(ch)
        walk(elem)
        return {k: max(1, len(str(max(0, ln - 1)))) for k, ln in lengths.items()}

    def iter_numeric_leaves(self) -> Iterable[NumberLeaf]:
        def walk(e: ET.Element, pref: List[PathToken]):
            children = list(e)
            if not children:
                num = XMLSource._try_parse_number(e.text)
                if num is not None:
                    yield (Path(pref + [ObjKey(e.tag)]), num, XMLSource._count_decimals(num))
                return
            groups: Dict[str, List[ET.Element]] = {}
            for ch in children:
                groups.setdefault(ch.tag, []).append(ch)
            for tag, group in groups.items():
                if len(group) == 1:
                    yield from walk(group[0], pref + [ObjKey(tag)])
                else:
                    for i, ch in enumerate(group):
                        yield from walk(ch, pref + [ArrIdx(tag, i)])
        yield from walk(self.root, [])

    def index_widths(self) -> Dict[str, int]:
        return dict(self._widths)

class FormatAdapter:
    def __init__(self, source: HierSource, kind: str):
        self.source = source
        self.kind = kind  # "json"|"xml"

    @staticmethod
    def sniff(text: str) -> "FormatAdapter":
        s = text.lstrip()
        if s.startswith("<"):
            return FormatAdapter(XMLSource.sniff_and_make(text), "xml")
        if s.startswith("{") or s.startswith("["):
            return FormatAdapter(JSONSource.sniff_and_make(text), "json")
        # try both
        try:
            return FormatAdapter(JSONSource.sniff_and_make(text), "json")
        except Exception:
            return FormatAdapter(XMLSource.sniff_and_make(text), "xml")
