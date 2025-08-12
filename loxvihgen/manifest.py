# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_POLL = 1200

def manifest_path(project: str) -> Path:
    return Path(f"{project}.vih.json")

def response_guess_path(project: str) -> Optional[Path]:
    cand_json = Path(f"{project}.response.json")
    cand_xml  = Path(f"{project}.response.xml")
    if cand_json.exists(): return cand_json
    if cand_xml.exists(): return cand_xml
    return None

def rules_default_path(project: str) -> Path:
    return Path(f"{project}.rules.json")

def output_default_path(project: str, prefix: Optional[str]) -> Path:
    return Path(f"VI_{project}--{prefix}.xml") if prefix else Path(f"VI_{project}.xml")

def load_manifest(project: str) -> Dict[str, Any]:
    p = manifest_path(project)
    if not p.exists():
        return {
            "project": project,
            "source": {"url": None, "response": None},
            "rules": str(rules_default_path(project)),
            "build": {"title": project, "name_separator": " ", "polling_time": DEFAULT_POLL, "address_url": None},
            "prefixes": []
        }
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {
            "project": project,
            "source": {"url": None, "response": None},
            "rules": str(rules_default_path(project)),
            "build": {"title": project, "name_separator": " ", "polling_time": DEFAULT_POLL, "address_url": None},
            "prefixes": []
        }

def save_manifest(project: str, data: Dict[str, Any]) -> None:
    manifest_path(project).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
