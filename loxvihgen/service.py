# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import urllib.request
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .sources import FormatAdapter
from .rules import Rules, generate_rules_skeleton
from .builders import TitleBuilder, VIHBuilder, JSONCheckStringBuilder, XMLCheckStringBuilder
from .renderer import ViHttpXmlRenderer
from .manifest import (
    load_manifest, save_manifest, response_guess_path, rules_default_path,
    output_default_path, DEFAULT_POLL
)

__version__ = "2.3.0"
__tool__ = "LoxVIHGen"
logger = logging.getLogger(__name__)

# ---- util ----

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _full_comment(input_path: Optional[Path], output_path: Optional[Path], rules_path: Optional[Path], opts: Dict[str, Any]) -> str:
    files = []
    if input_path: files.append({"role":"input","name":str(input_path)})
    if rules_path: files.append({"role":"rules","name":str(rules_path)})
    if output_path: files.append({"role":"output","name":str(output_path)})
    meta = {"tool": __tool__, "version": __version__, "utc": _now_utc_iso(), "files": files, "opts": opts}
    return json.dumps(meta, separators=(",",":"))


def _resolve_paths_and_adapter(project: str, m: Dict[str, Any]) -> tuple[FormatAdapter, Rules, Path, Path]:
    resp_path = Path(m.get("source", {}).get("response") or "")
    if not resp_path.exists():
        guess = response_guess_path(project)
        if not guess:
            raise FileNotFoundError
        resp_path = guess
    text = resp_path.read_text(encoding="utf-8")
    adapter = FormatAdapter.sniff(text)
    rules_path = Path(m.get("rules") or str(rules_default_path(project)))
    rules = Rules.load(rules_path if rules_path.exists() else None)
    return adapter, rules, resp_path, rules_path


def _effective_params(project: str, m: Dict[str, Any], title: Optional[str], prefixes: List[str], sep: Optional[str], poll: Optional[int], address_url: Optional[str]) -> tuple[str, str, int, str, List[str]]:
    b = m.get("build", {})
    eff_title = title or b.get("title") or project
    eff_sep = sep if sep is not None else b.get("name_separator", " ")
    eff_poll = int(poll if poll is not None else b.get("polling_time", DEFAULT_POLL))
    eff_addr = address_url or b.get("address_url") or m.get("source", {}).get("url") or "http://..."
    prefix_list: List[str] = prefixes if prefixes else list(m.get("prefixes", []))
    if not prefix_list:
        prefix_list = [""]
    return eff_title, eff_sep, eff_poll, eff_addr, prefix_list


def _build_prefix(pref: str, adapter: FormatAdapter, rules: Rules, eff_title: str, eff_sep: str, eff_poll: int, eff_addr: str, project: str, output: Optional[Path], prefix_list: List[str], resp_path: Path, rules_path: Path) -> None:
    tb = TitleBuilder(sep=eff_sep, prefix=(pref or ""), width_by_key=adapter.source.index_widths())
    check_builder = JSONCheckStringBuilder() if adapter.kind == "json" else XMLCheckStringBuilder()
    vih = VIHBuilder(adapter.source, tb, rules, check_builder)
    cmds = vih.build_commands()
    full_title = f"{pref} {eff_title}".strip() if pref else eff_title
    if output is not None and len(prefix_list) == 1:
        out_path = output
    elif output is not None and len(prefix_list) > 1:
        raise ValueError("--output cannot be a single file when multiple prefixes are used.")
    else:
        out_path = output_default_path(project, pref or None)
    comment = _full_comment(resp_path, out_path, rules_path if rules_path.exists() else None,
                            {"prefix": pref or "", "sep": eff_sep, "title": full_title, "poll": eff_poll, "address_url": eff_addr})
    xml = ViHttpXmlRenderer().render(cmds, title=full_title, address_url=eff_addr, polling_time=eff_poll, comment_json=comment)
    out_path.write_text(xml, encoding="utf-8")
    logger.info("%d commands → %s", len(cmds), out_path)

# ---- commands ----

