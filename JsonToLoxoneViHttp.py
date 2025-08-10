#!/usr/bin/env python3
"""
Loxone Virtual HTTP Input (VIH) Vorlage-Generator

- Liest ein Beispiel-JSON (OpenWeather One Call 3.0 o.ä.).
- Traversiert rekursiv und erzeugt für *alle numerischen Felder* Loxone-Suchstrings.
- Schreibt eine XML-Vorlage, die direkt in Loxone Config importierbar ist.

Python: 3.10+

Wesentliche Optionen / Änderungen:
- Arrays: korrekte Key-gebundene Indizierung (kein <root_list> mehr).
- Titel-Trenner konfigurierbar (NAME_SEPARATOR), Default: " ". Beispiel mit Punkt: "owm1c.hourly[09].wind_speed".
- Dezimalstellen pro Pfad (array-weit) aus Beispiel-JSON ermitteln ⇒ Unit "<v>" oder "<v.N>".
- Optionale Units-Overrides per Datei (--units units.json): mappt *Attributnamen* auf physikalische Einheiten.
- Reihenfolge der Kommandos entspricht JSON-Reihenfolge (keine Sortierung mehr).

Suchstring-Logik:
  - Objektpfad: \i"key":\i …
  - Arrayauswahl: \i"arrKey":[\i + ("\i{\i" * (index+1)) …
  - Wert am Ende: … \v

XML-Attribute werden HTML-escaped. Backslashes bleiben erhalten.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple, Optional
from decimal import Decimal

# ===================== Konfiguration =====================
PREFIX = "owm1c"                 # Titel-Prefix
NAME_SEPARATOR = " "             # Trenner zwischen Pfadelementen im Titel (z.B. "." für Punkt-Notation)
POLLING_TIME = 1200              # Sekunden
ADDRESS_URL = (
    "https://api.openweathermap.org/data/3.0/onecall?units=metric&lang=de&lat=48.2&lon=14.4&appid=TODO_INSERT_API_KEY_HERE"
)
ROOT_TITLE = "openweathermap.com onecall"
MINISERVER_MIN_VERSION = "16000610"

# Werte-Mapping wie im Beispiel
SIGNED = "true"
ANALOG = "true"
SRC_LOW = 0
SRC_HIGH = 100
DST_LOW = 0
DST_HIGH = 100
DEF_VAL = 0
MIN_VAL = -10000
MAX_VAL = 10000

# ===================== Pfadrepräsentation =====================
@dataclass(frozen=True)
class ObjKey:
    key: str

@dataclass(frozen=True)
class ArrIdx:
    key: str  # Array-Key-Name
    idx: int  # 0-basiert

PathToken = ObjKey | ArrIdx

# ===================== Traversierung & Hilfen =====================

def _is_number(x: Any) -> bool:
    # bool ist Unterklasse von int => ausschließen
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _count_decimals(val: float) -> int:
    """Zählt Nachkommastellen anhand der String-Repräsentation.
    JSON verliert trailing zeros; das ist hier akzeptiert (Bsp. 28 ⇒ 0, 28.87 ⇒ 2).
    """
    s = str(val)
    if "e" in s or "E" in s:
        # in Dezimalform bringen
        s = format(val, ".10f").rstrip("0").rstrip(".")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def _collect_array_lengths(node: Any, arr_len: Dict[str, int]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list):
                arr_len[k] = max(arr_len.get(k, 0), len(v))
                for i, item in enumerate(v):
                    _collect_array_lengths(item, arr_len)
            else:
                _collect_array_lengths(v, arr_len)
    elif isinstance(node, list):
        for item in node:
            _collect_array_lengths(item, arr_len)


def _walk_numeric_leaves(node: Any, prefix: List[PathToken]) -> Iterable[Tuple[List[PathToken], float, int]]:
    """Yield (Pfad, Wert, Dezimalstellen) für alle numerischen leaves basierend auf Beispiel-JSON.
    WICHTIG: Listen unter einem Objekt-Key werden als ArrIdx(key, idx) emittiert (kein <root_list>!).
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list):
                for i, item in enumerate(v):
                    # direkt ArrIdx mit dem Key verwenden
                    yield from _walk_numeric_leaves(item, prefix + [ArrIdx(k, i)])
            else:
                yield from _walk_numeric_leaves(v, prefix + [ObjKey(k)])
    elif isinstance(node, list):
        # Nur relevant, wenn root eine Liste wäre (bei OWM nicht der Fall)
        for i, v in enumerate(node):
            yield from _walk_numeric_leaves(v, prefix + [ArrIdx("$root", i)])
    else:
        if _is_number(node):
            try:
                val = float(node)
            except Exception:
                return
            dec = _count_decimals(val)
            yield (prefix, val, dec)


def _path_signature(tokens: Sequence[PathToken]) -> Tuple[str, ...]:
    """Pfadsignatur ohne Indizes: [ArrIdx('hourly', 3), ObjKey('temp')] -> ("hourly[]", "temp")
    Dient dazu, Dezimalstellen/Units array-weit konsistent zuzuordnen.
    """
    sig: List[str] = []
    for t in tokens:
        if isinstance(t, ArrIdx):
            sig.append(f"{t.key}[]")
        elif isinstance(t, ObjKey):
            sig.append(t.key)
        else:
            raise TypeError("unknown token")
    return tuple(sig)

# ===================== Suchstring- und Titelbau =====================

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


