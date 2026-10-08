# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 MLPC Inc.
"""Command line: python -m cite_gate check <claims.json> [--sources DIR] [--json] [--strict]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .check import check_file


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cite-gate",
                                 description="Check that a script's facts are backed by verbatim source quotes.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check a claims file")
    c.add_argument("claims", type=Path, help="claims JSON file")
    c.add_argument("--sources", type=Path, help="directory of <src>.txt files (default: ./sources next to the claims file)")
    c.add_argument("--json", action="store_true", help="print the report as JSON")
    c.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    a = ap.parse_args(argv)

    rep = check_file(a.claims, a.sources)
    if a.json:
        print(json.dumps(rep.as_dict(), ensure_ascii=False, indent=1))
    else:
        print(f"{rep.items} items · {rep.words:,} words · "
              f"{len(rep.failures)} failures · {len(rep.warnings)} warnings")
        for x in rep.failures:
            print(f"  FAIL [{x['item']}] {x['message']}")
        for x in rep.warnings:
            print(f"  warn [{x['item']}] {x['message']}")
    if rep.failures or (a.strict and rep.warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
