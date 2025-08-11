#!/usr/bin/env python3
"""
JsonToLoxViHttp — Generator für Loxone Virtual HTTP Input (VIH) Vorlagen

Zweck
-----
Erzeugt aus einem Beispiel-JSON eine importierbare Loxone-XML-Vorlage.
Alle *numerischen* Felder werden als Befehle abgebildet. Suchstrings werden
aus dem JSON-Pfad konstruiert (inkl. Array-Indizierung nach Loxone-Logik).

Wesentliches
------------
- JSON-Reihenfolge bleibt erhalten (foo[4] vor foo[47]).
- Format-String: <v> oder <v.N> basierend auf Nachkommastellen (array-weit).
- Units-Overrides per **Suffix-Pfad** (z. B. "temp.min", "hourly.wind_speed").
  Längster Suffix gewinnt; "[]" optional; Array-Indizes werden ignoriert.
- **Spezialfall:** Wenn die Unit im Override mit "<" beginnt (z. B. "<v.3> °F"),
  wird sie **eins-zu-eins** als kompletter Loxone-Formatstring übernommen
  (kein automatisches <v.N> + Einheit).
- Optional: Generiere eine **Units-Template**-Datei aus dem JSON mit vollen Pfaden
  (z. B. "daily[].temp.max"), damit man die Einheiten bequem ausfüllen kann.

Metadaten
---------
- In `VirtualInHttp/@Comment`: **minimal** (einzeiliges JSON).
- Zusätzlich als XML-Kommentar oberhalb des Root: **full**.
- Es werden **keine Dateigrößen** und **kein cwd** ausgegeben.

CLI
---
python JsonToLoxViHttp.py INPUT_JSON [OUTPUT_XML]
  [--units UNITS_JSON]
  [--prefix PREFIX]
  [--name-separator SEP]
  [--address-url URL]
  [--title TITLE]
  [--polling-time SECONDS]
  [--metadata {minimal,full,off}]
  [--gen-units] [--units-out UNITS_OUT]

- INPUT_JSON: Dateipfad oder "-" (stdin)
- OUTPUT_XML: optional; fehlt → "VI_<stem>.xml" (nur wenn INPUT eine Datei ist)
- --units: optional; Autodiscovery wenn nicht gesetzt: "<stem>-units.json" → "units.json"
- --gen-units: erzeugt eine Units-Template-Datei (Default-Pfad: "<stem>-units.json") und beendet sich.
- --units-out: Pfad für die Units-Template-Datei (nur zusammen mit --gen-units)
- --prefix: optional; Default "" (leer). Ist leer → kein führender Separator.
- --name-separator: Default " " (Leerzeichen). Beispiel "." → "owm1c.hourly[03].wind_speed"
- --address-url: Default "http://..." (platzhalter, dienst-neutral)
- --title: Default = **Input-Dateiname ohne Endung** (bei stdin: "vi-http")
- --polling-time: Default 1200
- --metadata: Default "minimal". "off" unterdrückt beide Metadaten.
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

__tool__ = "JsonToLoxViHttp"
__version__ = "1.6.0"

# ===================== Datamodel =====================

@dataclass(frozen=True)
class ObjKey:
    key: str

@dataclass(frozen=True)
class ArrIdx:
    key: str   # Array-Name
    idx: int   # 0-basiert

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
        out[k] = max(1, len(str(max(0, n - 1))))  # Breite aus max Index
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
    """Reduzierte Tokens. with_arrays=True → Arrays als 'key[]', sonst 'key'."""
    out: List[str] = []
    for t in path:
        if isinstance(t, ObjKey):
            out.append(t.key)
        elif isinstance(t, ArrIdx):
            out.append(f"{t.key}[]" if with_arrays else t.key)
        else:
            raise TypeError("unknown token")
    return out

# ===================== Units Overrides =====================

@dataclass
class UnitRule:
    pattern: str            # Original pattern string (z. B. "temp.min", "hourly.wind_speed")
    tokens: List[str]       # Dot-splitted tokens, [] entfernt
    unit: str               # Einheit oder kompletter Loxone-Formatstring, wenn mit "<" beginnend
    order: int              # Eingabereihenfolge

def load_unit_overrides(path: Optional[Path]) -> List[UnitRule]:
    rules: List[UnitRule] = []
    if not path:
        return rules
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warnung: Units-Datei konnte nicht gelesen werden: {e}", file=sys.stderr)
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
    """
    Returns (unit_string, is_full_format). If is_full_format is True, the unit_string is a
    complete Loxone Unit field (e.g., "<v.2> °F") and should be used as-is.
    """
    if not rules:
        return None
    reduced = _normalize_tokens_for_units(path)  # ohne [] für Matching
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

# ===================== Titelbau =====================

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

# ===================== Format-String =====================

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

# ===================== Build Commands =====================

def build_commands(root: Any, prefix: str, sep: str, unit_rules: List[UnitRule]) -> List[Tuple[str, str, str]]:
    arr_len: Dict[str, int] = {}
    _collect_array_lengths(root, arr_len)
    width_by_key = _index_width_map(arr_len)

    leaves = list(_walk_numeric_leaves(root, []))  # JSON-Reihenfolge

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

# ===================== Units Template Generator =====================

def generate_units_template(root: Any) -> Dict[str, Any]:
    """Erzeugt ein units.json-Skelett mit vollen Pfad-Patterns (inkl. [] für Arrays)."""
    patterns: List[str] = []
    seen: set[str] = set()

    for path, _val, _dec in _walk_numeric_leaves(root, []):
        toks = _normalize_tokens_for_units(path, with_arrays=True)  # z. B. ['daily[]','temp','max']
        # Leaf ist das letzte Token, also der eigentliche Zahlen-Name
        pat = ".".join(toks)
        if pat not in seen:
            seen.add(pat)
            patterns.append(pat)

    patterns.sort()
    return {"overrides": [{"pattern": p, "unit": ""} for p in patterns]}

# ===================== XML Rendering =====================

def render_xml(commands: List[Tuple[str, str, str]], title: str, address_url: str, polling_time: int,
               miniserver_min_version: str, minimal_comment: str, full_comment: str) -> str:
    title_attr = _xml_escape_attr(title)
    addr_attr = _xml_escape_attr(address_url)
    comment_attr = _xml_escape_attr(minimal_comment) if minimal_comment else ""
    out: List[str] = []
    if full_comment:
        out.append(f"<!-- {full_comment} -->")
    out.append(f"<VirtualInHttp Title=\"{title_attr}\" Comment=\"{comment_attr}\" Address=\"{addr_attr}\" HintText=\"\" PollingTime=\"{polling_time}\">")
    out.append(f"\t<Info templateType=\"2\" minVersion=\"{miniserver_min_version}\"/>")
    for t, chk, unit in commands:
        # Titel, Unit, Check, dann Rest; bestimmte fixe Felder (DefVal/MinVal/MaxVal/HintText) sind bewusst weggelassen
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

# ===================== Metadata =====================

def _file_info(role: str, path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    return {"role": role, "name": str(path)}

def build_metadata(mode: str,
                   input_path: Optional[Path],
                   output_path: Optional[Path],
                   units_path: Optional[Path],
                   opts: Dict[str, Any]) -> Tuple[str, str]:
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = []
    fi = _file_info("input", input_path)
    if fi: files.append(fi)
    fu = _file_info("units", units_path)
    if fu: files.append(fu)
    minimal = {
        "tool": __tool__,
        "version": __version__,
        "utc": utc,
        "files": files,
        "output": str(output_path) if output_path else None,
        "opts": {"prefix": opts.get("prefix",""), "sep": opts.get("sep"," "), "poll": int(opts.get("poll",1200)), "title": opts.get("title","")}
    }
    minimal_str = json.dumps(minimal, separators=(",",":"))
    if mode == "off":
        return "", ""
    full = {
        "tool": __tool__,
        "version": __version__,
        "utc": utc,
        "args": opts,
        "files": files + ([{"role":"output","name": str(output_path)}] if output_path else [])
    }
    full_str = json.dumps(full, ensure_ascii=False)
    return minimal_str, full_str

# ===================== CLI =====================

def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Erzeuge Loxone-VIH-XML aus Beispiel-JSON")
    p.add_argument("input_json", help="Pfad zum Beispiel-JSON oder '-' für stdin")
    p.add_argument("output_xml", nargs="?", help="Zielpfad der XML-Vorlage (optional, Autoname: VI_<stem>.xml)")
    p.add_argument("--units", type=Path, default=None, help="Units-Overrides JSON-Datei (optional)")
    p.add_argument("--gen-units", action="store_true", help="Erzeuge eine Units-Template-Datei und beende")
    p.add_argument("--units-out", type=Path, default=None, help="Zielpfad für Units-Template (Default: <stem>-units.json)")
    p.add_argument("--prefix", default="", help="Titel-Prefix (Default: leer)")
    p.add_argument("--name-separator", dest="sep", default=" ", help="Trenner zwischen Pfadelementen (Default: ' ')")
    p.add_argument("--address-url", default="http://...", help="Adresse/URL des Webservice (Default: 'http://...')")
    p.add_argument("--title", default=None, help="Vorlagen-Titel (Default: Input-Dateiname ohne Endung; bei stdin: 'vi-http')")
    p.add_argument("--polling-time", dest="poll", type=int, default=1200, help="Abfrageintervall in Sekunden (Default: 1200)")
    p.add_argument("--metadata", choices=["minimal","full","off"], default="minimal", help="Metadaten-Ausgabe (Default: minimal)")
    args = p.parse_args(argv)

    # Input lesen
    input_path: Optional[Path] = None
    if args.input_json == "-":
        data = json.load(sys.stdin)
    else:
        input_path = Path(args.input_json)
        data = json.loads(input_path.read_text(encoding="utf-8"))

    # Gen-Units-Modus?
    if args.gen_units:
        if args.units_out:
            units_out = args.units_out
        else:
            if input_path is None:
                print("Fehler: --units-out ist erforderlich, wenn INPUT_JSON '-' ist.", file=sys.stderr)
                return 2
            units_out = input_path.with_name(f"{input_path.stem}-units.json")
        tmpl = generate_units_template(data)
        units_out.write_text(json.dumps(tmpl, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK: Units-Template erzeugt → {units_out}")
        return 0

    # Title default aus Input-Stem
    title = args.title
    if title is None:
        title = input_path.stem if input_path is not None else "vi-http"

    # Units-Datei ermitteln (wenn nicht explizit)
    units_path: Optional[Path] = args.units
    if units_path is None and input_path is not None:
        cand1 = input_path.with_name(input_path.stem + "-units.json")
        cand2 = input_path.with_name("units.json")
        if cand1.exists():
            units_path = cand1
        elif cand2.exists():
            units_path = cand2

    unit_rules = load_unit_overrides(units_path)

    # Output ermitteln
    output_path: Optional[Path] = None
    if args.output_xml:
        output_path = Path(args.output_xml)
    else:
        if input_path is None:
            print("Fehler: OUTPUT_XML ist erforderlich, wenn INPUT_JSON '-' ist.", file=sys.stderr)
            return 2
        output_path = input_path.with_name(f"VI_{input_path.stem}.xml")

    # Kommandos bauen
    cmds = build_commands(data, args.prefix, args.sep, unit_rules)

    # Metadaten
    opts = {
        "prefix": args.prefix,
        "sep": args.sep,
        "address_url": args.address_url,
        "title": title,
        "poll": args.poll,
        "metadata": args.metadata
    }
    minimal_comment, full_comment = build_metadata(args.metadata, input_path, output_path, units_path, opts)

    # XML rendern
    xml_body = render_xml(cmds, title=title, address_url=args.address_url, polling_time=args.poll,
                          miniserver_min_version="16000610",
                          minimal_comment=(minimal_comment if args.metadata != "off" else ""),
                          full_comment=(full_comment if args.metadata != "off" else ""))

    xml_content = f'<?xml version="1.0" encoding="utf-8"?>\n{xml_body}'
    output_path.write_text(xml_content, encoding="utf-8")
    print(f"OK: {len(cmds)} Befehle → {output_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())