# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .builders import JSONCheckStringBuilder, TitleBuilder, VIHBuilder, XMLCheckStringBuilder
from .manifest import (
    DEFAULT_POLL,
    load_manifest,
    manifest_path,
    output_default_path,
    response_guess_path,
    rules_default_path,
    save_manifest,
    workspace_name,
)
from .renderer import ViHttpXmlRenderer
from .rules import Rules, generate_rules_skeleton
from .sources import FormatAdapter

__tool__ = "LoxVIHGen"
DEFAULT_ADDRESS_URL = "http://..."
logger = logging.getLogger(__name__)

# ---- util ----

def _full_comment(
    workspace: Path,
    input_path: Optional[Path],
    output_path: Optional[Path],
    rules_path: Optional[Path],
    opts: Dict[str, Any],
) -> str:
    def _display_name(path: Path) -> str:
        try:
            rel = path.relative_to(workspace)
        except ValueError:
            return str(path)
        return str(rel)

    files = []
    if input_path:
        files.append({"role": "input", "name": _display_name(input_path)})
    if rules_path:
        files.append({"role": "rules", "name": _display_name(rules_path)})
    if output_path:
        files.append({"role": "output", "name": _display_name(output_path)})
    meta = {
        "tool": __tool__,
        "version": __version__,
        "files": files,
        "opts": opts,
    }
    return json.dumps(meta, separators=(",", ":"))


def _is_placeholder_address(value: Any) -> bool:
    return not isinstance(value, str) or value.strip() == "" or value == DEFAULT_ADDRESS_URL


def _sniff_adapter(text: str, source_path: Path) -> FormatAdapter:
    try:
        return FormatAdapter.sniff(text)
    except Exception as exc:
        raise ValueError(f"response is not valid JSON or XML: {source_path}") from exc


def _load_rules_or_error(rules_path: Path) -> Rules:
    try:
        return Rules.load(rules_path if rules_path.exists() else None)
    except json.JSONDecodeError as exc:
        raise ValueError(f"rules file is not valid JSON: {rules_path}") from exc


def _resolve_paths_and_adapter(
    workspace: Path,
    m: Dict[str, Any],
) -> tuple[FormatAdapter, Rules, Path, Path]:
    resp_str = m.get("source", {}).get("response")
    resp_path = workspace / resp_str if isinstance(resp_str, str) and resp_str else None
    if not resp_path or not resp_path.is_file():
        guess = response_guess_path(workspace)
        if not guess:
            raise FileNotFoundError
        resp_path = guess
    text = resp_path.read_text(encoding="utf-8")
    adapter = _sniff_adapter(text, resp_path)
    rules_name = m.get("rules") or rules_default_path(workspace).name
    rules_path = workspace / rules_name
    rules = _load_rules_or_error(rules_path)
    return adapter, rules, resp_path, rules_path


def _load_manifest(workspace: Path) -> Optional[Dict[str, Any]]:
    try:
        return load_manifest(workspace)
    except ValueError as exc:
        logger.error(str(exc))
        return None


def _effective_params(
    workspace: Path,
    m: Dict[str, Any],
    title: Optional[str],
    prefixes: List[str],
    sep: Optional[str],
    poll: Optional[int],
    address_url: Optional[str],
) -> tuple[str, str, int, str, List[str]]:
    b = m.get("build", {})
    eff_title = title or b.get("title") or workspace_name(workspace)
    eff_sep = sep if sep is not None else b.get("name_separator", " ")
    eff_poll = int(poll if poll is not None else b.get("polling_time", DEFAULT_POLL))
    stored_build_addr = b.get("address_url")
    eff_addr = (
        address_url
        or (stored_build_addr if not _is_placeholder_address(stored_build_addr) else None)
        or m.get("source", {}).get("url")
        or DEFAULT_ADDRESS_URL
    )
    prefix_list: List[str] = prefixes if prefixes else list(m.get("prefixes", []))
    if not prefix_list:
        prefix_list = [""]
    return eff_title, eff_sep, eff_poll, eff_addr, prefix_list


def _build_prefix(
    workspace: Path,
    pref: str,
    adapter: FormatAdapter,
    rules: Rules,
    eff_title: str,
    eff_sep: str,
    eff_poll: int,
    eff_addr: str,
    output: Optional[Path],
    prefix_list: List[str],
    resp_path: Path,
    rules_path: Path,
) -> None:
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
        out_path = output_default_path(workspace, pref or None)
    comment = _full_comment(
        workspace,
        resp_path,
        out_path,
        rules_path if rules_path.exists() else None,
        {
            "prefix": pref or "",
            "sep": eff_sep,
            "title": full_title,
            "poll": eff_poll,
            "address_url": eff_addr,
        },
    )
    xml = ViHttpXmlRenderer().render(
        cmds,
        title=full_title,
        address_url=eff_addr,
        polling_time=eff_poll,
        comment_json=comment,
    )
    out_path.write_text(xml, encoding="utf-8")
    logger.info("%d commands → %s", len(cmds), out_path)

# ---- commands ----

