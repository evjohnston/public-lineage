"""Harvest sociology dissertations with advisor names from open repositories.

Sources
  * OAI-PMH: MINDS@UW (DSpace 8, `dim`), Knowledge@UChicago (InvenioRDM, `datacite`),
    Harvard DASH / Deep Blue / eScholarship (probed; blocked at time of writing).
  * theses.fr public JSON API (the one its own front end uses), discipline ~ "sociologie".

Raw responses are cached under data/raw/dissertations/<source>/ and reused on rerun.
OAI harvests resume from the last cached page; a harvest is marked complete with a
DONE file. Delete a source's cache dir to force a fresh harvest.

Output: data/external/dissertations_edges.parquet, one row per (thesis, advisor).

Usage:
  .venv/bin/python scripts/fetch_dissertations.py                 # all sources
  .venv/bin/python scripts/fetch_dissertations.py --only minds thesesfr
  .venv/bin/python scripts/fetch_dissertations.py --parse-only    # rebuild parquet from cache
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "dissertations"
OUT = ROOT / "data" / "external" / "dissertations_edges.parquet"
UA = "academic-lineage-research/0.1"

OAI_NS = "{http://www.openarchives.org/OAI/2.0/}"
DIM_NS = "{http://www.dspace.org/xmlns/dspace/dim}"
DC4_NS = "{http://datacite.org/schema/kernel-4}"

SOC_RE = re.compile(r"sociolog", re.I)


# --------------------------------------------------------------------------- HTTP
class Robots:
    """Minimal RFC 9309 robots.txt matcher (urllib.robotparser ignores '*' and '$' wildcards).
    Uses the group for our product token if present, else '*'; longest match wins, Allow wins ties."""

    def __init__(self, text: str) -> None:
        groups: list[tuple[list[str], list[tuple[str, str]], float | None]] = []
        agents: list[str] = []
        rules: list[tuple[str, str]] = []
        delay = None
        last_was_agent = False
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if not last_was_agent and agents:
                    groups.append((agents, rules, delay))
                    agents, rules, delay = [], [], None
                agents.append(v.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if k in ("allow", "disallow"):
                rules.append((k, v))
            elif k == "crawl-delay":
                try:
                    delay = float(v)
                except ValueError:
                    pass
        if agents:
            groups.append((agents, rules, delay))
        token = UA.split("/")[0].lower()
        mine = [g for g in groups if token in g[0]] or [g for g in groups if "*" in g[0]]
        self.rules = [r for g in mine for r in g[1]]
        self.crawl_delay = next((g[2] for g in mine if g[2]), None)

    @staticmethod
    def _rx(pat: str) -> re.Pattern:
        end = pat.endswith("$")
        body = re.escape(pat[:-1] if end else pat).replace(r"\*", ".*")
        return re.compile(body + ("$" if end else ""))

    def can_fetch(self, path: str) -> bool:
        best = ("allow", -1)
        for kind, pat in self.rules:
            if not pat:  # empty Disallow = allow everything
                continue
            if self._rx(pat).match(path):
                if len(pat) > best[1] or (len(pat) == best[1] and kind == "allow"):
                    best = (kind, len(pat))
        return best[0] == "allow"


class Client:
    """httpx wrapper: per-host minimum delay, backoff on 429/503, no cookies kept."""

    def __init__(self) -> None:
        self.http = httpx.Client(headers={"User-Agent": UA}, timeout=120, follow_redirects=True)
        self.last: dict[str, float] = {}
        self.delay: dict[str, float] = {}

        self.robots: dict[str, Robots | None] = {}

    def set_delay(self, host: str, seconds: float) -> None:
        self.delay[host] = max(seconds, self.delay.get(host, 0))

    def allowed(self, url: str) -> str | None:
        """Check robots.txt (cached per host) and adopt its Crawl-delay. Returns a reason if disallowed.
        Per RFC 9309, a 4xx robots.txt means no restrictions; 5xx/unreachable means disallow all."""
        u = urlparse(url)
        host = u.netloc
        if host not in self.robots:
            try:
                r = self.http.get(f"{u.scheme}://{host}/robots.txt")
                self.last[host] = time.time()
                if r.status_code >= 500:
                    self.robots[host] = None
                else:
                    self.robots[host] = Robots(r.text if r.status_code < 400 else "")
                    if self.robots[host].crawl_delay:
                        self.set_delay(host, self.robots[host].crawl_delay + 0.5)
            except httpx.HTTPError:
                self.robots[host] = None
        rb = self.robots[host]
        if rb is None:
            return "robots.txt unreachable (treated as disallow)"
        path = u.path or "/"
        if not rb.can_fetch(path + (f"?{u.query}" if u.query else "")):
            return "robots.txt disallows this path"
        return None

    def get(self, url: str, params: dict | None = None, tries: int = 5) -> httpx.Response:
        host = urlparse(url).netloc
        wait = 30.0
        for attempt in range(tries):
            gap = self.delay.get(host, 1.1) - (time.time() - self.last.get(host, 0))
            if gap > 0:
                time.sleep(gap)
            try:
                r = self.http.get(url, params=params)
            except httpx.HTTPError as e:
                self.last[host] = time.time()
                print(f"  ! {host}: {e!r}; retry in {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
                wait *= 2
                continue
            self.last[host] = time.time()
            if r.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                ra = r.headers.get("Retry-After", "")
                sleep = float(ra) if ra.isdigit() else wait
                if sleep > 300:  # server asks for a long pause: treat as blocked, don't fight it
                    print(f"  ! {host}: HTTP {r.status_code}, Retry-After {ra}s; giving up", file=sys.stderr)
                    return r
                print(f"  ! {host}: HTTP {r.status_code}; backing off {sleep:.0f}s", file=sys.stderr)
                time.sleep(sleep)
                wait *= 2
                continue
            return r
        return r  # type: ignore[possibly-undefined]


# --------------------------------------------------------------------------- helpers
def flip_name(name: str | None) -> str | None:
    """'Last, First M.' -> 'First M. Last'. Leaves other forms alone."""
    if not name:
        return None
    name = re.sub(r"\s+", " ", html.unescape(html.unescape(name))).strip().strip(",;")
    name = re.sub(r",?\s*\(?\d{4}-(\d{4})?\)?\.?$", "", name)  # drop life dates
    if name.count(",") == 1:
        last, first = [p.strip() for p in name.split(",")]
        if first and last and not re.fullmatch(r"(Jr|Sr|II|III|IV)\.?", first):
            return f"{first} {last}"
    return name or None


def year_of(s: str | None) -> int | None:
    m = re.search(r"(1[89]\d\d|20\d\d)", s or "")
    return int(m.group(1)) if m else None


def degree_level(degree: str | None) -> str | None:
    if not isinstance(degree, str) or not degree:
        return None
    if re.search(r"(?i)ph\.?\s?d|doctor|doctorat|dissertation", degree):
        return "doctoral"
    if re.search(r"(?i)master|\bM\.?\s?[AS]\b|\bM\.?Phil", degree):
        return "masters"
    return None


def is_blocked(r: httpx.Response) -> str | None:
    ct = r.headers.get("content-type", "")
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    if "xml" not in ct and "<OAI-PMH" not in r.text[:2000]:
        if "anubis" in r.text[:3000].lower():
            return "Anubis proof-of-work bot challenge"
        if "Just a moment" in r.text[:3000] or "challenge" in r.text[:3000]:
            return "Cloudflare JS challenge"
        return f"non-OAI response ({ct})"
    return None


# --------------------------------------------------------------------------- OAI harvest
def oai_harvest(client: Client, base: str, prefix: str, set_spec: str | None, cache: Path) -> list[Path]:
    """Harvest ListRecords into cache/page_NNNN.xml, resuming from cached pages. Returns page files."""
    cache.mkdir(parents=True, exist_ok=True)
    done = cache / "DONE"
    pages = sorted(cache.glob("page_*.xml"))
    if done.exists():
        return pages

    token = None
    if pages:
        m = re.search(r"<resumptionToken[^>]*>([^<]+)</resumptionToken>", pages[-1].read_text("utf-8"))
        token = m.group(1) if m else None
        if token is None:
            done.write_text("ok")
            return pages
    n = len(pages)
    restarted = False
    while True:
        if token:
            params = {"verb": "ListRecords", "resumptionToken": token}
        else:
            params = {"verb": "ListRecords", "metadataPrefix": prefix}
            if set_spec:
                params["set"] = set_spec
        r = client.get(base, params=params)
        blocked = is_blocked(r)
        if blocked:
            raise RuntimeError(f"{base}: {blocked}")
        text = r.text
        if 'code="badResumptionToken"' in text and not restarted:
            print(f"  token expired; restarting {set_spec} from scratch", file=sys.stderr)
            for p in cache.glob("page_*.xml"):
                p.unlink()
            n, token, restarted = 0, None, True
            continue
        if 'code="noRecordsMatch"' in text:
            done.write_text("empty")
            return []
        n += 1
        p = cache / f"page_{n:04d}.xml"
        p.write_text(text, "utf-8")
        m = re.search(r"<resumptionToken([^>]*)>([^<]+)</resumptionToken>", text)
        if n % 10 == 0 or not m:
            size = re.search(r'completeListSize="(\d+)"', m.group(1)) if m else None
            print(f"  {set_spec}: page {n}" + (f" of ~{size.group(1)} records" if size else ""))
        if not m:
            done.write_text("ok")
            return sorted(cache.glob("page_*.xml"))
        token = m.group(2)


def oai_records(pages: list[Path]):
    for p in pages:
        try:
            root = ET.parse(p).getroot()
        except ET.ParseError as e:
            print(f"  ! parse error {p}: {e}", file=sys.stderr)
            continue
        for rec in root.iter(f"{OAI_NS}record"):
            hdr = rec.find(f"{OAI_NS}header")
            if hdr is None or hdr.get("status") == "deleted":
                continue
            ident = hdr.findtext(f"{OAI_NS}identifier")
            sets = [s.text for s in hdr.findall(f"{OAI_NS}setSpec")]
            md = rec.find(f"{OAI_NS}metadata")
            if md is not None and len(md):
                yield ident, sets, md[0]


def list_sets(client: Client, base: str, cache: Path) -> list[tuple[str, str]]:
    f = cache / "sets.json"
    if f.exists():
        return [tuple(x) for x in json.loads(f.read_text())]
    out, token = [], None
    while True:
        params = {"verb": "ListSets", "resumptionToken": token} if token else {"verb": "ListSets"}
        r = client.get(base, params=params, tries=2)
        blocked = is_blocked(r)
        if blocked:
            raise RuntimeError(f"{base}: {blocked}")
        out += re.findall(r"<setSpec>([^<]*)</setSpec>\s*<setName>([^<]*)</setName>", r.text)
        m = re.search(r"<resumptionToken[^>]*>([^<]+)</resumptionToken>", r.text)
        if not m:
            break
        token = m.group(1)
    cache.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    return out


# --------------------------------------------------------------------------- DSpace (dim) and IDEALS (native)
def parse_dim(el: ET.Element) -> dict[str, list[str]]:
    """Flatten DSpace `dim` (mdschema=) or IDEALS `native` (schema=) fields to 'schema.element.qualifier'."""
    d: dict[str, list[str]] = {}
    for f in el.iter():
        if not isinstance(f.tag, str) or f.tag.rsplit("}", 1)[-1] != "field":
            continue
        key = ".".join(x for x in (f.get("mdschema") or f.get("schema"), f.get("element"), f.get("qualifier")) if x)
        if f.text and f.text.strip():
            d.setdefault(key, []).append(f.text.strip())
    return d


def first(d: dict, *keys: str) -> str | None:
    for k in keys:
        if d.get(k):
            return d[k][0]
    return None


def all_of(d: dict, prefix: str) -> list[str]:
    """Values of every key starting with `prefix` (case-insensitive)."""
    p = prefix.lower()
    return [v for k, vs in d.items() if k.lower().startswith(p) for v in vs]


def name_key(name: str) -> str:
    """'Tim F. Liao' and 'Tim Liao' -> 'liao|t' (surname + first initial), for de-duplication."""
    parts = re.sub(r"[.,]", " ", name or "").lower().split()
    return f"{parts[-1]}|{parts[0][:1]}" if len(parts) > 1 else (parts[0] if parts else "")


def uniq(xs, key=lambda x: x.lower()):
    """Order-preserving de-dup of truthy strings."""
    seen, out = set(), []
    for x in xs:
        k = key(x or "")
        if x and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def umn_description(d: dict) -> None:
    """UMN Conservancy keeps degree, major and advisors only in dc.description, e.g.
    'University of Minnesota Ph.D. dissertation. August 2012. Major: Sociology. Advisor: Ann Meier. ...'
    Advisors are already 'First Last', comma/'and' separated. Fills synthetic keys in place."""
    for desc in d.get("dc.description", []):
        m = re.search(r"University of Minnesota (.+?) (?:dissertation|thesis)\.", desc, re.I)
        if m:
            d.setdefault("x.degree", []).append(m.group(1))
        m = re.search(r"Major:\s*([^.]+)\.", desc)
        if m:
            d.setdefault("x.discipline", []).append(m.group(1).strip())
        m = re.search(r"Advisors?:\s*(.+?)\.\s+(?:\d+ computer file|\d|$)", desc)
        if m:
            names = re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", m.group(1).strip())
            names = [re.sub(r"^(Dr|Prof|Professor)\.?\s+|,?\s*(Ph\.?\s?D\.?|PhD)$", "", n.strip()) for n in names]
            d.setdefault("x.advisor", []).extend(n for n in names if n)


MINDS_SETS = {
    "col_1793_345": "University of Wisconsin-Madison",  # UW-Madison Open Dissertations and Theses
    "col_1793_24417": "University of Wisconsin-Madison",  # UW-Madison Closed Dissertations and Theses
    "com_1793_84081": "University of Wisconsin-Madison",  # Department of Sociology (Madison)
    "com_1793_21799": "University of Wisconsin-Madison",  # Community and Environmental Sociology
    "col_1793_94912": None,  # "Sociology"
    "col_1793_97803": None,  # Department of Sociology and Social Work
    "col_1793_90774": "University of Wisconsin-Milwaukee",  # UWM Electronic Theses and Dissertations
    "col_1793_79734": None,  # Dissertations
    "col_1793_80047": None,  # Dissertations and Theses
    "col_1793_82523": "University of Wisconsin-Stout",  # Stout Dissertations
    "col_1793_95650": "University of Wisconsin-River Falls",  # UWRF Dissertations
}

# Each repo: base URL, metadataPrefix, sets (explicit, or `set_regex` over ListSets names),
# soc_sets (membership alone marks a record as sociology), doctoral_only, optional `prep` hook.
DSPACE_REPOS = {
    "minds": {
        "base": "https://minds.wisc.edu/server/oai/request", "prefix": "dim",
        "institution_default": "University of Wisconsin", "sets": MINDS_SETS,
        "soc_sets": {"com_1793_84081", "com_1793_21799", "col_1793_94912", "col_1793_97803",
                     "col_1793_84082", "col_1793_84083", "col_1793_80928"},
        "doctoral_only": False,  # kept masters too (first pass); filter on degree_level
    },
    "umn": {
        # dim has no advisor/degree fields; they live in dc.description (see umn_description)
        "base": "https://conservancy.umn.edu/server/oai/request", "prefix": "dim",
        "institution_default": "University of Minnesota",
        "sets": {"col_11299_45273": None},  # Dissertations (12.3k); no sociology collection exists
        "soc_sets": set(), "doctoral_only": True, "prep": umn_description,
    },
    "ideals": {
        # IDEALS is not DSpace; `native` is dim-like and keeps advisor/committeeChair/committeeMember.
        # (its qdc output collapses contributors into unlabeled dc:contributor)
        "base": "https://www.ideals.illinois.edu/oai-pmh", "prefix": "native",
        "institution_default": "University of Illinois at Urbana-Champaign",
        "sets": {"col_2142_14851": None},  # Dissertations and Theses - Sociology
        "soc_sets": {"col_2142_14851"}, "doctoral_only": True,
    },
    "cornell": {
        "base": "https://ecommons.cornell.edu/server/oai/request", "prefix": "dim",
        "institution_default": "Cornell University",
        "sets": {"col_1813_47": None},  # Cornell Theses and Dissertations (13.2k); filter on discipline
        "soc_sets": set(), "doctoral_only": True,
    },
    "oregon": {
        "base": "https://scholarsbank.uoregon.edu/server/oai/request", "prefix": "dim",
        "institution_default": "University of Oregon",
        "sets": {"col_1794_3074": None},  # Sociology Theses and Dissertations
        "soc_sets": {"col_1794_3074"}, "doctoral_only": True,
    },
    "dash": {
        "base": "https://dash.harvard.edu/server/oai/request", "prefix": "dim",
        "institution_default": "Harvard University", "set_regex": r"(?i)dissertation|sociolog",
        "soc_sets": set(), "doctoral_only": True,
    },
    "deepblue": {
        "base": "https://deepblue.lib.umich.edu/dspace-oai/request", "prefix": "dim",
        "institution_default": "University of Michigan", "set_regex": r"(?i)dissertation|sociolog",
        "soc_sets": set(), "doctoral_only": True,
    },
}

BAD_DEGREE = re.compile(r"(?i)\b(B\.?A|B\.?S|bachelor|honou?rs|senior|undergrad)", re.I)
ADVISOR_KEYS = ("dc.contributor.advisor", "dc.contributor.chair", "dc.contributor.committeeChair",
                "dc.contributor.coChair", "dc.contributor.coadvisor", "x.advisor")


def dspace_rows(name: str, cfg: dict, client: Client | None, status: dict) -> list[dict]:
    cache = RAW / f"oai_{name}"
    st = status.setdefault(f"oai:{name}", {})
    st.update(endpoint=cfg["base"], format=cfg["prefix"])
    if client:
        err = client.allowed(cfg["base"])
        if err:
            st["error"] = err
            client = None
    if "sets" in cfg:
        sets = cfg["sets"]
    else:
        try:
            all_sets = list_sets(client, cfg["base"], cache) if client else json.loads((cache / "sets.json").read_text())
        except Exception as e:  # blocked / unreachable
            st.setdefault("error", str(e))
            return []
        sets = {s: None for s, n in all_sets if re.search(cfg["set_regex"], n)}
    st["sets"] = list(sets)
    rows, seen = [], set()
    n_rec = n_soc = n_adv = n_com = 0
    years = []
    for set_spec, inst in sets.items():
        scache = cache / set_spec
        try:
            pages = (oai_harvest(client, cfg["base"], cfg["prefix"], set_spec, scache) if client
                     else sorted(scache.glob("page_*.xml")))
        except Exception as e:
            st.setdefault("set_errors", {})[set_spec] = str(e)
            pages = sorted(scache.glob("page_*.xml"))
        for ident, rec_sets, md in oai_records(pages):
            if ident in seen:
                continue
            seen.add(ident)
            n_rec += 1
            d = parse_dim(md)
            if cfg.get("prep"):
                cfg["prep"](d)
            disc = "; ".join(uniq(all_of(d, "thesis.degree.discipline") + all_of(d, "dc.degree.discipline")
                                  + all_of(d, "dc.contributor.department") + all_of(d, "thesis.degree.department")
                                  + all_of(d, "x.discipline")))
            subj = all_of(d, "dc.subject")
            in_soc_set = bool(set(rec_sets) & cfg["soc_sets"])
            soc = bool(SOC_RE.search(disc)) or in_soc_set or (
                not disc and any(re.fullmatch(r"(?i)(sociology|.*::sociology)", s) for s in subj))
            if not soc:
                continue
            degree = "; ".join(uniq(all_of(d, "thesis.degree.name") + all_of(d, "dc.degree.name")
                                    + all_of(d, "thesis.degree.level") + all_of(d, "dc.degree.level")
                                    + all_of(d, "x.degree"))) or None
            if degree and BAD_DEGREE.search(degree) and not re.search(r"(?i)ph\.?d|doctor", degree):
                continue
            if "col_1793_84083" in rec_sets:  # Madison sociology senior theses
                continue
            if cfg.get("doctoral_only") and degree_level(degree) != "doctoral":
                continue
            n_soc += 1
            flip = (lambda x: x) if name == "umn" else flip_name
            advisors = uniq([flip(a) for k in ADVISOR_KEYS for a in d.get(k, [])], key=name_key)
            adv_k = {name_key(a) for a in advisors}
            committee = [c for c in uniq([flip_name(c) for c in all_of(d, "dc.contributor.committeeMember")], key=name_key)
                         if name_key(c) not in adv_k]
            n_adv += bool(advisors)
            n_com += bool(committee)
            students = all_of(d, "dc.contributor.author") or all_of(d, "dc.creator")
            grantor = first(d, "thesis.degree.grantor", "dc.degree.grantor")
            yr = year_of(first(d, "dc.date.issued", "dc.date.created", "dc.date.submitted"))
            if yr:
                years.append(yr)
            for a in advisors:
                rows.append({
                    "source": f"oai:{name}", "source_id": ident,
                    "advisor_name": a, "student_name": flip_name(students[0]) if students else None,
                    "year": yr, "institution": grantor or inst or cfg["institution_default"],
                    "field": "sociology", "url": first(d, "dc.identifier.uri") or ident,
                    "title": first(d, "dc.title"),
                    "role": "advisor" if len(advisors) == 1 else "co-advisor",
                    "department": disc or None, "degree": degree,
                    "committee": "; ".join(committee) or None,
                    "advisor_id": None, "student_id": None,
                })
    st.update(records_harvested=n_rec, sociology_records=n_soc, sociology_with_advisor=n_adv,
              sociology_with_committee=n_com,
              record_year_min=min(years, default=None), record_year_max=max(years, default=None))
    return rows


# --------------------------------------------------------------------------- UChicago (datacite)
UC_BASE = "https://knowledge.uchicago.edu/oai2d"


def uchicago_rows(client: Client | None, status: dict) -> list[dict]:
    # Harvest the Social Sciences Division set (2.3k records, about half the size of the full
    # dissertations set; robots.txt asks for a 10 s crawl delay and pages hold only 10 records).
    # Any cached pages of the full dissertations set are parsed too.
    base_cache = RAW / "oai_uchicago"
    st = status.setdefault("oai:uchicago", {"endpoint": UC_BASE, "format": "datacite (kernel-4)"})
    harvest_set = "community-social-sciences-division"
    if client:
        client.set_delay("knowledge.uchicago.edu", 10.5)  # robots.txt Crawl-delay: 10
        try:
            oai_harvest(client, UC_BASE, "datacite", harvest_set, base_cache / harvest_set)
            st.pop("error", None)
        except Exception as e:
            st["error"] = str(e)
    pages = sorted(base_cache.glob("*/page_*.xml"))
    st["complete"] = (base_cache / harvest_set / "DONE").exists()
    st["harvested_set"] = harvest_set
    rows, n_rec, n_soc, n_adv = [], 0, 0, 0
    seen: set[str] = set()
    for ident, sets, md in oai_records(pages):
        rt = md.find(f"{DC4_NS}resourceType")
        is_diss = "community-uchicago-dissertations" in sets or (
            rt is not None and rt.get("resourceTypeGeneral") == "Dissertation")
        if ident in seen or not is_diss:
            continue
        seen.add(ident)
        n_rec += 1
        subjects = [s.text.strip() for s in md.iter(f"{DC4_NS}subject") if s.text]
        # No department in OAI output (only in the robots-disallowed /api). Use ProQuest subject
        # categories: keep if any subject mentions sociology, within the Social Sciences Division.
        in_ssd = "community-social-sciences-division" in sets
        if not (subjects and SOC_RE.search(subjects[0])) and not (
                in_ssd and any(SOC_RE.search(s) for s in subjects)):
            continue
        n_soc += 1
        sup, other = [], []
        for c in md.iter(f"{DC4_NS}contributor"):
            nm = c.findtext(f"{DC4_NS}contributorName")
            (sup if c.get("contributorType") == "Supervisor" else other).append(nm)
        if sup:
            n_adv += 1
        student = md.findtext(f"{DC4_NS}creators/{DC4_NS}creator/{DC4_NS}creatorName")
        rid = ident.rsplit(":", 1)[-1]
        divisions = [s.replace("community-", "") for s in sets if s != "community-uchicago-dissertations"]
        for a in sup:
            rows.append({
                "source": "oai:uchicago", "source_id": ident,
                "advisor_name": flip_name(a), "student_name": flip_name(student),
                "year": year_of(md.findtext(f"{DC4_NS}publicationYear")),
                "institution": "University of Chicago", "field": "sociology",
                "url": f"https://knowledge.uchicago.edu/records/{rid}",
                "title": md.findtext(f"{DC4_NS}titles/{DC4_NS}title"),
                "role": "advisor" if len(sup) == 1 else "co-advisor",
                # no department in OAI: record division + ProQuest subjects instead
                "department": "; ".join(divisions + ["subjects: " + ", ".join(subjects[:3])]),
                "degree": "PhD",
                "committee": "; ".join(flip_name(o) for o in other if o) or None,
                "advisor_id": None, "student_id": None,
            })
    st.update(records_harvested=n_rec, sociology_records=n_soc, sociology_with_advisor=n_adv)
    return rows


# --------------------------------------------------------------------------- probes for blocked sources
PROBES = {
    # not harvested: each failed at the time of writing (see status.json)
    "escholarship": "https://escholarship.org/oai?verb=Identify",  # CloudFront 403
    "osu": "https://kb.osu.edu/server/oai/request?verb=Identify",  # robots.txt: Disallow /server/oai/
    "bu": "https://open.bu.edu/server/oai/request?verb=Identify",  # robots.txt: Disallow /server/oai/*
    "mit": "https://dspace.mit.edu/oai/request?verb=Identify",  # 302 -> /server/oai, firewall 429
    "duke": "https://dukespace.lib.duke.edu/dspace-oai/request?verb=Identify",  # Anubis challenge
}


def probe(client: Client, name: str, url: str, status: dict) -> None:
    st = status.setdefault(f"oai:{name}", {})
    st["endpoint"] = url.split("?")[0]
    err = client.allowed(url)
    if err:
        st["error"] = err
        return
    r = client.get(url, tries=2)
    st["error"] = is_blocked(r) or "reachable (not harvested)"


# --------------------------------------------------------------------------- theses.fr
TF_API = "https://theses.fr/api/v1/theses/recherche/"
TF_QUERY = "discipline:sociologie"
TF_PAGE = 1000


def thesesfr_rows(client: Client | None, status: dict) -> list[dict]:
    cache = RAW / "thesesfr"
    cache.mkdir(parents=True, exist_ok=True)
    st = status.setdefault("theses.fr", {"endpoint": TF_API, "format": f"JSON, q={TF_QUERY}"})
    if client:
        client.set_delay("theses.fr", 5.5)  # robots.txt Crawl-delay: 5
    total, debut, page = None, 0, 0
    while True:
        f = cache / f"page_{page:03d}.json"
        if not f.exists():
            if not client:
                break
            r = client.get(TF_API, params={"q": TF_QUERY, "debut": debut, "nombre": TF_PAGE, "tri": "dateAsc"})
            if r.status_code != 200:
                st["error"] = f"HTTP {r.status_code} at debut={debut}"
                break
            f.write_text(r.text, "utf-8")
        d = json.loads(f.read_text("utf-8"))
        total = d.get("totalHits", total)
        if not d.get("theses"):
            break
        debut += TF_PAGE
        page += 1
        if total is not None and debut >= min(total, 10000):
            break
    rows, ids, n_adv, n_com = [], set(), 0, 0
    years = []
    for f in sorted(cache.glob("page_*.json")):
        for t in json.loads(f.read_text("utf-8")).get("theses", []):
            if t["id"] in ids:
                continue
            ids.add(t["id"])
            dirs = [x for x in t.get("directeurs") or [] if x.get("nom")]
            if dirs:
                n_adv += 1
            au = (t.get("auteurs") or [{}])[0]
            student = " ".join(x for x in (au.get("prenom"), au.get("nom")) if x) or None
            yr = year_of(t.get("dateSoutenance")) if t.get("status") == "soutenue" else None
            dir_ppn = {x.get("ppn") for x in dirs if x.get("ppn")}
            dir_nm = {(x.get("prenom"), x.get("nom")) for x in dirs}
            jury = (t.get("examinateurs") or []) + (t.get("rapporteurs") or []) + [t.get("president") or {}]
            committee = "; ".join(uniq((
                " ".join(x for x in (e.get("prenom"), e.get("nom")) if x) for e in jury
                if e.get("nom") and e.get("ppn") not in dir_ppn and (e.get("prenom"), e.get("nom")) not in dir_nm
            ), key=name_key)) or None
            n_com += bool(committee)
            for dr in dirs:
                rows.append({
                    "source": "theses.fr", "source_id": t["id"],
                    "advisor_name": " ".join(x for x in (dr.get("prenom"), dr.get("nom")) if x),
                    "student_name": student, "year": yr,
                    "institution": t.get("etabSoutenanceN"), "field": "sociology",
                    "url": f"https://theses.fr/{t['id']}", "title": t.get("titrePrincipal"),
                    "role": "director", "department": t.get("discipline"),
                    "degree": "doctorat" if t.get("status") == "soutenue" else "doctorat (en cours)",
                    "committee": committee,
                    "advisor_id": dr.get("ppn"), "student_id": au.get("ppn"),
                })
    st.update(total_hits=total, records_harvested=len(ids), sociology_records=len(ids),
              sociology_with_advisor=n_adv, sociology_with_committee=n_com)
    return rows


# --------------------------------------------------------------------------- main
SOURCES = ["minds", "uchicago", "umn", "ideals", "cornell", "oregon", "dash", "deepblue",
           "escholarship", "osu", "bu", "mit", "duke", "thesesfr"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=SOURCES)
    ap.add_argument("--parse-only", action="store_true", help="no network; rebuild from cache")
    args = ap.parse_args()
    todo = args.only or SOURCES
    client = None if args.parse_only else Client()
    status_file = RAW / "status.json"
    prev = json.loads(status_file.read_text()) if status_file.exists() else {}
    status: dict = {}
    rows: list[dict] = []
    for src in SOURCES:  # always parse every cached source so the parquet is complete
        live = client if src in todo else None
        print(f"== {src}" + ("" if live else " (cache only)"))
        if src in DSPACE_REPOS:
            if live is None and not (RAW / f"oai_{src}").exists():
                continue
            rows += dspace_rows(src, DSPACE_REPOS[src], live, status)
        elif src == "uchicago":
            rows += uchicago_rows(live, status)
        elif src == "thesesfr":
            rows += thesesfr_rows(live, status)
        elif src in PROBES and live:
            probe(live, src, PROBES[src], status)
    df = pd.DataFrame(rows)
    cols = ["source", "source_id", "advisor_name", "student_name", "year", "institution", "field",
            "url", "title", "role", "department", "degree", "committee", "advisor_id", "student_id"]
    df = df.reindex(columns=cols)
    df.insert(cols.index("degree") + 1, "degree_level", df["degree"].map(degree_level))
    df["year"] = df["year"].astype("Int64")
    df["title"] = df["title"].map(lambda t: html.unescape(t) if isinstance(t, str) else t)
    df = df.drop_duplicates(["source", "source_id", "advisor_name"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    for src, g in df.groupby("source"):
        status.setdefault(src, {}).update(edges=len(g), year_min=g.year.min(), year_max=g.year.max())
    for k, v in prev.items():  # keep probe results / errors from earlier live runs
        status[k] = {**v, **status.get(k, {})}
    RAW.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(status, indent=2, default=str))
    print(json.dumps(status, indent=2, default=str))
    print(f"wrote {len(df)} rows -> {OUT}")


if __name__ == "__main__":
    main()
