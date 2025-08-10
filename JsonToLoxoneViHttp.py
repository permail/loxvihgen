#!/usr/bin/env python3
"""
Loxone Virtual HTTP Input (VIH) Vorlage-Generator

- Liest ein Beispiel-JSON (OpenWeather One Call 3.0 oder ähnliches Schema).
- Traversiert rekursiv und erzeugt für *alle numerischen Felder* Loxone-Suchstrings.
- Schreibt eine XML-Vorlage, die direkt in Loxone Config importierbar ist.

Python: 3.10+

Hinweis:
- Arrays werden anhand der *Beispiellänge* indiziert. Titel-Indizes werden mit führenden Nullen gepolstert,
  sodass alle beobachteten Elemente reinpassen (Breite = len(str(n-1))).
- "Numerisch" bedeutet: JSON number (int/float). Strings werden ignoriert, auch wenn sie wie Zahlen aussehen.
- Suchstring-Logik:
  - Objektpfad: \i"key":\i …
  - Arrayauswahl: \i"arrKey":[\i + ("\i{\i" * (index+1)) …
  - Wert am Ende: … \v
- XML-Attribute werden HTML-escaped. Backslashes bleiben erhalten.

Konstanten unten (PREFIX, POLLING_TIME, ADDRESS_URL, ROOT_TITLE) bei Bedarf anpassen.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

# ===================== Konfiguration =====================
PREFIX = "owm1c"  # Titel-Prefix für jeden Befehl
POLLING_TIME = 1200  # Sekunden
ADDRESS_URL = (
    "https://api.openweathermap.org/data/3.0/onecall?units=metric&lang=de&lat=48.2&lon=14.4&appid=TODO_INSERT_API_KEY_HERE"
)
ROOT_TITLE = "openweathermap.com onecall"
MINISERVER_MIN_VERSION = "16000610"

# Werte-Mapping wie in deinem Beispiel (Loxone Defaults beibehalten)
SIGNED = "true"
ANALOG = "true"
SRC_LOW = 0
SRC_HIGH = 100
DST_LOW = 0
DST_HIGH = 100
DEF_VAL = 0
MIN_VAL = -10000
MAX_VAL = 10000
UNIT = "<v.1>"

# ===================== Pfadrepräsentation =====================
@dataclass(frozen=True)
class ObjKey:
    key: str

@dataclass(frozen=True)
class ArrIdx:
    key: str
    idx: int  # 0-basiert

PathToken = ObjKey | ArrIdx

# ===================== Traversierung =====================

def _is_number(x: Any) -> bool:
    # bool ist Unterklasse von int => ausschließen
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _collect_array_lengths(node: Any, arr_len: Dict[str, int]) -> None:
    """Merkt sich pro Array-KEY die maximale beobachtete Länge.
    Annahme: Arrays sind Werte eines Objekt-Schlüssels.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list):
                cur = len(v)
                prev = arr_len.get(k, 0)
                if cur > prev:
                    arr_len[k] = cur
                for i, item in enumerate(v):
                    _collect_array_lengths(item, arr_len)
            else:
                _collect_array_lengths(v, arr_len)
    elif isinstance(node, list):
        for item in node:
            _collect_array_lengths(item, arr_len)
    # sonst: leaf ⇒ ignorieren


