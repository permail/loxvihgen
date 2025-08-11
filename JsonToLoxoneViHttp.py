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
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__tool__ = "LoxVIHGen"
__version__ = "2.0.1"

# ===================== Data model =====================

@dataclass(frozen=True)
class ObjKey:
    key: str

@dataclass(frozen=True)
class ArrIdx:
    key: str   # array/container name (JSON: list key; XML: parent tag for repeated children)
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


def _collect_array_lengths_json(node: Any, arr_len: Dict[str, int]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list):
                arr_len[k] = max(arr_len.get(k, 0), len(v))
                for item in v:
                    _collect_array_lengths_json(item, arr_len)
            else:
                _collect_array_lengths_json(v, arr_len)
    elif isinstance(node, list):
        for item in node:
            _collect_array_lengths_json(item, arr_len)


def _collect_array_lengths_xml(elem: ET.Element, arr_len: Dict[str, int]) -> None:
    by_tag: Dict[str, int] = {}
    children = list(elem)
    for ch in children:
        by_tag[ch.tag] = by_tag.get(ch.tag, 0) + 1
    max_repeats = max(by_tag.values()) if by_tag else 0
    if max_repeats > 1:
        arr_len[elem.tag] = max(arr_len.get(elem.tag, 0), max_repeats)
    for ch in children:
        _collect_array_lengths_xml(ch, arr_len)


def _walk_numeric_leaves_json(node: Any, prefix: List[PathToken]) -> Iterable[Tuple[List[PathToken], float, int]]:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list):
                for i, item in enumerate(v):
                    yield from _walk_numeric_leaves_json(item, prefix + [ArrIdx(k, i)])
            else:
                yield from _walk_numeric_leaves_json(v, prefix + [ObjKey(k)])
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_numeric_leaves_json(v, prefix + [ArrIdx("$root", i)])
    else:
        if _is_number(node):
            fv = float(node)
            yield (prefix, fv, _count_decimals(fv))


def _walk_numeric_leaves_xml(elem: ET.Element, prefix: List[PathToken]) -> Iterable[Tuple[List[PathToken], float, int]]:
    children = list(elem)
    if not children:
        num = _try_parse_number(elem.text)
        if num is not None:
            yield (prefix + [ObjKey(elem.tag)], num, _count_decimals(num))
        return
    groups: Dict[str, List[ET.Element]] = {}
    for ch in children:
        groups.setdefault(ch.tag, []).append(ch)
    for tag, group in groups.items():
        if len(group) == 1:
            ch = group[0]
            yield from _walk_numeric_leaves_xml(ch, prefix + [ObjKey(tag)])
        else:
            for i, ch in enumerate(group):
                yield from _walk_numeric_leaves_xml(ch, prefix + [ArrIdx(elem.tag, i)])


