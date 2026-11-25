"""Read open-access dissertation PDFs for lineage ties the metadata misses.

Sources (--source):
  hal   open French sociology theses on HAL/TEL (structured director field)
  core  CORE theses mentioning a "department of sociology" (PDF links; worldwide, English-heavy)

For each thesis: download the PDF (cached outside iCloud, deleted after reading), take the first
25 pages (pdftotext; Tesseract OCR for pages with no text layer), and find people already in the
data who are named there. Each mention is labelled by where it appears:
  advisor  within ~80 characters of advisor / chair / supervisor / directeur / promoteur
  jury     inside the jury / committee / approval page
  ack      inside the acknowledgments ("Remerciements", "Acknowledgments", "Danksagung")
Mentions are dropped when the person was active 45+ years before the thesis (a cited classic, not
a mentor), or when they are the student or a recorded director.

Output (appended, resumable): data/external/dissertation_text_mentions.parquet, one row per
(thesis, named person): source, thesis_id, year, title, student_name, student_pid, named_pid,
section, snippet, url.
Usage: python -I scripts/read_dissertations.py --source hal|core [--limit N]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import httpx
import pandas as pd
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path(tempfile.gettempdir()) / "lineage_dissertation_pdfs"
OUT = ROOT / "data" / "external" / "dissertation_text_mentions.parquet"
DONE = ROOT / "data" / "external" / "dissertation_text_done.json"
UA = {"User-Agent": "academic-lineage-research/0.1"}
SRC = sys.argv[sys.argv.index("--source") + 1] if "--source" in sys.argv else "hal"
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
PAGES, CLASSIC_GAP = 25, 45

ACK = re.compile(r"(remerciements|acknowledg(e)?ments?|danksagung|agradecimientos|ringraziamenti)", re.I)
JURY = re.compile(r"(composition du jury|membres du jury|jury\s*:|dissertation committee|doctoral committee|committee members|"
                  r"approved by|approval page|examining committee|readers?\s*:|thesis committee|supervisory committee)", re.I)
# thesis-direction wording only: "directeur/directrice de recherche" is a CNRS job title, not a role
ADV = re.compile(r"(advis(o|e)r|committee chair|chair of (my|the) (dissertation )?committee|supervis(or|ed by)|"
                 r"directeur de these|directrice de these|direction de (ma |cette )?these|sous la direction|co-?direct|"
                 r"promoteur|betreuer|doktorvater|doktormutter)", re.I)


def norm(s):
    s = unicodedata.normalize("NFKD", s if isinstance(s, str) else "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z]+", " ", s).strip()


def person_name(raw):
    """'Last, First' -> 'first last' tokens."""
    if not isinstance(raw, str):
        return ""
    if "," in raw:
        last, _, first = raw.partition(",")
        raw = f"{first} {last}"
    return norm(re.sub(r"\(.*?\)", "", raw))


def load_people():
    d = json.loads((ROOT / "explorer" / "data" / "lineage.json").read_text())
    idx, year = defaultdict(set), {}
    for r in d["people"]:
        t = norm(r[1]).split()
        if len(r) > 13 and r[13]:
            year[r[0]] = r[13]
        if len(t) >= 2 and len(t[0]) > 1 and len(t[-1]) > 2:
            idx[f"{t[0]} {t[-1]}"].add(r[0])
            if len(t) > 2:
                idx[" ".join(t)].add(r[0])
    names = {k: next(iter(v)) for k, v in idx.items() if len(v) == 1}
    # pattern per first letter keeps the scan fast: only names whose first token appears in the text are tried
    by_first = defaultdict(list)
    for k, pid in names.items():
        by_first[k.split()[0]].append((k, pid))
    return names, by_first, year


def page_texts(pdf: Path) -> tuple[list[str], int]:
    out, ocr = [], 0
    for p in range(1, PAGES + 1):
        r = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-layout", str(pdf), "-"], capture_output=True, text=True)
        if r.returncode != 0:
            break
        txt = r.stdout
        if len(txt.strip()) < 80:  # no text layer: OCR the page
            with tempfile.TemporaryDirectory() as td:
                subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", "200", "-png", str(pdf), f"{td}/pg"], capture_output=True)
                pngs = list(Path(td).glob("pg*.png"))
                if pngs:
                    txt = subprocess.run(["tesseract", str(pngs[0]), "-", "-l", "eng"], capture_output=True, text=True).stdout
                    ocr += 1
        out.append(txt)
    return out, ocr


def sections(full: str) -> list[tuple[str, str]]:
    """(label, text) spans worth reading. Jury pages are short; acknowledgments run longer."""
    spans = []
    for m in JURY.finditer(full):  # a jury page is short, and ends where the acknowledgments begin
        chunk = full[m.start(): m.start() + 1200]
        a = ACK.search(chunk, 20)
        spans.append(("jury", chunk[: a.start()] if a else chunk))
    spans += [("ack", full[m.start(): m.start() + 5000]) for m in ACK.finditer(full)]
    return spans


def find_mentions(full, by_first, year, thesis_year, exclude):
    found = {}
    for label, span in sections(full):
        t = " " + norm(span) + " "
        toks = set(t.split())
        for first in toks:
            for key, pid in by_first.get(first, ()):
                pos = t.find(f" {key} ")
                if pos < 0 or pid in exclude or key in exclude:
                    continue
                y = year.get(pid)
                if thesis_year and y and y < thesis_year - CLASSIC_GAP:
                    continue  # a cited classic, not a mentor
                window = t[max(0, pos - 80): pos + len(key) + 80]
                lab = "advisor" if ADV.search(window) else label
                rank = {"advisor": 0, "jury": 1, "ack": 2}
                if pid not in found or rank[lab] < rank[found[pid][0]]:
                    found[pid] = (lab, window.strip()[:220])
    return found


_robots = {}


def allowed(url):
    """Respect each host's robots.txt (cached per host). Unreachable robots.txt -> allowed."""
    from urllib.parse import urlparse
    from urllib.robotparser import RobotFileParser
    host = urlparse(url)
    key = f"{host.scheme}://{host.netloc}"
    if key not in _robots:
        rp = RobotFileParser()
        try:
            r = httpx.get(key + "/robots.txt", headers=UA, timeout=20, follow_redirects=True)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except httpx.HTTPError:
            rp.parse([])
        _robots[key] = rp
    return _robots[key].can_fetch(UA["User-Agent"], url)


