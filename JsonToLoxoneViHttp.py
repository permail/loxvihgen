#!/usr/bin/env python3
"""
JsonToLoxoneViHttp — Generate Loxone Virtual HTTP Input (VIH) templates from JSON

What it does
------------
- Reads a sample JSON (e.g., from any HTTP/JSON service).
- Walks the JSON recursively and creates one Loxone command per *numeric* leaf.
- Builds Loxone search strings from the JSON path (including arrays) and
  assigns a Unit/format based on decimals seen in the sample.

Typical workflow
----------------
1) Generate a units template from your JSON (full paths included):
   $ python JsonToLoxoneViHttp.py data.json --gen-units
   -> writes: data-units.json

2) Edit data-units.json: fill units for patterns you care about.
   - Patterns are dot-separated suffix paths like:
       "temp", "temp.min", "feels_like.min", "hourly.wind_speed", "daily[].temp.max"
   - Arrays: indices are ignored. "[]" is optional and cosmetic.
   - Longest matching suffix wins. If a unit starts with "<" (e.g., "<v.2> °F"),
     it is taken as a complete Loxone format string.

3) Generate the Loxone XML template:
   $ python JsonToLoxoneViHttp.py data.json
   (auto-detects data-units.json → units.json; creates VI_data.xml)

   With a custom title, prefix and dot-separated names:
   $ python JsonToLoxoneViHttp.py data.json --title "My Weather" --prefix owm1c --name-separator "."

Key details
-----------
- Command titles: [prefix][sep]<path with optional [NN] indices>. If prefix is empty, no leading sep.
- Decimals: uses the maximum decimals observed for the same path-signature across an array.
  Unit becomes "<v>" or "<v.N>". If a unit override starts with "<", it is used verbatim.
- Order: preserves JSON order (e.g., foo[4] before foo[47]).
- XML command attribute order: Title, Unit, Check, then the rest.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__tool__ = "JsonToLoxoneViHttp"
__version__ = "1.7.0"

# ===================== Data model =====================

@dataclass(frozen=True)
class ObjKey:
    key: str

@dataclass(frozen=True)
class ArrIdx:
    key: str   # array name
    idx: int   # 0-based

PathToken = ObjKey | ArrIdx

# ===================== Helpers =====================

def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def _count_decimals(val: float) -> int:
    s = str(val)
    if "e" in s or "E" in s:
        s = format(val, ".12f").rstrip("0").rstrip(".")
    if "." in s:
        return len(s.split(".")[1])
    return 0

def _collect_array_lengths(node: Any, arr_len: Dict[str, int]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list):
                arr_len[k] = max(arr_len.get(k, 0), len(v))
                for item in v:
                    _collect_array_lengths(item, arr_len)
            else:
                _collect_array_lengths(v, arr_len)
    elif isinstance(node, list):
        for item in node:
            _collect_array_lengths(item, arr_len)

def _walk_numeric_leaves(node: Any, prefix: List[PathToken]) -> Iterable[Tuple[List[PathToken], float, int]]:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list):
                for i, item in enumerate(v):
                    yield from _walk_numeric_leaves(item, prefix + [ArrIdx(k, i)])
            else:
                yield from _walk_numeric_leaves(v, prefix + [ObjKey(k)])
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_numeric_leaves(v, prefix + [ArrIdx("$root", i)])
    else:
        if _is_number(node):
            fv = float(node)
            yield (prefix, fv, _count_decimals(fv))

def _index_width_map(arr_len: Dict[str, int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for k, n in arr_len.items():
        out[k] = max(1, len(str(max(0, n - 1))))  # width from max index
    return out

def _xml_escape_attr(s: str) -> str:
    return html_escape(s, quote=True)

def _quoted_key(k: str) -> str:
    return f"&quot;{_xml_escape_attr(k)}&quot;"

def build_check_string(path: Sequence[PathToken]) -> str:
    parts: List[str] = []
    i_quote = "\\i"
    for t in path:
        if isinstance(t, ObjKey):
            parts.append(f"{i_quote}{_quoted_key(t.key)}:{i_quote}")
        elif isinstance(t, ArrIdx):
            parts.append(f"{i_quote}{_quoted_key(t.key)}:[{i_quote}")
            parts.append("\\i{\\i" * (t.idx + 1))
        else:
            raise TypeError("unknown token")
    parts.append("\\v")
    return "".join(parts)

def _normalize_tokens_for_units(path: Sequence[PathToken], with_arrays: bool = False) -> List[str]:
    """Reduced tokens. with_arrays=True -> arrays as 'key[]', else 'key'."""
    out: List[str] = []
    for t in path:
        if isinstance(t, ObjKey):
            out.append(t.key)
        elif isinstance(t, ArrIdx):
            out.append(f"{t.key}[]" if with_arrays else t.key)
        else:
            raise TypeError("unknown token")
    return out

# ===================== Units overrides =====================

@dataclass
class UnitRule:
    pattern: str            # e.g., "temp.min", "hourly.wind_speed"
    tokens: List[str]       # dot-splitted tokens, [] removed
    unit: str               # unit or full Loxone format string if starting with "<"
    order: int              # input order for tie-breaks

def load_unit_overrides(path: Optional[Path]) -> List[UnitRule]:
    rules: List[UnitRule] = []
    if not path:
        return rules
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: cannot read units file: {e}", file=sys.stderr)
        return rules
    overrides = obj.get("overrides", []) if isinstance(obj, dict) else []
    if not isinstance(overrides, list):
        return rules
    for i, it in enumerate(overrides):
        if not isinstance(it, dict):
            continue
        pat = it.get("pattern")
        unit = it.get("unit")
        if not (isinstance(pat, str) and isinstance(unit, str) and pat):
            continue
        toks = [tok for tok in pat.replace("[]", "").split(".") if tok]
        rules.append(UnitRule(pattern=pat, tokens=toks, unit=unit, order=i))
    return rules

def choose_unit_for(path: Sequence[PathToken], rules: List[UnitRule]) -> Optional[Tuple[str, bool]]:
    """Return (unit_string, is_full_format). If is_full_format==True, use as-is."""
    if not rules:
        return None
    reduced = _normalize_tokens_for_units(path)  # without [] for matching
    best: Tuple[int, int, UnitRule] | None = None  # (match_len, -order, rule)
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

# ===================== Title building =====================

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

# ===================== Format string =====================

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
    # Unit override first
    unit_override = choose_unit_for(path, unit_rules)
    if unit_override and unit_override[1]:
        return unit_override[0]  # full format override

    d = max(0, decimals_by_sig.get(path_signature(path), 0))
    base = "<v>" if d == 0 else f"<v.{d}>"

    if unit_override and not unit_override[1]:
        return f"{base} {unit_override[0]}"
    return base

# ===================== Build commands =====================

def build_commands(root: Any, prefix: str, sep: str, unit_rules: List[UnitRule]) -> List[Tuple[str, str, str]]:
    arr_len: Dict[str, int] = {}
    _collect_array_lengths(root, arr_len)
    width_by_key = _index_width_map(arr_len)

    leaves = list(_walk_numeric_leaves(root, []))  # in JSON order

    decimals_by_sig: Dict[Tuple[str, ...], int] = {}
    for p, _val, dec in leaves:
        sig = path_signature(p)
        decimals_by_sig[sig] = max(decimals_by_sig.get(sig, 0), dec)

    cmds: List[Tuple[str, str, str]] = []
    for p, _val, _dec in leaves:
        title = build_title(p, width_by_key, prefix, sep)
        check = build_check_string(p)
        unit = format_string_for(p, decimals_by_sig, unit_rules)
        cmds.append((title, check, unit))
    return cmds

# ===================== Units template generator =====================

def generate_units_template(root: Any) -> str:
    """Return a compact units.json template as a string.
       One override per line, full paths (with [] for arrays).
    """
    patterns: List[str] = []
    seen: set[str] = set()

    for path, _val, _dec in _walk_numeric_leaves(root, []):
        toks = _normalize_tokens_for_units(path, with_arrays=True)  # e.g., ['daily[]','temp','max']
        pat = ".".join(toks)
        if pat not in seen:
            seen.add(pat)
            patterns.append(pat)

    patterns.sort()
    # compact JSON: each override on its own line
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
    out.append(f"\t<Info templateType=\"2\" minVersion=\"{miniserver_min_version}\"/>")
    for t, chk, unit in commands:
        out.append(
            "\t<VirtualInHttpCmd "
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

# ===================== Metadata (always full) =====================

def build_full_metadata(input_path: Optional[Path],
                        output_path: Optional[Path],
                        units_path: Optional[Path],
                        opts: Dict[str, Any]) -> str:
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = []
    if input_path:
        files.append({"role":"input","name":str(input_path)})
    if units_path:
        files.append({"role":"units","name":str(units_path)})
    if output_path:
        files.append({"role":"output","name":str(output_path)})
    meta = {
        "tool": __tool__,
        "version": __version__,
        "utc": utc,
        "files": files,
        "opts": {
            "prefix": opts.get("prefix",""),
            "sep": opts.get("sep"," "),
            "title": opts.get("title",""),
            "poll": int(opts.get("poll",1200)),
            "address_url": opts.get("address_url","")
        }
    }
    # minified one-liner
    return json.dumps(meta, separators=(",",":"))

# ===================== CLI =====================

def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Generate a Loxone VI-HTTP XML template from a sample JSON")
    p.add_argument("input_json", help="Path to JSON or '-' for stdin")
    p.add_argument("output_xml", nargs="?", help="Output XML path (optional, default: VI_<stem>.xml)")
    p.add_argument("--units", type=Path, default=None, help="Units overrides JSON (optional)")
    p.add_argument("--gen-units", action="store_true", help="Generate a units template file and exit")
    p.add_argument("--units-out", type=Path, default=None, help="Units template output path (default: <stem>-units.json)")
    p.add_argument("--prefix", default="", help="Title prefix (default: empty)")
    p.add_argument("--name-separator", dest="sep", default=" ", help="Separator between path elements in titles (default: space)")
    p.add_argument("--address-url", default="http://...", help="Service URL string stored in the XML (default: 'http://...')")
    p.add_argument("--title", default=None, help="Template title (default: input filename without extension; for stdin: 'vi-http')")
    p.add_argument("--polling-time", dest="poll", type=int, default=1200, help="Polling interval in seconds (default: 1200)")
    args = p.parse_args(argv)

    # Read input
    input_path: Optional[Path] = None
    if args.input_json == "-":
        data = json.load(sys.stdin)
    else:
        input_path = Path(args.input_json)
        data = json.loads(input_path.read_text(encoding="utf-8"))

    # gen-units mode?
    if args.gen_units:
        units_out = args.units_out
        if units_out is None:
            if input_path is None:
                print("Error: --units-out is required when input is stdin.", file=sys.stderr)
                return 2
            units_out = input_path.with_name(f"{input_path.stem}-units.json")
        content = generate_units_template(data)
        units_out.write_text(content, encoding="utf-8")
        print(f"OK: units template written → {units_out}")
        return 0

    # Title default from input stem
    title = args.title if args.title is not None else (input_path.stem if input_path else "vi-http")

    # Units autodiscovery
    units_path: Optional[Path] = args.units
    if units_path is None and input_path is not None:
        cand1 = input_path.with_name(input_path.stem + "-units.json")
        cand2 = input_path.with_name("units.json")
        if cand1.exists():
            units_path = cand1
        elif cand2.exists():
            units_path = cand2

    unit_rules = load_unit_overrides(units_path)

    # Output path
    output_path: Optional[Path] = None
    if args.output_xml:
        output_path = Path(args.output_xml)
    else:
        if input_path is None:
            print("Error: OUTPUT_XML is required when input is stdin.", file=sys.stderr)
            return 2
        output_path = input_path.with_name(f"VI_{input_path.stem}.xml")

    # Build commands
    cmds = build_commands(data, args.prefix, args.sep, unit_rules)

    # Build metadata (always full, minified)
    meta_json = build_full_metadata(input_path, output_path, units_path, {
        "prefix": args.prefix,
        "sep": args.sep,
        "title": title,
        "poll": args.poll,
        "address_url": args.address_url
    })

    # Render + write XML
    xml_body = render_xml(cmds, title=title, address_url=args.address_url, polling_time=args.poll,
                          miniserver_min_version="16000610",
                          full_comment_json=meta_json)
    xml_content = f'<?xml version="1.0" encoding="utf-8"?>\n{xml_body}'
    output_path.write_text(xml_content, encoding="utf-8")
    print(f"OK: {len(cmds)} commands → {output_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())