def _index_width_map(arr_len: Dict[str, int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for k, n in arr_len.items():
        out[k] = max(1, len(str(max(0, n - 1))))
    return out


def _xml_escape_attr(s: str) -> str:
    return html_escape(s, quote=True)


def _quoted_key(k: str) -> str:
    return f"&quot;{_xml_escape_attr(k)}&quot;"


def _tag_token(tag: str) -> str:
    return f"&lt;{_xml_escape_attr(tag)}&gt;"

# ===================== Check string builders =====================

def build_check_string_json(path: Sequence[PathToken]) -> str:
    parts: List[str] = []
    i_quote = "\i"
    for t in path:
        if isinstance(t, ObjKey):
            parts.append(f"{i_quote}{_quoted_key(t.key)}:{i_quote}")
        elif isinstance(t, ArrIdx):
            parts.append(f"{i_quote}{_quoted_key(t.key)}:[{i_quote}")
            parts.append("\i{\i" * (t.idx + 1))
        else:
            raise TypeError("unknown token")
    parts.append("\v")
    return "".join(parts)


def build_check_string_xml(path: Sequence[PathToken]) -> str:
    parts: List[str] = []
    i_quote = "\i"
    for t in path:
        if isinstance(t, ObjKey):
            parts.append(f"{i_quote}{_tag_token(t.key)}{i_quote}")
        elif isinstance(t, ArrIdx):
            parts.append((f"{i_quote}{_tag_token(t.key)}{i_quote}") * (t.idx + 1))
        else:
            raise TypeError("unknown token")
    parts.append("\v")
    return "".join(parts)

# ===================== Rules (overrides) =====================

@dataclass
class UnitRule:
    pattern: str
    tokens: List[str]
    unit: str
    order: int


def load_rules(path: Optional[Path]) -> List[UnitRule]:
    rules: List[UnitRule] = []
    if not path or not path.exists():
        return rules
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: cannot read rules file: {e}", file=sys.stderr)
        return rules
    overrides = obj.get("overrides", []) if isinstance(obj, dict) else []
    if not isinstance(overrides, list):
        return rules
    for i, it in enumerate(overrides):
        if not isinstance(it, dict):
            continue
        pat = it.get("pattern")
        unit = it.get("unit")
        if not (isinstance(pat, str) and isinstance(unit, str)):
            continue
        toks = [tok for tok in pat.replace("[]", "").split(".") if tok]
        if not toks:
            continue
        rules.append(UnitRule(pattern=pat, tokens=toks, unit=unit, order=i))
    return rules


def choose_unit_for(path: Sequence[PathToken], rules: List[UnitRule]) -> Optional[Tuple[str, bool]]:
    if not rules:
        return None
    reduced: List[str] = []
    for t in path:
        reduced.append(t.key)
    best: Tuple[int, int, UnitRule] | None = None
    for r in rules:
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

# ===================== Title & format =====================

def build_title(path: Sequence[PathToken], width_by_key: Dict[str, int], prefix: str, sep: str) -> str:
    elements: List[str] = []
    for t in path:
        if isinstance(t, ArrIdx):
            w = width_by_key.get(t.key, 1)
            elements.append(f"{t.key}[{t.idx:0{w}d}]")
        elif isinstance(t, ObjKey):
            elements.append(t.key)
        else:
            raise TypeError("unknown token")
    path_str = sep.join(elements)
    if prefix:
        return f"{prefix}{sep}{path_str}" if path_str else prefix
    else:
        return path_str


def path_signature(tokens: Sequence[PathToken]) -> Tuple[str, ...]:
    sig: List[str] = []
    for t in tokens:
        if isinstance(t, ArrIdx):
            sig.append(f"{t.key}[]")
        elif isinstance(t, ObjKey):
            sig.append(t.key)
    return tuple(sig)


def format_string_for(path: Sequence[PathToken],
                      decimals_by_sig: Dict[Tuple[str, ...], int],
                      unit_rules: List[UnitRule]) -> str:
    unit_override = choose_unit_for(path, unit_rules)
    if unit_override and unit_override[1]:
        return unit_override[0]
    d = max(0, decimals_by_sig.get(path_signature(path), 0))
    base = "<v>" if d == 0 else f"<v.{d}>"
    if unit_override and not unit_override[1]:
        return f"{base} {unit_override[0]}"
    return base

# ===================== Build commands =====================

def build_commands_from_json(root: Any, prefix: str, sep: str, unit_rules: List[UnitRule]) -> List[Tuple[str, str, str]]:
    arr_len: Dict[str, int] = {}
    _collect_array_lengths_json(root, arr_len)
    width_by_key = _index_width_map(arr_len)

    leaves = list(_walk_numeric_leaves_json(root, []))

    decimals_by_sig: Dict[Tuple[str, ...], int] = {}
    for p, _val, dec in leaves:
        sig = path_signature(p)
        decimals_by_sig[sig] = max(decimals_by_sig.get(sig, 0), dec)

    cmds: List[Tuple[str, str, str]] = []
    for p, _val, _dec in leaves:
        title = build_title(p, width_by_key, prefix, sep)
        check = build_check_string_json(p)
        unit = format_string_for(p, decimals_by_sig, unit_rules)
        cmds.append((title, check, unit))
    return cmds


def build_commands_from_xml(root: ET.Element, prefix: str, sep: str, unit_rules: List[UnitRule]) -> List[Tuple[str, str, str]]:
    arr_len: Dict[str, int] = {}
    _collect_array_lengths_xml(root, arr_len)
    width_by_key = _index_width_map(arr_len)

    leaves = list(_walk_numeric_leaves_xml(root, []))

    decimals_by_sig: Dict[Tuple[str, ...], int] = {}
    for p, _val, dec in leaves:
        sig = path_signature(p)
        decimals_by_sig[sig] = max(decimals_by_sig.get(sig, 0), dec)

    cmds: List[Tuple[str, str, str]] = []
    for p, _val, _dec in leaves:
        title = build_title(p, width_by_key, prefix, sep)
        check = build_check_string_xml(p)
        unit = format_string_for(p, decimals_by_sig, unit_rules)
        cmds.append((title, check, unit))
    return cmds

# ===================== Rules skeleton generators =====================

def generate_rules_skeleton_from_json(root: Any) -> str:
    patterns: List[str] = []
    seen: set[str] = set()
    for path, _val, _dec in _walk_numeric_leaves_json(root, []):
        toks: List[str] = []
        for t in path:
            toks.append(t.key)
        pat = ".".join(toks).replace(".$root", "")
        if pat not in seen:
            seen.add(pat)
            patterns.append(pat)
    patterns.sort()
    lines = ['{', '  "overrides": [']
    for i, p in enumerate(patterns):
        comma = "," if i < len(patterns) - 1 else ""
        lines.append(f'    {{"pattern":"{p}","unit":""}}{comma}')
    lines.append('  ]')
    lines.append('}')
    return "\n".join(lines)


def generate_rules_skeleton_from_xml(root: ET.Element) -> str:
    patterns: List[str] = []
    seen: set[str] = set()
    for path, _val, _dec in _walk_numeric_leaves_xml(root, []):
        toks: List[str] = []
        for t in path:
            toks.append(t.key)
        pat = ".".join(toks)
        if pat not in seen:
            seen.add(pat)
            patterns.append(pat)
    patterns.sort()
    lines = ['{', '  "overrides": [']
    for i, p in enumerate(patterns):
        comma = "," if i < len(patterns) - 1 else ""
        lines.append(f'    {{"pattern":"{p}","unit":""}}{comma}')
    lines.append('  ]')
    lines.append('}')
    return "\n".join(lines)

# ===================== XML rendering =====================

def render_xml(commands: List[Tuple[str, str, str]], title: str, address_url: str, polling_time: int,
               miniserver_min_version: str, full_comment_json: str) -> str:
    title_attr = _xml_escape_attr(title)
    addr_attr = _xml_escape_attr(address_url)
    comment_attr = _xml_escape_attr(full_comment_json) if full_comment_json else ""
    out: List[str] = []
    if full_comment_json:
        out.append(f"<!-- {full_comment_json} -->")
    out.append(f"<VirtualInHttp Title=\"{title_attr}\" Comment=\"{comment_attr}\" Address=\"{addr_attr}\" HintText=\"\" PollingTime=\"{polling_time}\">")
    out.append(f"	<Info templateType=\"2\" minVersion=\"{miniserver_min_version}\"/>")
    for t, chk, unit in commands:
        out.append(
            "	<VirtualInHttpCmd "
            f"Title=\"{_xml_escape_attr(t)}\" "
            f"Unit=\"{_xml_escape_attr(unit)}\" "
            f"Check=\"{chk}\" "
            f"Signed=\"true\" Analog=\"true\" "
            f"SourceValLow=\"0\" DestValLow=\"0\" "
            f"SourceValHigh=\"100\" DestValHigh=\"100\" "
            f"Comment=\"\"/>"
        )
    out.append("</VirtualInHttp>")
    return "\n".join(out) + "\n"

# ===================== Metadata (always full, minified) =====================

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

# ===================== Manifest =====================

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
        # If unreadable, fall back to defaults (do not crash)
        return {
            "project": project,
            "source": {"url": None, "response": None},
            "rules": str(rules_default_path(project)),
            "build": {"title": project, "name_separator": " ", "polling_time": 1200, "address_url": None},
            "prefixes": []
        }


def save_manifest(project: str, data: Dict[str, Any]) -> None:
    manifest_path(project).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ===================== Format sniffing =====================

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

# ===================== Subcommand impls =====================

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
    fmt = sniff_format(text)

    # Build skeleton
    if fmt == "json":
        root = json.loads(text)
        content = generate_rules_skeleton_from_json(root)
    else:
        root = ET.fromstring(text)
        content = generate_rules_skeleton_from_xml(root)

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
    fmt = sniff_format(text)
    data = json.loads(text) if fmt == "json" else ET.fromstring(text)

    # Resolve rules
    rules_path = Path(m.get("rules") or str(rules_default_path(project)))
    unit_rules = load_rules(rules_path if rules_path.exists() else None)

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
        eff_prefix = pref or ""
        cmds = (build_commands_from_json(data, eff_prefix, eff_sep, unit_rules)
                if fmt == "json" else
                build_commands_from_xml(data, eff_prefix, eff_sep, unit_rules))

        # Title: include prefix if present
        full_title = f"{eff_prefix} {eff_title}".strip() if eff_prefix else eff_title

        # Output path rules
        if output is not None and len(prefix_list) == 1:
            out_path = output
        elif output is not None and len(prefix_list) > 1:
            print("Error: --output cannot be a single file when multiple prefixes are used.", file=sys.stderr)
            return 2
        else:
            out_path = output_default_path(project, eff_prefix or None)

        meta_json = build_full_metadata(resp_path, out_path, rules_path if rules_path.exists() else None, {
            "prefix": eff_prefix,
            "sep": eff_sep,
            "title": full_title,
            "poll": eff_poll,
            "address_url": eff_addr
        })

        xml_body = render_xml(cmds, title=full_title, address_url=eff_addr, polling_time=eff_poll,
                              miniserver_min_version="16000610", full_comment_json=meta_json)
        xml_content = f'<?xml version="1.0" encoding="utf-8"?>\n{xml_body}'
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

# ===================== CLI =====================

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