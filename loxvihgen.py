#!/usr/bin/env python3
"""
# LoxVIHGen — Generate Loxone Virtual HTTP Input (VIH) templates from web‑service responses

## What it does
- Reads a **sample response** from your target endpoint.
- Accepts **JSON** or **XML** as input (auto‑detected).
- Walks the structure recursively and creates **one Loxone command per numeric leaf**.
- Builds **Loxone search strings** from the path (handles arrays / repeated elements) and assigns a **Unit/format**
  based on the decimals observed across the sample.

## File layout (per `project`)
- Response: `project.response.json` / `project.response.xml`
- Rules:    `project.rules.json` (overrides for units/format; suffix‑path matching)
- Manifest: `project.vih.json` (wiring & defaults; no overrides)
- Output:   `VI_project.xml` (or multi‑prefix: `VI_project--<prefix>.xml`)

## Subcommands (project‑centric)
```
loxvihgen fetch  PROJECT [-u URL]
loxvihgen rules  PROJECT [--force]
loxvihgen build  PROJECT [--title TITLE] [--prefix P ...] [--name-separator SEP] [--polling-time S] [--address-url URL] [--output OUT]
loxvihgen all    PROJECT -u URL
```
- Every command **creates/updates** `project.vih.json` if missing, storing what it learned (URL, paths, defaults).
- **No HTTP options** beyond `-u URL`. If your endpoint needs more, save the response yourself and use `rules/build`.
- `fetch` without `-u` uses the URL stored in the manifest.

## Typical workflow

1) **Grab a sample from your target web service** and save it as `weather.json`:
   ```bash
   curl 'https://api.openweathermap.org/data/3.0/onecall?units=metric&lang=en&lat=48&lon=14&appid=YOUR_KEY' \
     -o weather.json
   ```
   Or let LoxVIHGen fetch and remember the URL/manifests for you:
   ```bash
   loxvihgen all weather -u 'https://api.openweathermap.org/data/3.0/onecall?units=metric&lang=en&lat=48&lon=14&appid=YOUR_KEY'
   ```

2) **Generate a rules skeleton** from the response (one override per line):
   ```bash
   loxvihgen rules weather
   # writes: weather.rules.json
   ```

3) **Edit `weather.rules.json`** and fill units for the patterns you care about.
   - Patterns are **dot‑separated suffix paths**, e.g.:
     - `temp`, `temp.min`, `feels_like.min`
     - `hourly.wind_speed`
     - `daily[].temp.max` (indices ignored; `[]` is optional and cosmetic)
   - **Longest matching suffix wins**.
   - If a unit **starts with `<`** (e.g. `<v.2> °F`), it is treated as a **complete Loxone format string**.

4) **Build the Loxone XML** (uses response + rules + manifest defaults):
   ```bash
   loxvihgen build weather
   # creates: VI_weather.xml
   ```
   With dot‑separated names and a prefix:
   ```bash
   loxvihgen build weather --name-separator '.' --prefix plug1 --title 'Shelly'
   # creates: VI_weather--plug1.xml (command names start with 'plug1')
   ```
   Multiple prefixes:
   ```bash
   loxvihgen build weather --prefix plug1 --prefix plug2 --title 'Shelly'
   # creates: VI_weather--plug1.xml and VI_weather--plug2.xml
   ```

## Units & formatting
- **Decimals**: the tool computes `<v>` or `<v.N>` using the **maximum decimals** seen for the same path signature
  across arrays (e.g., `28.87` → `<v.2>` for all `hourly[].temp`).
- **Overrides** (in `project.rules.json`): appended as `" <UNIT>"` unless they start with `<`, in which case the full
  string is used verbatim.

"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__tool__ = "LoxVIHGen"
__version__ = "2.2.0"

# ===================== Data model =====================

@dataclass(frozen=True)
class ObjKey:
    key: str

@dataclass(frozen=True)
class ArrIdx:
    key: str   # container name (JSON: list key; XML: repeated child tag)
    idx: int   # 0-based

PathToken = ObjKey | ArrIdx

# ===================== Helpers =====================

def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _try_parse_number(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    t = s.strip()
    if not t:
        return None
    try:
        return float(t.replace(",", "."))
    except Exception:
        return None


def _count_decimals(val: float) -> int:
    s = str(val)
    if "e" in s or "E" in s:
        s = format(val, ".12f").rstrip("0").rstrip(".")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def _xml_escape_attr(s: str) -> str:
    return html_escape(s, quote=True)

# ===================== Abstract hierarchical source (business layer) =====================

class HierSource(ABC):
    """Structure-only view. No Loxone-specific logic here (SRP)."""

    @abstractmethod
    def iter_numeric_leaves(self) -> Iterable[Tuple[List[PathToken], float, int]]:
        """Yield (path_tokens, value, decimals). Order follows input."""

    @abstractmethod
    def index_widths(self) -> Dict[str, int]:
        """Zero-padded width per array container key (for titles)."""

# --------------------- JSON ---------------------

class JSONSource(HierSource):
    def __init__(self, root: Any):
        self.root = root
        self._widths = self._calc_widths(root)

    @staticmethod
    def sniff_and_make(text: str) -> "JSONSource":
        return JSONSource(json.loads(text))

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

    def iter_numeric_leaves(self) -> Iterable[Tuple[List[PathToken], float, int]]:
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
                if _is_number(n):
                    fv = float(n)
                    yield (pref, fv, _count_decimals(fv))
        yield from walk(self.root, [])

    def index_widths(self) -> Dict[str, int]:
        return dict(self._widths)

# --------------------- XML ---------------------

class XMLSource(HierSource):
    def __init__(self, root: ET.Element):
        self.root = root
        self._widths = self._calc_widths(root)

    @staticmethod
    def sniff_and_make(text: str) -> "XMLSource":
        return XMLSource(ET.fromstring(text))

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

    def iter_numeric_leaves(self) -> Iterable[Tuple[List[PathToken], float, int]]:
        def walk(e: ET.Element, pref: List[PathToken]):
            children = list(e)
            if not children:
                num = _try_parse_number(e.text)
                if num is not None:
                    yield (pref + [ObjKey(e.tag)], num, _count_decimals(num))
                return
            groups: Dict[str, List[ET.Element]] = {}
            for ch in children:
                groups.setdefault(ch.tag, []).append(ch)
            for tag, group in groups.items():
                if len(group) == 1:
                    yield from walk(group[0], pref + [ObjKey(tag)])
                else:
                    for i, ch in enumerate(group):
                        # Store the repeated CHILD tag as ArrIdx (not the parent)
                        yield from walk(ch, pref + [ArrIdx(tag, i)])
        yield from walk(self.root, [])

    def index_widths(self) -> Dict[str, int]:
        return dict(self._widths)

# ===================== Rules engine (business layer) =====================

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
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
                overrides = obj.get("overrides", []) if isinstance(obj, dict) else []
                for i, it in enumerate(overrides):
                    if isinstance(it, dict) and isinstance(it.get("pattern"), str) and isinstance(it.get("unit"), str):
                        toks = [tok for tok in it["pattern"].replace("[]", "").split(".") if tok]
                        if toks:
                            rules.append(UnitRule(pattern=it["pattern"], tokens=toks, unit=it["unit"], order=i))
            except Exception as e:
                print(f"Warning: cannot read rules file: {e}", file=sys.stderr)
        return Rules(rules)

    def match_unit(self, path: Sequence[PathToken]) -> Optional[Tuple[str, bool]]:
        reduced: List[str] = [t.key for t in path if getattr(t, "key", None) and t.key != "$root"]
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

# ===================== Builders (business layer) =====================

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

    def title_for(self, path: Sequence[PathToken]) -> str:
        parts: List[str] = []
        for t in path:
            if isinstance(t, ArrIdx):
                w = self.width.get(t.key, 1)
                parts.append(f"{t.key}[{t.idx:0{w}d}]")
            elif isinstance(t, ObjKey):
                parts.append(t.key)
        base = self.sep.join(parts)
        return (f"{self.prefix}{self.sep}{base}" if self.prefix and base else (self.prefix or base))

class CheckStringBuilder(ABC):
    @abstractmethod
    def build(self, path: Sequence[PathToken]) -> str: ...

class JSONCheckStringBuilder(CheckStringBuilder):
    def build(self, path: Sequence[PathToken]) -> str:
        parts: List[str] = []
        i = "\i"
        for t in path:
            if isinstance(t, ObjKey):
                parts.append(f"{i}&quot;{_xml_escape_attr(t.key)}&quot;:{i}")
            elif isinstance(t, ArrIdx):
                if t.key == "$root":
                    parts.append("\i[" + i)
                else:
                    parts.append(f"{i}&quot;{_xml_escape_attr(t.key)}&quot;:[{i}")
                parts.append("\i{\i" * (t.idx + 1))
        parts.append("\v")
        return "".join(parts)

class XMLCheckStringBuilder(CheckStringBuilder):
    def build(self, path: Sequence[PathToken]) -> str:
        parts: List[str] = []
        i = "\i"
        for t in path:
            if isinstance(t, ObjKey):
                parts.append(f"{i}&lt;{_xml_escape_attr(t.key)}&gt;{i}")
            elif isinstance(t, ArrIdx):
                parts.append((f"{i}&lt;{_xml_escape_attr(t.key)}&gt;{i}") * (t.idx + 1))
        parts.append("\v")
        return "".join(parts)

class VIHBuilder:
    def __init__(self, source: HierSource, title_builder: TitleBuilder, rules: Rules, check_builder: CheckStringBuilder):
        self.source = source
        self.title_builder = title_builder
        self.rules = rules
        self.check_builder = check_builder

    @staticmethod
    def path_signature(tokens: Sequence[PathToken]) -> Tuple[str, ...]:
        sig: List[str] = []
        for t in tokens:
            if isinstance(t, ArrIdx):
                if t.key != "$root":
                    sig.append(f"{t.key}[]")
            elif isinstance(t, ObjKey):
                sig.append(t.key)
        return tuple(sig)

    def format_string_for(self, path: Sequence[PathToken], decimals_by_sig: Dict[Tuple[str, ...], int]) -> str:
        u = self.rules.match_unit(path)
        if u and u[1]:
            return u[0]
        d = max(0, decimals_by_sig.get(self.path_signature(path), 0))
        base = "<v>" if d == 0 else f"<v.{d}>"
        if u and not u[1]:
            return f"{base} {u[0]}"
        return base

    def build_commands(self) -> List[Command]:
        width = self.source.index_widths()
        leaves = list(self.source.iter_numeric_leaves())
        # compute decimals per signature
        decs: Dict[Tuple[str, ...], int] = {}
        for p, _v, d in leaves:
            sig = self.path_signature(p)
            decs[sig] = max(decs.get(sig, 0), d)
        # build
        out: List[Command] = []
        for p, _v, _d in leaves:
            title = self.title_builder.title_for(p)
            check = self.check_builder.build(p)
            unit = self.format_string_for(p, decs)
            out.append(Command(title=title, check=check, unit=unit))
        return out

# ===================== Rules skeleton generator =====================

def generate_rules_skeleton(source: HierSource) -> str:
    pats: List[str] = []
    seen: set[str] = set()
    for path, _val, _dec in source.iter_numeric_leaves():
        toks = [t.key for t in path if getattr(t, "key", None) and t.key != "$root"]
        pat = ".".join(toks)
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
    return "\n".join(lines)

# ===================== XML rendering (business → output) =====================

def render_xml(commands: List[Command], title: str, address_url: str, polling_time: int,
               miniserver_min_version: str, full_comment_json: str) -> str:
    title_attr = _xml_escape_attr(title)
    addr_attr = _xml_escape_attr(address_url)
    comment_attr = _xml_escape_attr(full_comment_json) if full_comment_json else ""
    out: List[str] = []
    if full_comment_json:
        out.append(f"<!-- {full_comment_json} -->")
    out.append(f"<VirtualInHttp Title=\"{title_attr}\" Comment=\"{comment_attr}\" Address=\"{addr_attr}\" HintText=\"\" PollingTime=\"{polling_time}\">")
    out.append(f"	<Info templateType=\"2\" minVersion=\"{miniserver_min_version}\"/>")
    for c in commands:
        out.append(
            "	<VirtualInHttpCmd "
            f"Title=\"{_xml_escape_attr(c.title)}\" "
            f"Unit=\"{_xml_escape_attr(c.unit)}\" "
            f"Check=\"{c.check}\" "
            f"Signed=\"true\" Analog=\"true\" "
            f"SourceValLow=\"0\" DestValLow=\"0\" "
            f"SourceValHigh=\"100\" DestValHigh=\"100\" "
            f"Comment=\"\"/>"
        )
    out.append("</VirtualInHttp>")
    body = "\n".join(out) + "\n"
    return f'<?xml version="1.0" encoding="utf-8"?>{body}'

# ===================== Metadata (business) =====================

def build_full_metadata(input_path: Optional[Path],
                        output_path: Optional[Path],
                        rules_path: Optional[Path],
                        opts: Dict[str, Any]) -> str:
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = []
    if input_path:
        files.append({"role":"input","name":str(input_path)})
    if rules_path:
        files.append({"role":"rules","name":str(rules_path)})
    if output_path:
        files.append({"role":"output","name":str(output_path)})
    meta = {
        "tool": __tool__,
        "version": __version__,
        "utc": utc,
        "files": files,
        "opts": opts
    }
    return json.dumps(meta, separators=(",",":"))

# ===================== Service layer: manifest & file helpers =====================

def manifest_path(project: str) -> Path:
    return Path(f"{project}.vih.json")


def response_guess_path(project: str) -> Optional[Path]:
    cand_json = Path(f"{project}.response.json")
    cand_xml  = Path(f"{project}.response.xml")
    if cand_json.exists():
        return cand_json
    if cand_xml.exists():
        return cand_xml
    return None


def rules_default_path(project: str) -> Path:
    return Path(f"{project}.rules.json")


def output_default_path(project: str, prefix: Optional[str]) -> Path:
    if prefix:
        return Path(f"VI_{project}--{prefix}.xml")
    return Path(f"VI_{project}.xml")


def load_manifest(project: str) -> Dict[str, Any]:
    p = manifest_path(project)
    if not p.exists():
        return {
            "project": project,
            "source": {"url": None, "response": None},
            "rules": str(rules_default_path(project)),
            "build": {
                "title": project,
                "name_separator": " ",
                "polling_time": 1200,
                "address_url": None
            },
            "prefixes": []
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {
            "project": project,
            "source": {"url": None, "response": None},
            "rules": str(rules_default_path(project)),
            "build": {"title": project, "name_separator": " ", "polling_time": 1200, "address_url": None},
            "prefixes": []
        }


def save_manifest(project: str, data: Dict[str, Any]) -> None:
    manifest_path(project).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ===================== Format sniffing & source factory =====================

def sniff_format(text: str) -> str:
    s = text.lstrip()
    if s.startswith("<"):
        return "xml"
    if s.startswith("{") or s.startswith("["):
        return "json"
    try:
        json.loads(text)
        return "json"
    except Exception:
        try:
            ET.fromstring(text)
            return "xml"
        except Exception:
            raise ValueError("Input is neither valid JSON nor XML")


def make_source(text: str) -> Tuple[HierSource, CheckStringBuilder]:
    fmt = sniff_format(text)
    if fmt == "json":
        return JSONSource.sniff_and_make(text), JSONCheckStringBuilder()
    else:
        return XMLSource.sniff_and_make(text), XMLCheckStringBuilder()

# ===================== Subcommand impls (service layer) =====================

def cmd_fetch(project: str, url: Optional[str]) -> int:
    # Resolve URL: CLI or manifest
    if not url:
        m0 = load_manifest(project)
        url = m0.get("source", {}).get("url")
        if not url:
            print("Error: no URL provided and none stored in manifest.", file=sys.stderr)
            return 2
    # Fetch plain GET
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read()
            encoding = resp.headers.get_content_charset() or "utf-8"
            text = raw.decode(encoding, errors="replace")
            ctype = resp.headers.get_content_type() or ""
    except Exception as e:
        print(f"Error: fetch failed: {e}", file=sys.stderr)
        return 4
    fmt = "json" if "json" in ctype.lower() else ("xml" if "xml" in ctype.lower() else sniff_format(text))
    resp_path = Path(f"{project}.response.{fmt}")
    resp_path.write_text(text, encoding="utf-8")

    # Update manifest
    m = load_manifest(project)
    m.setdefault("project", project)
    m.setdefault("source", {})
    m["source"]["url"] = url
    m["source"]["response"] = str(resp_path)
    m.setdefault("rules", str(rules_default_path(project)))
    m.setdefault("build", {})
    m["build"].setdefault("title", project)
    m["build"].setdefault("name_separator", " ")
    m["build"].setdefault("polling_time", 1200)
    m["build"].setdefault("address_url", url)
    m.setdefault("prefixes", [])
    save_manifest(project, m)
    print(f"OK: wrote {resp_path} and updated {manifest_path(project)}")
    return 0


def cmd_rules(project: str, force: bool) -> int:
    # Determine response
    m = load_manifest(project)
    resp_path = Path(m.get("source", {}).get("response") or "")
    if not resp_path or not resp_path.exists():
        guess = response_guess_path(project)
        if guess is None:
            print(f"Error: response missing. Expected {project}.response.json or {project}.response.xml", file=sys.stderr)
            return 6
        resp_path = guess
    text = resp_path.read_text(encoding="utf-8")

    # Build skeleton
    source, _ = make_source(text)
    content = generate_rules_skeleton(source)

    rules_path = Path(f"{project}.rules.json")
    if rules_path.exists() and not force:
        print(f"Info: {rules_path} exists. Use --force to overwrite.")
    else:
        rules_path.write_text(content, encoding="utf-8")
        print(f"OK: rules written → {rules_path}")

    # Update manifest (do not overwrite existing)
    m.setdefault("rules", str(rules_path))
    m.setdefault("build", {})
    m["build"].setdefault("title", project)
    m["build"].setdefault("name_separator", " ")
    m["build"].setdefault("polling_time", 1200)
    if m["build"].get("address_url") is None and m.get("source", {}).get("url"):
        m["build"]["address_url"] = m["source"]["url"]
    save_manifest(project, m)
    return 0


def cmd_build(project: str, title: Optional[str], prefixes: List[str], sep: Optional[str], poll: Optional[int], address_url: Optional[str], output: Optional[Path]) -> int:
    m = load_manifest(project)
    # Resolve response
    resp_path = Path(m.get("source", {}).get("response") or "")
    if not resp_path.exists():
        guess = response_guess_path(project)
        if guess is None:
            print(f"Error: response missing. Expected {project}.response.json or {project}.response.xml", file=sys.stderr)
            return 6
        resp_path = guess
    text = resp_path.read_text(encoding="utf-8")

    source, check_builder = make_source(text)

    # Resolve rules
    rules_path = Path(m.get("rules") or str(rules_default_path(project)))
    rules = Rules.load(rules_path if rules_path.exists() else None)

    # Effective build options (CLI overrides manifest defaults)
    b = m.get("build", {})
    eff_title = title or b.get("title") or project
    eff_sep = sep if sep is not None else b.get("name_separator", " ")
    eff_poll = int(poll if poll is not None else b.get("polling_time", 1200))
    eff_addr = address_url or b.get("address_url") or m.get("source", {}).get("url") or "http://..."

    # Prefix set (CLI takes precedence if provided)
    prefix_list: List[str] = prefixes if prefixes else list(m.get("prefixes", []))
    if not prefix_list:
        prefix_list = [""]  # single build without prefix

    # Build per prefix
    for pref in prefix_list:
        tb = TitleBuilder(sep=eff_sep, prefix=(pref or ""), width_by_key=source.index_widths())
        vih = VIHBuilder(source, tb, rules, check_builder)
        cmds = vih.build_commands()

        # Title: include prefix if present
        full_title = f"{pref} {eff_title}".strip() if pref else eff_title

        # Output path rules
        if output is not None and len(prefix_list) == 1:
            out_path = output
        elif output is not None and len(prefix_list) > 1:
            print("Error: --output cannot be a single file when multiple prefixes are used.", file=sys.stderr)
            return 2
        else:
            out_path = output_default_path(project, pref or None)

        meta_json = build_full_metadata(resp_path, out_path, rules_path if rules_path.exists() else None, {
            "prefix": pref or "",
            "sep": eff_sep,
            "title": full_title,
            "poll": eff_poll,
            "address_url": eff_addr
        })

        xml_content = render_xml(cmds, title=full_title, address_url=eff_addr, polling_time=eff_poll,
                                 miniserver_min_version="16000610", full_comment_json=meta_json)
        out_path.write_text(xml_content, encoding="utf-8")
        print(f"OK: {len(cmds)} commands → {out_path}")

    # Patch manifest with defaults if missing (do not override existing)
    m.setdefault("build", {})
    if "title" not in m["build"]:
        m["build"]["title"] = eff_title
    if "name_separator" not in m["build"]:
        m["build"]["name_separator"] = eff_sep
    if "polling_time" not in m["build"]:
        m["build"]["polling_time"] = eff_poll
    if m["build"].get("address_url") is None and eff_addr:
        m["build"]["address_url"] = eff_addr
    save_manifest(project, m)
    return 0


def cmd_all(project: str, url: str) -> int:
    e = cmd_fetch(project, url)
    if e != 0:
        return e
    # Only create rules if missing
    rules_p = rules_default_path(project)
    if not rules_p.exists():
        e = cmd_rules(project, force=False)
        if e != 0:
            return e
    return cmd_build(project, title=None, prefixes=[], sep=None, poll=None, address_url=None, output=None)

# ===================== CLI (service layer) =====================

def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="loxvihgen", description="Generate Loxone VI-HTTP XML from JSON/XML responses (project-centric)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="Fetch response for project and update manifest")
    pf.add_argument("project")
    pf.add_argument("-u", "--url", required=False, help="HTTP(S) URL to fetch via GET (optional if manifest has one)")

    pr = sub.add_parser("rules", help="Generate rules skeleton from project's response")
    pr.add_argument("project")
    pr.add_argument("--force", action="store_true", help="Overwrite existing project.rules.json")

    pb = sub.add_parser("build", help="Build VI XML from project's response (+rules)")
    pb.add_argument("project")
    pb.add_argument("--title")
    pb.add_argument("--prefix", action="append", default=[], help="Prefix for command titles (repeatable)")
    pb.add_argument("--name-separator", dest="sep", default=None, help="Separator between path elements in command titles")
    pb.add_argument("--polling-time", dest="poll", type=int, default=None, help="Polling interval in seconds")
    pb.add_argument("--address-url", default=None, help="Service URL stored in XML")
    pb.add_argument("--output", type=Path, default=None, help="Output XML path (single-prefix only)")

    pa = sub.add_parser("all", help="Fetch → rules (if missing) → build")
    pa.add_argument("project")
    pa.add_argument("-u", "--url", required=True)

    args = p.parse_args(argv)

    if args.cmd == "fetch":
        return cmd_fetch(args.project, args.url)
    if args.cmd == "rules":
        return cmd_rules(args.project, args.force)
    if args.cmd == "build":
        return cmd_build(args.project, args.title, args.prefix, args.sep, args.poll, args.address_url, args.output)
    if args.cmd == "all":
        return cmd_all(args.project, args.url)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
