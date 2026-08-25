#!/usr/bin/env python3
"""Download open-access OMIX archives from NGDC (HTTPS).

Reads omix_direct.tsv (or probes open releases). Skips controlled-access OMIX.

  python3 download_omix.py
  python3 download_omix.py --acc OMIX007362
  python3 download_omix.py --limit 2
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIST = ROOT / "omix_direct.tsv"
DATA = ROOT / "data" / "OMIX"
LOG = ROOT / "log"
CTX = ssl._create_unverified_context()
UA = "Mozilla/5.0 (compatible; stoc-omix-download/1.0)"


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return r.read()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, context=CTX, timeout=600) as r, tmp.open("wb") as f:
        cl = r.headers.get("Content-Length")
        if cl and cl.isdigit():
            print(f"    size≈{int(cl) / (1024 ** 2):.1f} MB", flush=True)
        while True:
            chunk = r.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)


def list_https_files(acc: str) -> list[tuple[str, str]]:
    page = f"https://ngdc.cncb.ac.cn/omix/release/{acc}"
    html = http_get(page).decode("utf-8", "replace")
    if re.search(r"Controlled|controlled access|受控", html, re.I) and not re.search(
        r"Open[- ]access|开放获取", html, re.I
    ):
        return []
    links = sorted(
        set(
            re.findall(
                rf"https://download\.cncb\.ac\.cn/OMIX/{re.escape(acc)}/[^\"\'\s<>]+",
                html,
            )
        )
    )
    out = []
    for url in links:
        name = url.rstrip("/").split("/")[-1]
        if name.endswith(".md5"):
            continue
        out.append((name, url))
    return out


def load_accs(only: str | None) -> list[str]:
    if not LIST.exists():
        sys.exit(f"missing {LIST}; run build or use committed omix_direct.tsv")
    accs = []
    with LIST.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            acc = row["accession"]
            if only and acc != only:
                continue
            accs.append(acc)
    return accs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--acc", default="", help="single OMIX accession")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    LOG.mkdir(parents=True, exist_ok=True)
    accs = load_accs(args.acc or None)
    if args.limit:
        accs = accs[: args.limit]

    ok, fail, empty = [], [], []
    for i, acc in enumerate(accs, 1):
        dest_dir = DATA / acc
        print(f"[{i}/{len(accs)}] {acc}", flush=True)
        try:
            files = list_https_files(acc)
            if not files:
                empty.append((acc, "no open HTTPS files (controlled or empty)"))
                print("  (no open files)")
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
                time.sleep(0.3)
            ok.append((acc, n))
        except urllib.error.HTTPError as e:
            fail.append((acc, f"HTTP {e.code}"))
            print(f"  FAIL HTTP {e.code}")
        except Exception as e:
            fail.append((acc, str(e)))
            print(f"  FAIL {e}")
        time.sleep(0.2)

    (LOG / "omix_ok.tsv").write_text(
        "accession\tn_files\n" + "".join(f"{a}\t{n}\n" for a, n in ok), encoding="utf-8"
    )
    (LOG / "omix_fail.tsv").write_text(
        "accession\terror\n" + "".join(f"{a}\t{e}\n" for a, e in fail), encoding="utf-8"
    )
    (LOG / "omix_empty.tsv").write_text(
        "accession\tnote\n" + "".join(f"{a}\t{e}\n" for a, e in empty), encoding="utf-8"
    )
    print(f"done ok={len(ok)} empty={len(empty)} fail={len(fail)}")


if __name__ == "__main__":
    main()
