# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_POLL = 1200
MANIFEST_FILENAME = "vih.json"
RULES_FILENAME = "rules.json"
RESPONSE_JSON_FILENAME = "response.json"
RESPONSE_XML_FILENAME = "response.xml"
DEFAULT_BUILD = {
    "title": None,
    "name_separator": " ",
    "polling_time": DEFAULT_POLL,
    "address_url": None,
}


def workspace_name(workspace: Path) -> str:
    name = workspace.resolve().name
    return name or str(workspace)


def default_manifest(workspace: Path) -> Dict[str, Any]:
    title = workspace_name(workspace)
    return {
        "project": title,
        "source": {"url": None, "response": None},
        "rules": str(rules_default_path(workspace).name),
        "build": {**DEFAULT_BUILD, "title": title},
        "prefixes": [],
    }


def manifest_path(workspace: Path) -> Path:
    return workspace / MANIFEST_FILENAME


def response_guess_path(workspace: Path) -> Optional[Path]:
    cand_json = workspace / RESPONSE_JSON_FILENAME
    cand_xml = workspace / RESPONSE_XML_FILENAME
    if cand_json.exists():
        return cand_json
    if cand_xml.exists():
        return cand_xml
    return None


def rules_default_path(workspace: Path) -> Path:
    return workspace / RULES_FILENAME


def output_default_path(workspace: Path, prefix: Optional[str]) -> Path:
    return workspace / (f"VI--{prefix}.xml" if prefix else "VI.xml")


def load_manifest(workspace: Path) -> Dict[str, Any]:
    p = manifest_path(workspace)
    if not p.exists():
        return default_manifest(workspace)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest is not valid JSON: {p}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"manifest must contain a JSON object: {p}")

    manifest = default_manifest(workspace)
    manifest.update(raw)
    source = raw.get("source")
    if isinstance(source, dict):
        manifest["source"] = {**manifest["source"], **source}
    build = raw.get("build")
    if isinstance(build, dict):
        manifest["build"] = {**manifest["build"], **build}
    rules = raw.get("rules")
    if isinstance(rules, str):
        manifest["rules"] = rules
    prefixes = raw.get("prefixes")
    if isinstance(prefixes, list):
        manifest["prefixes"] = prefixes
    return manifest


def save_manifest(workspace: Path, data: Dict[str, Any]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    manifest_path(workspace).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