def hal_docs():
    rows, start = [], 0
    while True:
        r = httpx.get("https://api.archives-ouvertes.fr/search/", params={
            "q": "*:*", "fq": ["docType_s:THESE", "domainAllCode_s:shs.socio"], "rows": 500, "start": start,
            "fl": "halId_s,title_s,authFullName_s,director_s,fileMain_s,producedDateY_i", "sort": "docid asc", "wt": "json"},
            headers=UA, timeout=120)
        docs = r.json()["response"]["docs"]
        rows += [{"id": d["halId_s"], "url": d.get("fileMain_s"), "year": d.get("producedDateY_i"),
                  "title": (d.get("title_s") or [""])[0], "student": (d.get("authFullName_s") or [""])[0],
                  "directors": [re.sub(r"\(.*\)", "", x).strip() for x in d.get("director_s", [])]} for d in docs if d.get("fileMain_s")]
        start += 500
        if len(docs) < 500:
            return rows
        time.sleep(1)


def core_docs():
    key = dotenv_values(ROOT / ".env").get("CORE_API_KEY")
    H = {**UA, "Authorization": f"Bearer {key}"}
    q = 'documentType:"thesis" AND "department of sociology" AND yearPublished>=1950'
    rows, offset = [], 0
    with httpx.Client(headers=H, timeout=120, follow_redirects=True) as c:
        while True:
            for attempt in range(6):
                r = c.get("https://api.core.ac.uk/v3/search/works/", params={"q": q, "limit": 100, "offset": offset})
                if r.status_code == 200:
                    break
                time.sleep(min(60, 5 * 2 ** attempt))
            else:
                break
            res = r.json().get("results", [])
            for w in res:
                # core.ac.uk/download blocks automated fetches (403), so use the original repository's file
                src = [u for u in (w.get("sourceFulltextUrls") or []) if u.startswith("http")]
                if src:
                    rows.append({"id": f"core:{w['id']}", "url": src[0], "year": w.get("yearPublished"),
                                 "title": w.get("title") or "", "student": ((w.get("authors") or [{}])[0]).get("name", ""),
                                 "directors": []})
            offset += 100
            if len(res) < 100 or offset >= 10_000:
                return rows
            time.sleep(1.2)
    return rows


