#!/usr/bin/env python3
"""Batch A: download ArrayExpress / BioStudies processed files (no FASTQ/BAM)."""

from __future__ import annotations

import csv
import json
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.tsv"
DATA = ROOT / "data" / "AE"
LOG = ROOT / "log"
CTX = ssl._create_unverified_context()
UA = "Mozilla/5.0 (compatible; stoc-l2-download/1.0)"

SKIP_NAME = re.compile(
    r"fastq|\.fq\.|sdrf|idf\.txt|\.bam(\.bai)?$|\.bai$",
    re.I,
)
KEEP_NAME = re.compile(
    r"processed|\.tar\.gz$|\.h5ad$|\.h5$|\.hdf5$|\.gef$|matrix|\.zip$",
    re.I,
)


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, context=CTX, timeout=90) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, context=CTX, timeout=600) as r, dest.open("wb") as f:
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def list_files(aid: str) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        url = (
            f"https://www.ebi.ac.uk/biostudies/api/v1/studies/{aid}/files"
            f"?start={offset}&pageSize=100"
        )
        fl = http_json(url)
        batch = fl.get("items") or []
        items.extend(batch)
        pag = fl.get("pagination") or {}
        total = pag.get("total") or len(items)
        offset += len(batch)
        if not batch or offset >= total:
            break
    return items


def file_url(aid: str, name: str) -> str:
    return f"https://www.ebi.ac.uk/biostudies/files/{aid}/{name}"


def main() -> None:
    if not MANIFEST.exists():
        sys.exit("run python3 build_manifest.py first")
    LOG.mkdir(parents=True, exist_ok=True)
    accs = []
    with MANIFEST.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["kind"] == "AE" and not row.get("skip_reason"):
                accs.append(row["accession"])
    ok, fail = [], []
    for aid in accs:
        dest_dir = DATA / aid
        print(f"== {aid}", flush=True)
        try:
            items = list_files(aid)
            saved = 0
            for it in items:
                name = it.get("Name") or ""
                desc = it.get("Description") or ""
                blob = f"{name} {desc}"
                if SKIP_NAME.search(blob):
                    continue
                if not (KEEP_NAME.search(blob) or "processed" in desc.lower()):
                    continue
                dest = dest_dir / Path(name).name
                if dest.exists() and dest.stat().st_size > 0:
                    print(f"  skip exists {dest.name}")
                    saved += 1
                    continue
                url = file_url(aid, name)
                print(f"  get {name}", flush=True)
                download(url, dest)
                saved += 1
                time.sleep(0.2)
            if saved:
                ok.append((aid, saved))
            else:
                fail.append((aid, "no processed files matched"))
        except Exception as e:
            fail.append((aid, str(e)))
            print(f"  FAIL {e}")
    (LOG / "ae_ok.tsv").write_text(
        "accession\tn_files\n" + "".join(f"{a}\t{n}\n" for a, n in ok), encoding="utf-8"
    )
    (LOG / "ae_fail.tsv").write_text(
        "accession\terror\n" + "".join(f"{a}\t{e}\n" for a, e in fail), encoding="utf-8"
    )
    print(f"done ok={len(ok)} fail={len(fail)}")


if __name__ == "__main__":
    main()