def _walk_numeric_leaves(node: Any, prefix: List[PathToken]) -> Iterable[Tuple[List[PathToken], float]]:
    """Yield (Pfad, Wert) für alle numerischen leaves basierend auf Beispiel-JSON."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_numeric_leaves(v, prefix + [ObjKey(k)])
    elif isinstance(node, list):
        # Listen ohne zu wissen wie sie heißen (falls direkt list als root) ⇒ Keys nicht vorhanden
        for i, v in enumerate(node):
            # Ohne key-Name können wir die Array-Navigation nicht zusammenbauen ⇒
            # Diese Situation entsteht praktisch nur, wenn root ein Array wäre. Für OWM ist root ein Objekt.
            # Fallback: behandeln als anonyme Arrayebene mit Key "<root_list>".
            yield from _walk_numeric_leaves(v, prefix + [ArrIdx("<root_list>", i)])
    else:
        if _is_number(node):
            # in float casten für vereinheitlichte Handhabung (Loxone nimmt \v, Skalen egal)
            try:
                val = float(node)
            except Exception:
                return
            yield (prefix, val)

# ===================== Suchstring- und Titelbau =====================

def _xml_escape_attr(s: str) -> str:
    # Für XML-Attribute: &, <, >, "
    return html_escape(s, quote=True)


def _quoted_key(k: str) -> str:
    # "key" ⇒ &quot;key&quot;
    return f"&quot;{_xml_escape_attr(k)}&quot;"


def build_check_string(path: Sequence[PathToken]) -> str:
    """Baut den Loxone-Suchstring (bereits XML-escaped für Anführungszeichen)."""
    parts: List[str] = []
    i_quote = "\\i"  # Literal Backslash + i
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
    # Breite je Key anhand max Länge; min 1
    out: Dict[str, int] = {}
    for k, n in arr_len.items():
        if n <= 0:
            w = 1
        else:
            w = max(1, len(str(n - 1)))
        out[k] = w
    return out


def build_title(path: Sequence[PathToken], width_by_key: Dict[str, int]) -> str:
    """Erzeugt den Titel-String nach gewünschtem Muster.
    Beispiele:
      [ObjKey('current'), ObjKey('temp')] -> "owm1c current temp"
      [ArrIdx('daily',2), ObjKey('temp'), ObjKey('max')] -> "owm1c daily[02] temp.max"
    """
    # Segmente: erstes Segment kann key oder key[idx]; danach dot-chain für nachfolgende ObjKeys bis zur nächsten Array-Ebene
    segments: List[str] = []
    dot_chain: List[str] = []

    def flush_chain():
        nonlocal dot_chain
        if dot_chain:
            if segments:
                segments.append(".".join(dot_chain))
            else:
                segments.append(".".join(dot_chain))
            dot_chain = []

    last_was_array = False
    for t in path:
        if isinstance(t, ArrIdx):
            # Beende evtl. laufende dot-chain
            flush_chain()
            w = width_by_key.get(t.key, 1)
            segments.append(f"{t.key}[{t.idx:0{w}d}]")
            last_was_array = True
        elif isinstance(t, ObjKey):
            if not segments or last_was_array:
                # Start eines neuen Bereichs oder direkt nach Array ⇒ eigenes Segment
                segments.append(t.key)
                last_was_array = False
            else:
                # Innerhalb desselben Bereichs ⇒ dot-chain
                dot_chain.append(t.key)
        else:
            raise TypeError("unknown token")

    # Final flush
    flush_chain()

    return f"{PREFIX} " + " ".join(segments)

# ===================== XML-Ausgabe =====================

def write_xml(commands: List[Tuple[str, str]], out_path: Path) -> None:
    """Schreibt die VirtualInHttp XML-Datei.
    commands: Liste aus (Title, CheckString)
    """
    # Attribute XML-escapen
    title_attr = _xml_escape_attr(ROOT_TITLE)
    addr_attr = _xml_escape_attr(ADDRESS_URL)

    with out_path.open("w", encoding="utf-8") as f:
        f.write("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n")
        f.write(
            f"<VirtualInHttp Title=\"{title_attr}\" Comment=\"\" Address=\"{addr_attr}\" HintText=\"\" PollingTime=\"{POLLING_TIME}\">\n"
        )
        f.write(f"\t<Info templateType=\"2\" minVersion=\"{MINISERVER_MIN_VERSION}\"/>\n")
        for title, check in commands:
            f.write(
                "\t<VirtualInHttpCmd "
                f"Title=\"{_xml_escape_attr(title)}\" Comment=\"\" "
                f"Check=\"{check}\" Signed=\"{SIGNED}\" Analog=\"{ANALOG}\" "
                f"SourceValLow=\"{SRC_LOW}\" DestValLow=\"{DST_LOW}\" "
                f"SourceValHigh=\"{SRC_HIGH}\" DestValHigh=\"{DST_HIGH}\" "
                f"DefVal=\"{DEF_VAL}\" MinVal=\"{MIN_VAL}\" MaxVal=\"{MAX_VAL}\" "
                f"Unit=\"{_xml_escape_attr(UNIT)}\" HintText=\"\"/>\n"
            )
        f.write("</VirtualInHttp>\n")

# ===================== Hauptlogik =====================

def build_commands_from_json(root: Any) -> List[Tuple[str, str]]:
    # 1) Array-Längen sammeln
    arr_len: Dict[str, int] = {}
    _collect_array_lengths(root, arr_len)
    width_by_key = _index_width_map(arr_len)

    # 2) Numerische Leaves sammeln
    leaves = list(_walk_numeric_leaves(root, []))

    # 3) Für jeden Pfad Titel & Check bauen
    commands: List[Tuple[str, str]] = []
    for path_tokens, _val in leaves:
        # Filter: Pfad muss mindestens einen ObjKey enthalten (sonst <root_list>)
        if any(isinstance(t, ObjKey) for t in path_tokens):
            title = build_title(path_tokens, width_by_key)
            check = build_check_string(path_tokens)
            commands.append((title, check))
    # Optional: stabil sortieren für deterministische Ausgabe
    commands.sort(key=lambda x: x[0])
    return commands


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Erzeuge Loxone-VIH-XML aus Beispiel-JSON")
    p.add_argument("input_json", type=Path, help="Pfad zum Beispiel-JSON")
    p.add_argument("output_xml", type=Path, help="Zielpfad der XML-Vorlage")
    args = p.parse_args(argv)

    try:
        data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Fehler beim Lesen/Parsen von JSON: {e}", file=sys.stderr)
        return 2

    cmds = build_commands_from_json(data)
    try:
        write_xml(cmds, args.output_xml)
    except Exception as e:
        print(f"Fehler beim Schreiben der XML: {e}", file=sys.stderr)
        return 3

    print(f"OK: {len(cmds)} Befehle erzeugt -> {args.output_xml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