def cmd_fetch(workspace_arg: str, url: Optional[str]) -> int:
    workspace = Path(workspace_arg)
    workspace.mkdir(parents=True, exist_ok=True)

    # Resolve URL
    if not url:
        m0 = _load_manifest(workspace)
        if m0 is None:
            return 2
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
    fmt = (
        "json"
        if "json" in ctype
        else (
            "xml"
            if "xml" in ctype
            else ("json" if text.lstrip().startswith(("{", "[")) else "xml")
        )
    )
    resp_path = workspace / f"response.{fmt}"
    resp_path.write_text(text, encoding="utf-8")

    m = _load_manifest(workspace)
    if m is None:
        return 2
    m.setdefault("project", workspace_name(workspace))
    m.setdefault("source", {})
    m["source"]["url"] = url
    m["source"]["response"] = resp_path.name
    m.setdefault("rules", rules_default_path(workspace).name)
    m.setdefault("build", {})
    m["build"].setdefault("title", workspace_name(workspace))
    m["build"].setdefault("name_separator", " ")
    m["build"].setdefault("polling_time", DEFAULT_POLL)
    if _is_placeholder_address(m["build"].get("address_url")):
        m["build"]["address_url"] = None
    m.setdefault("prefixes", [])
    save_manifest(workspace, m)
    logger.info("wrote %s and updated %s", resp_path, manifest_path(workspace))
    return 0


def cmd_rules(workspace_arg: str, force: bool) -> int:
    workspace = Path(workspace_arg)
    m = _load_manifest(workspace)
    if m is None:
        return 2
    resp_str = m.get("source", {}).get("response")
    resp_path = workspace / resp_str if resp_str else None
    if not resp_path or not resp_path.is_file():
        guess = response_guess_path(workspace)
        if not guess:
            logger.error(
                "response missing. Expected %s or %s",
                workspace / "response.json",
                workspace / "response.xml",
            )
            return 6
        resp_path = guess
    text = resp_path.read_text(encoding="utf-8")

    try:
        adapter = _sniff_adapter(text, resp_path)
    except ValueError as exc:
        logger.error(str(exc))
        return 2
    content = generate_rules_skeleton(adapter.source)

    workspace.mkdir(parents=True, exist_ok=True)
    rules_path = rules_default_path(workspace)
    if rules_path.exists() and not force:
        logger.info("%s exists. Use --force to overwrite.", rules_path)
    else:
        rules_path.write_text(content, encoding="utf-8")
        logger.info("rules written → %s", rules_path)

    m.setdefault("source", {})
    m["source"]["response"] = resp_path.name
    m.setdefault("project", workspace_name(workspace))
    m.setdefault("rules", rules_path.name)
    m.setdefault("build", {})
    m["build"].setdefault("title", workspace_name(workspace))
    m["build"].setdefault("name_separator", " ")
    m["build"].setdefault("polling_time", DEFAULT_POLL)
    save_manifest(workspace, m)
    return 0


def cmd_build(
    workspace_arg: str,
    title: Optional[str],
    prefixes: List[str],
    sep: Optional[str],
    poll: Optional[int],
    address_url: Optional[str],
    output: Optional[Path],
) -> int:
    workspace = Path(workspace_arg)
    m = _load_manifest(workspace)
    if m is None:
        return 2
    try:
        adapter, rules, resp_path, rules_path = _resolve_paths_and_adapter(workspace, m)
    except FileNotFoundError:
        logger.error(
            "response missing. Expected %s or %s",
            workspace / "response.json",
            workspace / "response.xml",
        )
        return 6
    except ValueError as exc:
        logger.error(str(exc))
        return 2

    eff_title, eff_sep, eff_poll, eff_addr, prefix_list = _effective_params(
        workspace,
        m,
        title,
        prefixes,
        sep,
        poll,
        address_url,
    )

    try:
        for pref in prefix_list:
            _build_prefix(
                workspace,
                pref,
                adapter,
                rules,
                eff_title,
                eff_sep,
                eff_poll,
                eff_addr,
                output,
                prefix_list,
                resp_path,
                rules_path,
            )
    except ValueError as e:
        logger.error(str(e))
        return 2

    # Persist the current project state so reruns can reuse the same defaults.
    m.setdefault("source", {})
    m["source"]["response"] = resp_path.name
    m.setdefault("project", workspace_name(workspace))
    m["rules"] = rules_path.name
    m.setdefault("build", {})
    stored_build_addr = m["build"].get("address_url")
    m["build"]["title"] = eff_title
    m["build"]["name_separator"] = eff_sep
    m["build"]["polling_time"] = eff_poll
    if not _is_placeholder_address(address_url):
        m["build"]["address_url"] = address_url
    elif not _is_placeholder_address(stored_build_addr):
        m["build"]["address_url"] = stored_build_addr
    else:
        m["build"]["address_url"] = None
    m["prefixes"] = [] if prefix_list == [""] else prefix_list
    save_manifest(workspace, m)
    return 0


def cmd_all(workspace_arg: str, url: str) -> int:
    workspace = Path(workspace_arg)
    e = cmd_fetch(str(workspace), url)
    if e != 0:
        return e
    # create rules if missing
    rules_p = rules_default_path(workspace)
    if not rules_p.exists():
        e = cmd_rules(str(workspace), force=False)
        if e != 0:
            return e
    return cmd_build(
        str(workspace),
        title=None,
        prefixes=[],
        sep=None,
        poll=None,
        address_url=None,
        output=None,
    )