def _index_width_map(arr_len: Dict[str, int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for k, n in arr_len.items():
        w = max(1, len(str(max(0, n - 1))))
        out[k] = w
    return out


def build_title(path: Sequence[PathToken], width_by_key: Dict[str, int]) -> str:
    elements: List[str] = []
    for t in path:
        if isinstance(t, ArrIdx):
            w = width_by_key.get(t.key, 1)
            elements.append(f"{t.key}[{t.idx:0{w}d}]")
        elif isinstance(t, ObjKey):
            elements.append(t.key)
        else:
            raise TypeError("unknown token")
    return PREFIX + NAME_SEPARATOR + NAME_SEPARATOR.join(elements)

# ===================== Units-Overrides =====================

def load_unit_overrides(path: Optional[Path]) -> Dict[str, str]:
    if not path:
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warnung: Units-Datei konnte nicht gelesen werden: {e}", file=sys.stderr)
        return {}
    overrides: Dict[str, str] = {}
    items = obj.get("overrides", []) if isinstance(obj, dict) else []
    for it in items:
        if isinstance(it, dict):
            attr = it.get("attribute")
            unit = it.get("unit")
            if isinstance(attr, str) and isinstance(unit, str) and attr:
                overrides[attr] = unit
    return overrides


def unit_string_for(path: Sequence[PathToken], decimals_by_sig: Dict[Tuple[str, ...], int], unit_over: Dict[str, str]) -> str:
    sig = _path_signature(path)
    d = max(0, decimals_by_sig.get(sig, 0))
    # Basis <v> oder <v.N>
    base = "<v>" if d == 0 else f"<v.{d}>"
    # Attributname = letzter ObjKey im Pfad (falls vorhanden), sonst der Array-Key
    last_attr: Optional[str] = None
    for t in reversed(path):
        if isinstance(t, ObjKey):
            last_attr = t.key
            break
        if isinstance(t, ArrIdx):
            last_attr = t.key  # fallback
            break
    suffix = unit_over.get(last_attr or "", "")
    if suffix:
        return f"{base} {suffix}"
    return base

# ===================== XML-Ausgabe =====================

def write_xml(commands: List[Tuple[str, str, str]], out_path: Path) -> None:
    """Schreibt die VirtualInHttp XML-Datei.
    commands: Liste aus (Title, CheckString, UnitString)
    """
    title_attr = _xml_escape_attr(ROOT_TITLE)
    addr_attr = _xml_escape_attr(ADDRESS_URL)

    with out_path.open("w", encoding="utf-8") as f:
        f.write("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n")
        f.write(
            f"<VirtualInHttp Title=\"{title_attr}\" Comment=\"\" Address=\"{addr_attr}\" HintText=\"\" PollingTime=\"{POLLING_TIME}\">\n"
        )
        f.write(f"\t<Info templateType=\"2\" minVersion=\"{MINISERVER_MIN_VERSION}\"/>\n")
        for title, check, unit in commands:
            f.write(
                "\t<VirtualInHttpCmd "
                f"Title=\"{_xml_escape_attr(title)}\" Comment=\"\" "
                f"Check=\"{check}\" Signed=\"{SIGNED}\" Analog=\"{ANALOG}\" "
                f"SourceValLow=\"{SRC_LOW}\" DestValLow=\"{DST_LOW}\" "
                f"SourceValHigh=\"{SRC_HIGH}\" DestValHigh=\"{DST_HIGH}\" "
                f"DefVal=\"{DEF_VAL}\" MinVal=\"{MIN_VAL}\" MaxVal=\"{MAX_VAL}\" "
                f"Unit=\"{_xml_escape_attr(unit)}\" HintText=\"\"/>\n"
            )
        f.write("</VirtualInHttp>\n")

# ===================== Hauptlogik =====================

def build_commands_from_json(root: Any, unit_over: Dict[str, str]) -> List[Tuple[str, str, str]]:
    # 1) Array-Längen für Indexbreite
    arr_len: Dict[str, int] = {}
    _collect_array_lengths(root, arr_len)
    width_by_key = _index_width_map(arr_len)

    # 2) Numerische Leaves sammeln (inkl. Dezimalstellen)
    leaves = list(_walk_numeric_leaves(root, []))  # [(path, val, dec)] in JSON-Reihenfolge

    # 3) Dezimalstellen pro Pfad-Signatur (max über alle Vorkommen)
    decimals_by_sig: Dict[Tuple[str, ...], int] = {}
    for path_tokens, _val, dec in leaves:
        sig = _path_signature(path_tokens)
        decimals_by_sig[sig] = max(decimals_by_sig.get(sig, 0), dec)

    # 4) Kommandos in derselben Reihenfolge ausgeben
    commands: List[Tuple[str, str, str]] = []
    for path_tokens, _val, _dec in leaves:
        # Skip falls kein ObjKey im Pfad (root-list Spezialfall)
        if not any(isinstance(t, (ObjKey, ArrIdx)) for t in path_tokens):
            continue
        title = build_title(path_tokens, width_by_key)
        check = build_check_string(path_tokens)
        unit = unit_string_for(path_tokens, decimals_by_sig, unit_over)
        commands.append((title, check, unit))

    return commands


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Erzeuge Loxone-VIH-XML aus Beispiel-JSON")
    p.add_argument("input_json", type=Path, help="Pfad zum Beispiel-JSON")
    p.add_argument("output_xml", type=Path, help="Zielpfad der XML-Vorlage")
    p.add_argument("--units", type=Path, default=None, help="Optionale Units-Overrides JSON-Datei")
    args = p.parse_args(argv)

    try:
        data = json.loads(args.input_json.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Fehler beim Lesen/Parsen von JSON: {e}", file=sys.stderr)
        return 2

    unit_over = load_unit_overrides(args.units)

    cmds = build_commands_from_json(data, unit_over)
    try:
        write_xml(cmds, args.output_xml)
    except Exception as e:
        print(f"Fehler beim Schreiben der XML: {e}", file=sys.stderr)
        return 3

    print(f"OK: {len(cmds)} Befehle erzeugt -> {args.output_xml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
