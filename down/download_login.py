#!/usr/bin/env python3
"""Print / write login-gated download pages (STDS, SCP, CNP). Does not fetch files."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGIN = ROOT / "login_urls.tsv"


def main() -> None:
    if not LOGIN.exists():
        sys.exit("run python3 build_manifest.py first")
    rows = list(csv.DictReader(LOGIN.open(encoding="utf-8"), delimiter="\t"))
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["kind"], []).append(r)
    print("Login-gated processed downloads (open page, sign in, save to dest_dir):\n")
    for kind in ("STDS", "SCP", "CNP"):
        items = by.get(kind, [])
        print(f"=== {kind} ({len(items)}) ===")
        for r in items:
            print(f"  {r['accession']}\n    {r['page_url']}\n    -> {r['dest_dir']}")
        print()
    print("Tip: after you copy a direct file URL, e.g.")
    print("  mkdir -p data/STDS/STDS0000058")
    print("  wget -c -O data/STDS/STDS0000058/xxx.gef 'DIRECT_URL'")


if __name__ == "__main__":
    main()
