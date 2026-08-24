#!/usr/bin/env python3
"""Batch E: download GEO Series supplementary files.

Default mode: download **whatever is in suppl/** (txt.gz / xlsx / rds / tar.gz / RAW.tar / …).
Already-downloaded files are skipped (resume-friendly).

  python3 download_geo.py                 # all GSE in manifest
  python3 download_geo.py --missing-only  # skip GSE dirs that already have files
  python3 download_geo.py --limit 5
  python3 download_geo.py --acc GSE109796
  python3 download_geo.py --processed-only  # old strict filter (h5/mtx/…)
  python3 download_geo.py --skip-raw        # all except *_RAW.tar / fastq / bam / sra
"""

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
UA = "Mozilla/5.0 (compatible; stoc-geo-download/2.0)"

# Old strict keep list (only used with --processed-only)
KEEP_EXT = re.compile(
    r"\.(h5ad|h5|hdf5|gef|mtx|mtx\.gz|rds|rda|rdata|csv\.gz|tsv\.gz)$",
    re.I,
)
KEEP_NAME = re.compile(r"processed|matrix|counts|expression|seurat|anndata", re.I)
RAWISH = re.compile(r"fastq|\.fq\.|_RAW\.tar|\.sra\b|\.bam\b|\.bai\b", re.I)
NOISE = re.compile(r"^(filelist\.txt|index\.html)$", re.I)


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
        # best-effort size hint
        cl = r.headers.get("Content-Length")
        if cl and cl.isdigit():
            print(f"    size≈{int(cl) / (1024 ** 2):.1f} MB", flush=True)
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)


def want(name: str, *, processed_only: bool, skip_raw: bool) -> bool:
    base = name.split("?")[0]
    if not base or base.endswith("/"):
        return False
    if NOISE.match(base):
        return False
    if processed_only:
        if RAWISH.search(base):
            return False
        if KEEP_EXT.search(base):
            return True
        if base.lower().endswith(".zip") and KEEP_NAME.search(base):
            return True
        if (
            base.lower().endswith(".tar.gz")
            and KEEP_NAME.search(base)
            and "raw" not in base.lower()
        ):
            return True
        return False
    # default: everything GEO put in suppl/
    if skip_raw and RAWISH.search(base):
        return False
    return True


def list_suppl_files(
    gse: str, *, processed_only: bool, skip_raw: bool
) -> list[tuple[str, str]]:
    """Return (filename, absolute_url)."""
    last_err: Exception | None = None
    for idx in suppl_index_urls(gse):
        try:
            html = http_get(idx).decode("utf-8", "replace")
        except Exception as e:
            last_err = e
            continue
        p = HrefParser()
        p.feed(html)
        out: list[tuple[str, str]] = []
        base = idx if idx.endswith("/") else idx + "/"
        for h in p.hrefs:
            if h in ("../", "/") or h.startswith("?"):
                continue
            name = h.split("/")[-1]
            if not want(name, processed_only=processed_only, skip_raw=skip_raw):
                continue
            url = h if h.startswith("http") else urllib.request.urljoin(base, h)
            out.append((name, url))
        # directory existed (even if empty after filter)
        return out
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


def has_any_file(dest_dir: Path) -> bool:
    if not dest_dir.is_dir():
        return False
    for p in dest_dir.rglob("*"):
        if p.is_file() and p.stat().st_size > 0 and not p.name.endswith(".part"):
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="max GSE to fetch (0=all)")
    ap.add_argument("--acc", default="", help="single GSE accession")
    ap.add_argument(
        "--missing-only",
        action="store_true",
        help="skip GSE directories that already contain at least one file",
    )
    ap.add_argument(
        "--processed-only",
        action="store_true",
        help="old behavior: only h5/mtx/rds/… matrices",
    )
    ap.add_argument(
        "--skip-raw",
        action="store_true",
        help="download all suppl except RAW.tar / fastq / bam / sra",
    )
    args = ap.parse_args()
    if not MANIFEST.exists():
        sys.exit("run python3 build_manifest.py first")
    LOG.mkdir(parents=True, exist_ok=True)

    mode = "processed-only" if args.processed_only else ("all-except-raw" if args.skip_raw else "all-suppl")
    print(f"mode={mode} data={DATA}", flush=True)

    accs = load_accs(args.acc or None)
    if args.missing_only:
        before = len(accs)
        accs = [g for g in accs if not has_any_file(DATA / g)]
        print(f"missing-only: {len(accs)}/{before} GSE still need files", flush=True)
    if args.limit:
        accs = accs[: args.limit]

    ok, fail, empty = [], [], []
    for i, gse in enumerate(accs, 1):
        dest_dir = DATA / gse
        print(f"[{i}/{len(accs)}] {gse}", flush=True)
        try:
            files = list_suppl_files(
                gse, processed_only=args.processed_only, skip_raw=args.skip_raw
            )
            if not files:
                empty.append((gse, "suppl empty or nothing matched filter"))
                print("  (no files in suppl / after filter)")
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
    print("logs: log/geo_ok.tsv log/geo_fail.tsv log/geo_empty.tsv")


if __name__ == "__main__":
    main()