def cmd_fetch(project: str, url: Optional[str]) -> int:
    # Resolve URL
    if not url:
        m0 = load_manifest(project)
        url = m0.get("source", {}).get("url")
        if not url:
            logger.error("no URL provided and none stored in manifest")
            return 2
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read()
            encoding = resp.headers.get_content_charset() or "utf-8"
            text = raw.decode(encoding, errors="replace")
            ctype = (resp.headers.get_content_type() or "").lower()
    except Exception as e:
        logger.error("fetch failed: %s", e)
        return 4
    fmt = "json" if "json" in ctype else ("xml" if "xml" in ctype else ("json" if text.lstrip().startswith(('{','[')) else "xml"))
    resp_path = Path(f"{project}.response.{fmt}")
    resp_path.write_text(text, encoding="utf-8")

    m = load_manifest(project)
    m.setdefault("project", project)
    m.setdefault("source", {})
    m["source"]["url"] = url
    m["source"]["response"] = str(resp_path)
    m.setdefault("rules", str(rules_default_path(project)))
    m.setdefault("build", {})
    m["build"].setdefault("title", project)
    m["build"].setdefault("name_separator", " ")
    m["build"].setdefault("polling_time", DEFAULT_POLL)
    m["build"].setdefault("address_url", url)
    m.setdefault("prefixes", [])
    save_manifest(project, m)
    logger.info("wrote %s and updated %s.vih.json", resp_path, project)
    return 0


def cmd_rules(project: str, force: bool) -> int:
    m = load_manifest(project)
    resp_path = Path(m.get("source", {}).get("response") or "")
    if not resp_path.exists():
        guess = response_guess_path(project)
        if not guess:
            logger.error("response missing. Expected %s.response.json or %s.response.xml", project, project)
            return 6
        resp_path = guess
    text = resp_path.read_text(encoding="utf-8")

    adapter = FormatAdapter.sniff(text)
    content = generate_rules_skeleton(adapter.source)

    rules_path = Path(f"{project}.rules.json")
    if rules_path.exists() and not force:
        logger.info("%s exists. Use --force to overwrite.", rules_path)
    else:
        rules_path.write_text(content, encoding="utf-8")
        logger.info("rules written → %s", rules_path)

    m.setdefault("rules", str(rules_path))
    m.setdefault("build", {})
    m["build"].setdefault("title", project)
    m["build"].setdefault("name_separator", " ")
    m["build"].setdefault("polling_time", DEFAULT_POLL)
    if m["build"].get("address_url") is None and m.get("source", {}).get("url"):
        m["build"]["address_url"] = m["source"]["url"]
    save_manifest(project, m)
    return 0


def cmd_build(project: str, title: Optional[str], prefixes: List[str], sep: Optional[str], poll: Optional[int], address_url: Optional[str], output: Optional[Path]) -> int:
    m = load_manifest(project)
    try:
        adapter, rules, resp_path, rules_path = _resolve_paths_and_adapter(project, m)
    except FileNotFoundError:
        logger.error("response missing. Expected %s.response.json or %s.response.xml", project, project)
        return 6

    eff_title, eff_sep, eff_poll, eff_addr, prefix_list = _effective_params(project, m, title, prefixes, sep, poll, address_url)

    try:
        for pref in prefix_list:
            _build_prefix(pref, adapter, rules, eff_title, eff_sep, eff_poll, eff_addr, project, output, prefix_list, resp_path, rules_path)
    except ValueError as e:
        logger.error(str(e))
        return 2

    # back-fill manifest defaults if missing
    m.setdefault("build", {})
    m["build"].setdefault("title", eff_title)
    m["build"].setdefault("name_separator", eff_sep)
    m["build"].setdefault("polling_time", eff_poll)
    if m["build"].get("address_url") is None and eff_addr:
        m["build"]["address_url"] = eff_addr
    save_manifest(project, m)
    return 0


def cmd_all(project: str, url: str) -> int:
    e = cmd_fetch(project, url)
    if e != 0:
        return e
    # create rules if missing
    rules_p = rules_default_path(project)
    if not rules_p.exists():
        e = cmd_rules(project, force=False)
        if e != 0:
            return e
    return cmd_build(project, title=None, prefixes=[], sep=None, poll=None, address_url=None, output=None)
