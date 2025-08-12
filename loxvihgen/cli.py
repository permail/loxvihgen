# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
import argparse
from pathlib import Path
from typing import Optional, Sequence
from .service import cmd_fetch, cmd_rules, cmd_build, cmd_all

def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="loxvihgen", description="Generate Loxone VI-HTTP XML from JSON/XML responses (project-centric)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("fetch", help="Fetch response for project and update manifest")
    pf.add_argument("project")
    pf.add_argument("-u", "--url", required=False, help="HTTP(S) URL to fetch via GET (optional if manifest has one)")

    pr = sub.add_parser("rules", help="Generate rules skeleton from project's response")
    pr.add_argument("project")
    pr.add_argument("--force", action="store_true", help="Overwrite existing PROJECT.rules.json")

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