def main():
    CACHE.mkdir(exist_ok=True)
    names, by_first, year = load_people()
    docs = hal_docs() if SRC == "hal" else core_docs()
    done = set(json.loads(DONE.read_text())) if DONE.exists() else set()
    todo = [d for d in docs if d["id"] not in done][: LIMIT or None]
    print(f"{SRC}: {len(docs):,} theses with PDFs, {len(todo):,} to read", flush=True)
    old = pd.read_parquet(OUT) if OUT.exists() else pd.DataFrame()
    if len(old) and "source" in old:
        old = old[old.thesis_id.isin(done)]  # keep rows of finished theses only
    new_rows, ocr_total, t0 = [], 0, time.time()
    with httpx.Client(headers=UA, timeout=180, follow_redirects=True) as c:
        for i, d in enumerate(todo, 1):
            pdf = CACHE / (re.sub(r"[^A-Za-z0-9_.-]", "_", d["id"]) + ".pdf")
            if not allowed(d["url"]):
                done.add(d["id"]); continue  # the host's robots.txt disallows it
            try:
                if not pdf.exists():
                    time.sleep(1.0)
                    resp = c.get(d["url"])
                    if resp.status_code != 200 or resp.content[:5] != b"%PDF-":
                        done.add(d["id"]); continue
                    pdf.write_bytes(resp.content)
                pages, ocr = page_texts(pdf)
                ocr_total += ocr
            except (httpx.HTTPError, OSError):
                continue
            finally:
                pass
            full = "\n".join(pages)
            student = person_name(d["student"])
            st = student.split()
            student_pid = names.get(f"{st[0]} {st[-1]}") if len(st) >= 2 else None
            exclude = {student_pid} | {f"{x.split()[0]} {x.split()[-1]}" for x in map(person_name, d["directors"]) if len(x.split()) >= 2}
            exclude |= {names.get(k) for k in list(exclude) if isinstance(k, str)}
            for pid, (sec, snip) in find_mentions(full, by_first, year, d["year"], exclude).items():
                new_rows.append({"source": SRC, "thesis_id": d["id"], "year": d["year"], "title": d["title"][:300],
                                 "student_name": d["student"], "student_pid": student_pid, "named_pid": pid,
                                 "section": sec, "snippet": snip, "url": d["url"]})
            done.add(d["id"])
            pdf.unlink(missing_ok=True)  # keep nothing but the extracted mentions
            if i % 25 == 0 or i == len(todo):
                pd.concat([old, pd.DataFrame(new_rows)], ignore_index=True).to_parquet(OUT, index=False)
                DONE.write_text(json.dumps(sorted(done)))
                print(f"  {i:,}/{len(todo):,} read, {len(new_rows):,} mentions, {ocr_total} OCR pages ({time.time() - t0:,.0f}s)", flush=True)
    df = pd.concat([old, pd.DataFrame(new_rows)], ignore_index=True)
    df.to_parquet(OUT, index=False)
    DONE.write_text(json.dumps(sorted(done)))
    if len(df):
        print(df[df.source == SRC].section.value_counts().to_dict(), "| with known student:", int(df[df.source == SRC].student_pid.notna().sum()))


if __name__ == "__main__":
    main()
