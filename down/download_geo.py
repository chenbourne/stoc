#!/usr/bin/env python3
"""Batch E: download GEO Series supplementary processed matrices (no FASTQ/RAW)."""

from __future__ import annotations

import argparse
import csv
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.tsv"
DATA = ROOT / "data" / "GSE"
LOG = ROOT / "log"
CTX = ssl._create_unverified_context()
UA = "Mozilla/5.0 (compatible; stoc-l2-download/1.0)"

KEEP_EXT = re.compile(
    r"\.(h5ad|h5|hdf5|gef|mtx|mtx\.gz|rds|rda|rdata|csv\.gz|tsv\.gz)$",
    re.I,
)
KEEP_NAME = re.compile(r"processed|matrix|counts|expression|seurat|anndata", re.I)
SKIP = re.compile(r"fastq|\.fq\.|_RAW\.tar|\.sra\b|\.bam\b|\.bai\b", re.I)


class HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        for k, v in attrs:
            if k == "href" and v:
                self.hrefs.append(v)


def series_block(gse: str) -> str:
    n = int(re.sub(r"\D", "", gse))
    return f"GSE{n // 1000}nnn"


def suppl_index_urls(gse: str) -> list[str]:
    block = series_block(gse)
    return [
        f"https://ftp.ncbi.nlm.nih.gov/geo/series/{block}/{gse}/suppl/",
        f"https://ftp.ncbi.nlm.nih.gov/geo/series/{block}/{gse}/suppl",
    ]


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return r.read()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, context=CTX, timeout=600) as r, tmp.open("wb") as f:
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)


def want(name: str) -> bool:
    base = name.split("?")[0]
    if SKIP.search(base):
        return False
    if KEEP_EXT.search(base):
        return True
    if base.lower().endswith(".zip") and KEEP_NAME.search(base):
        return True
    if base.lower().endswith(".tar.gz") and KEEP_NAME.search(base) and "raw" not in base.lower():
        return True
    return False


def list_suppl_files(gse: str) -> list[tuple[str, str]]:
    """Return (filename, absolute_url)."""
    last_err = None
    for idx in suppl_index_urls(gse):
        try:
            html = http_get(idx).decode("utf-8", "replace")
        except Exception as e:
            last_err = e
            continue
        p = HrefParser()
        p.feed(html)
        out = []
        base = idx if idx.endswith("/") else idx + "/"
        for h in p.hrefs:
            if h in ("../", "/") or h.startswith("?"):
                continue
            name = h.split("/")[-1]
            if not name or name.endswith("/"):
                continue
            if not want(name):
                continue
            url = h if h.startswith("http") else urllib.request.urljoin(base, h)
            out.append((name, url))
        if out:
            return out
        # directory existed but no keep files
        return []
    raise last_err or RuntimeError("no GEO suppl index")


def load_accs(only: str | None) -> list[str]:
    accs = []
    with MANIFEST.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["kind"] != "GSE" or row.get("skip_reason"):
                continue
            if only and row["accession"] != only:
                continue
            accs.append(row["accession"])
    return accs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max GSE to fetch (0=all)")
    ap.add_argument("--acc", default="", help="single GSE accession")
    args = ap.parse_args()
    if not MANIFEST.exists():
        sys.exit("run python3 build_manifest.py first")
    LOG.mkdir(parents=True, exist_ok=True)
    accs = load_accs(args.acc or None)
    if args.limit:
        accs = accs[: args.limit]
    ok, fail, empty = [], [], []
    for i, gse in enumerate(accs, 1):
        dest_dir = DATA / gse
        print(f"[{i}/{len(accs)}] {gse}", flush=True)
        try:
            files = list_suppl_files(gse)
            if not files:
                empty.append((gse, "suppl has no processed matrix matching filter"))
                print("  (no matching processed files)")
                continue
            n = 0
            for name, url in files:
                dest = dest_dir / name
                if dest.exists() and dest.stat().st_size > 0:
                    print(f"  exists {name}")
                    n += 1
                    continue
                print(f"  get {name}", flush=True)
                download(url, dest)
                n += 1
                time.sleep(0.4)
            ok.append((gse, n))
        except urllib.error.HTTPError as e:
            fail.append((gse, f"HTTP {e.code}"))
            print(f"  FAIL HTTP {e.code}")
        except Exception as e:
            fail.append((gse, str(e)))
            print(f"  FAIL {e}")
        time.sleep(0.3)
    (LOG / "geo_ok.tsv").write_text(
        "accession\tn_files\n" + "".join(f"{a}\t{n}\n" for a, n in ok), encoding="utf-8"
    )
    (LOG / "geo_fail.tsv").write_text(
        "accession\terror\n" + "".join(f"{a}\t{e}\n" for a, e in fail), encoding="utf-8"
    )
    (LOG / "geo_empty.tsv").write_text(
        "accession\tnote\n" + "".join(f"{a}\t{e}\n" for a, e in empty), encoding="utf-8"
    )
    print(f"done ok={len(ok)} empty={len(empty)} fail={len(fail)}")


if __name__ == "__main__":
    main()
