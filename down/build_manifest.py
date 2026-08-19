#!/usr/bin/env python3
"""Build de-duplicated download manifest: Level 2 + Level 1+2 processed only."""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JSON_PATH = ROOT.parent / "enrich_all.json"
OUT = ROOT / "manifest.tsv"
LOGIN_OUT = ROOT / "login_urls.tsv"

KEEP_LEVELS = {"Level 2", "Level 1+2"}
# kinds that can hold processed matrices in this cohort
KEEP_KINDS = {"AE", "STDS", "GSE", "SCP", "CNP"}


def default_page(kind: str, acc: str) -> str:
    k, a = kind.upper(), acc or ""
    return {
        "AE": f"https://www.ebi.ac.uk/biostudies/arrayexpress/studies/{a}",
        "STDS": f"https://db.cngb.org/stomics/datasets/{a}",
        "GSE": f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={a}",
        "SCP": f"https://singlecell.broadinstitute.org/single_cell/study/{a}",
        "CNP": f"https://db.cngb.org/data_resources/project/{a}/",
    }.get(k, "")


def main() -> None:
    if not JSON_PATH.exists():
        sys.exit(f"missing {JSON_PATH}")
    papers = json.loads(JSON_PATH.read_text())

    # accession -> linked STDS (for CNP skip)
    cnp_to_stds: dict[str, set[str]] = defaultdict(set)
    stds_set: set[str] = set()
    for r in papers:
        for repo in r.get("repos") or []:
            if repo.get("kind") == "CNP" and repo.get("linked_stds"):
                cnp_to_stds[repo.get("id") or ""].add(repo["linked_stds"])
        for d in r.get("dataset_rows") or []:
            if d.get("kind") == "STDS" and d.get("accession"):
                stds_set.add(d["accession"])

    rows: dict[tuple[str, str], dict] = {}
    for r in papers:
        doi = r.get("doi") or ""
        for s in r.get("sample_rows") or []:
            lv = s.get("file_level")
            kind = (s.get("parent_kind") or "").upper()
            acc = s.get("parent_accession") or ""
            if lv not in KEEP_LEVELS or kind not in KEEP_KINDS or not acc:
                continue
            key = (kind, acc)
            rec = rows.setdefault(
                key,
                {
                    "kind": kind,
                    "accession": acc,
                    "file_level": set(),
                    "file_format": s.get("file_format") or "",
                    "page_url": default_page(kind, acc),
                    "download_url": "",
                    "n_sample_rows": 0,
                    "dois": set(),
                },
            )
            rec["file_level"].add(lv)
            rec["n_sample_rows"] += 1
            rec["dois"].add(doi)
            rec["page_url"] = default_page(kind, acc)
            dl = s.get("download_url") or ""
            if any(
                dl.lower().split("?")[0].endswith(ext)
                for ext in (".tar.gz", ".h5ad", ".h5", ".gef", ".zip", ".mtx.gz")
            ):
                rec["download_url"] = dl

    out_rows = []
    login_rows = []
    for (kind, acc), rec in sorted(rows.items()):
        skip = ""
        batch = {"AE": "A", "STDS": "B", "SCP": "C", "CNP": "D", "GSE": "E"}[kind]
        how = {
            "AE": "python3 download_ae.py",
            "GSE": "python3 download_geo.py",
            "STDS": "login CNGBdb; download gef/h5ad from dataset page",
            "SCP": "login Broad SCP; download h5ad/Seurat from study page",
            "CNP": "login CNGBdb; processed matrices only (skip FASTQ)",
        }[kind]
        if kind == "CNP":
            linked = cnp_to_stds.get(acc) or set()
            already = sorted(x for x in linked if x in stds_set)
            if already:
                skip = "linked_STDS_already_in_batch_B:" + ",".join(already)
                how = "SKIP — use STDS download of " + ",".join(already)
        levels = "Level 1+2" if "Level 1+2" in rec["file_level"] else "Level 2"
        dest = f"data/{kind}/{acc}"
        page = rec["page_url"] or default_page(kind, acc)
        row = {
            "batch": batch,
            "kind": kind,
            "accession": acc,
            "file_level": levels,
            "n_sample_rows": rec["n_sample_rows"],
            "n_papers": len(rec["dois"]),
            "dois": "; ".join(sorted(rec["dois"])),
            "file_format": (rec["file_format"] or "")[:120],
            "page_url": page,
            "example_download_url": rec["download_url"],
            "dest_dir": dest,
            "how": how,
            "skip_reason": skip,
        }
        out_rows.append(row)
        if kind in ("STDS", "SCP", "CNP") and not skip:
            login_rows.append(
                {
                    "kind": kind,
                    "accession": acc,
                    "page_url": page,
                    "dest_dir": dest,
                    "note": how,
                }
            )

    ROOT.mkdir(parents=True, exist_ok=True)
    fields = list(out_rows[0].keys()) if out_rows else []
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t")
        w.writeheader()
        w.writerows(out_rows)
    with LOGIN_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["kind", "accession", "page_url", "dest_dir", "note"], delimiter="\t"
        )
        w.writeheader()
        w.writerows(login_rows)

    by = defaultdict(int)
    skip_n = 0
    for r in out_rows:
        by[r["kind"]] += 1
        if r["skip_reason"]:
            skip_n += 1
    print(f"wrote {OUT}  ({len(out_rows)} unique datasets)")
    print("  by kind:", dict(by))
    print(f"  CNP skip (already STDS): {skip_n}")
    print(f"wrote {LOGIN_OUT}  ({len(login_rows)} login-gated pages)")
    print("to_download (not skipped):", len(out_rows) - skip_n)


if __name__ == "__main__":
    main()
