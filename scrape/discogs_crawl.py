import csv
import json
import os
import re
import sys
import time
import dig
import discogs_match
from discogs_match import at_key, norm_cat, score, trusted

# the discogs matcher the other way round. discogs.py searches discogs once per
# store release, several searches each. this pages through discogs' own
# listing of a year's electronic vinyl, style by style, and looks every hit up
# in an index of all the store registries at once: one request returns 100
# releases, each matched against every store.
#
#   -xref    no discogs requests at all. a link the rules confirmed in one
#            store is copied to the same record in the others, when the two
#            store entries agree with each other on the same evidence
#   -year    the crawl. hits are scored with the same rules as the nightly
#            job (discogs_match.score); strong links straight away, ok is
#            confirmed on the full record first. single field matches are
#            ignored, the nightly job deals with those
#
# unlinked entries are filled in, and links from the old algorithms (no
# "match" field, never checked) are confirmed when a hit agrees with them, or
# reported as a conflict when it strongly points elsewhere (see check_legacy).
# links the rules or claude confirmed are never touched, and a rejected link
# is never made again. progress is kept per year and style in
# reports/discogs-crawl.json, so a stopped crawl picks up where it was

STYLES = [
    "House", "Deep House", "Tech House", "Electro", "Dub Techno",
    "Breaks", "Breakbeat", "UK Garage", "Garage House", "Speed Garage",
    "Techno", "Minimal", "Minimal Techno", "Acid", "Acid House",
    "Disco", "Nu-Disco", "Italo-Disco",
    # house variants
    "Progressive House", "Tribal House", "Ghetto House", "Euro House", "Hard House",
    "Bassline", "Beatdown", "Hi NRG",
    # broken / bass
    "Broken Beat", "Jungle", "Drum n Bass", "Dubstep", "Grime", "Juke",
    # leftfield / downtempo
    "Ambient", "Downtempo", "Leftfield", "IDM", "Experimental", "Dub", "Balearic",
    # wave / body music
    "EBM", "New Beat", "Synth-pop", "Darkwave", "Electroclash", "Trance",
]

STATE_FILE = "reports/discogs-crawl.json"
CONFLICTS_FILE = "reports/discogs-crawl-conflicts.csv"


def arg(name, default=None):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


# every store registry, the top level json files (ra/, weekly/ are not stores)
def registry_stores():
    return dig.stores_list("diig-registry")


# ── index ────────────────────────────────────────────────────────────────────

# every store's registry, indexed on the fields a discogs hit can be found by:
# normalised catalogue number, its trailing number alone (discogs files some
# catnos without the label prefix), and artist + title
class Registry:
    def __init__(self, stores):
        self.regs = {}
        self.changed = {}
        self.by_cat, self.by_num, self.by_at = {}, {}, {}
        for store in stores:
            reg = dig.load_registry(store)
            self.regs[store] = reg
            self.changed[store] = set()
            for key, r in reg.items():
                if dig.validate_release(key, r):
                    continue
                ref = (store, key)
                cat = norm_cat(r.get("cat", ""))
                if cat:
                    self.by_cat.setdefault(cat, []).append(ref)
                    num = re.search(r"\D(\d+)$", cat)
                    if num:
                        self.by_num.setdefault(num.group(1), []).append(ref)
                k = at_key(r.get("artist", ""), r.get("title", ""))
                if k:
                    self.by_at.setdefault(k, []).append(ref)

    def size(self):
        return sum(len(r) for r in self.regs.values())

    def entry(self, ref):
        return self.regs[ref[0]][ref[1]]

    def lookup(self, cand):
        refs = set()
        for c in cand["catnos"]:
            nc = norm_cat(c)
            if not nc:
                continue
            refs.update(self.by_cat.get(nc, []))
            if nc.isdigit():
                refs.update(self.by_num.get(nc, []))
        k = at_key(cand["artist"], cand["title"])
        if k:
            refs.update(self.by_at.get(k, []))
        return refs

    # vinyl: the record is known to be vinyl, so the nightly -check-formats
    # needn't fetch it again
    def link(self, ref, verdict, signals, cand, via, vinyl=False):
        r = self.entry(ref)
        r["discogs"] = discogs_match.discogs_entry(r, verdict, signals, cand, r.get("discogs"))
        r["discogs"]["via"] = via
        if vinyl:
            r["discogs"]["format_checked"] = True
        self.changed[ref[0]].add(ref[1])

    def save(self):
        patch = {}
        for store, keys in self.changed.items():
            if not keys:
                continue
            reg = self.regs[store]
            print(f"writing {store}: {len(keys)} entries changed")
            dig.write_registry(store, reg)
            patch.update({k: reg[k] for k in keys})
        if patch:
            dig.patch_releases(patch)


# open to a new link: not already linked, and this record not ruled out
def open_for(r, cand_id):
    d = r.get("discogs")
    if discogs_match.is_linked(d):
        return False
    rejected = d.get("rejected", []) if isinstance(d, dict) else []
    return cand_id not in {discogs_match.url_id(u) for u in rejected}


# a preorder often has no discogs page yet, so an ok match is more likely a
# different record: the same rule as discogs_match.match_release
def linkable(r, verdict):
    return verdict == "strong" or (verdict == "ok" and not discogs_match.is_preorder(r))


# ── cross reference ──────────────────────────────────────────────────────────

# a trusted link's store entry stands in for the discogs record: the other
# entries it is indexed with are scored against its artist, title, label,
# catno and tracks
def xref(reg, counts):
    for store, entries in reg.regs.items():
        for key, r in list(entries.items()):
            d = r.get("discogs")
            if not trusted(d):
                continue
            cand = {"id": d["id"], "url": d["url"], "artist": r.get("artist", ""),
                    "title": r.get("title", ""), "labels": [r.get("label", "")],
                    "catnos": [r.get("cat", "")], "formats": [], "tracks": r.get("track_names")}
            for ref in reg.lookup(cand):
                if ref == (store, key):
                    continue
                other = reg.entry(ref)
                if not open_for(other, d["id"]):
                    continue
                verdict, signals = score(other, cand)
                if not linkable(other, verdict):
                    continue
                reg.link(ref, verdict, signals, cand, f"xref {key}", vinyl=bool(d.get("format_checked")))
                counts[ref[0]] = counts.get(ref[0], 0) + 1
                print(f"{ref[1]}: {other.get('artist')} - {other.get('title')} [{other.get('cat')}]")
                print(f"    {verdict} {'+'.join(signals)} from {key} -> {d['url']}")


# ── crawl ────────────────────────────────────────────────────────────────────

class Crawl:
    def __init__(self, api, reg):
        self.api = api
        self.reg = reg
        self.seen = set()
        self.records = {}
        self.conflicts = []
        self.counts = {"hits": 0, "in_registry": 0, "fetched": 0, "already": 0, "conflict": 0,
                       "preorder": 0, "weak": 0, "linked": {}, "confirmed": {}, "replaced": {}}

    # the full record for an ok hit: every label's catno and the tracklist,
    # which can confirm it or rule it out. fetched once per hit
    def full(self, cand):
        if cand["id"] not in self.records:
            self.counts["fetched"] += 1
            rec = self.api.record(cand["url"])
            full = discogs_match.candidate_from_record(rec) if rec else None
            if full:
                full["url"] = cand["url"]
            self.records[cand["id"]] = full
        return self.records[cand["id"]]

    def consider(self, hit):
        if hit.get("id") in self.seen:
            return
        self.seen.add(hit.get("id"))
        self.counts["hits"] += 1
        cand = discogs_match.candidate_from_hit(hit)
        refs = self.reg.lookup(cand)
        if refs:
            self.counts["in_registry"] += 1
        for ref in refs:
            r = self.reg.entry(ref)
            d = r.get("discogs")
            if trusted(d):
                self.counts["already" if d.get("id") == cand["id"] else "conflict"] += 1
                continue
            if discogs_match.is_linked(d):
                self.check_legacy(ref, r, d, cand)
                continue
            if not open_for(r, cand["id"]):
                continue
            verdict, signals, use = self.judge(r, cand)
            if verdict == "weak":
                self.counts["weak"] += 1
            if verdict not in ("strong", "ok"):
                continue
            if not linkable(r, verdict):
                self.counts["preorder"] += 1
                continue
            self.reg.link(ref, verdict, signals, use, "crawl", vinyl=True)
            self.tally("linked", ref)
            print(f"{ref[1]}: {r.get('artist')} - {r.get('title')} [{r.get('cat')}]")
            print(f"    {verdict} {'+'.join(signals)} -> {use['url']}")

    def tally(self, name, ref):
        c = self.counts[name]
        c[ref[0]] = c.get(ref[0], 0) + 1

    # score on the hit, and an ok again on the full record
    def judge(self, r, cand):
        verdict, signals = score(r, cand)
        if verdict != "ok":
            return verdict, signals, cand
        full = self.full(cand)
        if not full:
            return "no", [], cand
        verdict, signals = score(r, full)
        return verdict, signals, full

    # a link from the old algorithms, which nothing has checked. this hit is
    # found by the same catno or artist + title:
    #   same record   confirmed with the evidence recorded, so -rescore and the
    #                 validator skip it. the old matcher picked it on its own,
    #                 so an ok on the hit is enough, no fetch
    #   other record  on strong evidence, written to the conflicts report, or
    #                 with -replace linked instead, the old link kept as
    #                 "replaced" (not rejected: it may be another pressing)
    def check_legacy(self, ref, r, d, cand):
        if d.get("id") == cand["id"]:
            verdict, signals = score(r, cand)
            if not linkable(r, verdict):
                return
            d.update(match=verdict, signals=signals, matcher=discogs_match.MATCHER_VERSION, via="crawl",
                     format_checked=True)
            self.reg.changed[ref[0]].add(ref[1])
            self.tally("confirmed", ref)
            return
        verdict, signals = score(r, cand)
        if verdict != "strong":
            return
        if "-replace" in sys.argv:
            old = d.get("url")
            self.reg.link(ref, verdict, signals, cand, "crawl", vinyl=True)
            r["discogs"]["replaced"] = old
            self.tally("replaced", ref)
            print(f"{ref[1]}: {r.get('artist')} - {r.get('title')} [{r.get('cat')}]")
            print(f"    replaced {old}\n    {verdict} {'+'.join(signals)} -> {cand['url']}")
        else:
            self.conflicts.append({"key": ref[1], "artist": r.get("artist", ""), "title": r.get("title", ""),
                                   "label": r.get("label", ""), "cat": r.get("cat", ""),
                                   "old_link": d.get("url", ""), "new_link": cand["url"],
                                   "rules": f"{verdict} {'+'.join(signals)}"})

    def style(self, year, style, st, deadline):
        page = st.get("page", 0) + 1
        while time.monotonic() < deadline:
            data = self.api.get("/database/search", {
                "type": "release", "genre": "Electronic", "style": style, "year": year,
                "format": "Vinyl", "per_page": 100, "page": page})
            if not data or not data.get("results"):
                st["done"] = True
                return
            for hit in data["results"]:
                self.consider(hit)
            pages = data["pagination"]["pages"]
            st.update(page=page, pages=pages)
            print(f"  {style} {year}: page {page}/{pages}, {self.counts['hits']} hits so far", flush=True)
            if page >= pages:
                st["done"] = True
                return
            page += 1


# "2026", "2025-2015" (either way round) or "2024,2020", newest first
def parse_years(spec):
    years = set()
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        lo, hi = int(lo), int(hi or lo)
        years.update(range(min(lo, hi), max(lo, hi) + 1))
    return [str(y) for y in sorted(years, reverse=True)]


# one year, style by style. its summary is printed and its progress saved
# when done, stopped or interrupted
def crawl_year(api, reg, year, styles, state, deadline, dry):
    progress = state.setdefault(year, {})
    crawl = Crawl(api, reg)
    requests = api.requests
    try:
        for style in styles:
            st = progress.setdefault(style, {})
            if st.get("done"):
                print(f"  {style} {year}: done")
                continue
            crawl.style(year, style, st, deadline)
            if time.monotonic() >= deadline:
                break
    finally:
        c = crawl.counts
        n = lambda k: f"{sum(c[k].values())} {c[k]}"
        print(f"crawl {year}: {c['hits']} discogs releases, {c['in_registry']} found in the registry")
        print(f"  linked              {n('linked')}")
        print(f"  old links confirmed {n('confirmed')}")
        print(f"  old links replaced  {n('replaced')}")
        print(f"  conflicts           {len(crawl.conflicts)} strong matches to another record than an old link")
        print(f"  skipped             {c['already']} confirmed links to the same record, {c['conflict']} "
              f"to another, {c['weak']} single field matches, {c['preorder']} preorders on ok evidence")
        print(f"  {api.requests - requests} discogs requests, {c['fetched']} of them to confirm on the full record",
              flush=True)
        if not dry:
            save_state(state)
            save_conflicts(crawl.conflicts)


def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE, encoding="utf-8"))
    return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), indent=2)


# strong matches to a different record than an old link, for a look by eye
# or discogs_validate.py. appended to, one row per entry and record
def save_conflicts(rows):
    if not rows:
        return
    have = set()
    if os.path.exists(CONFLICTS_FILE):
        have = {(r["key"], r["new_link"]) for r in csv.DictReader(open(CONFLICTS_FILE, encoding="utf-8"))}
    rows = [r for r in rows if (r["key"], r["new_link"]) not in have]
    new = not os.path.exists(CONFLICTS_FILE)
    with open(CONFLICTS_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else [])
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} new conflicts in {CONFLICTS_FILE}")


def display_help():
    print("discogs_crawl.py: match discogs listings into every store registry at once")
    print("")
    print("  -xref               copy confirmed links between stores, no discogs")
    print("                      requests. runs after -year when given both")
    print("  -year <years>       page through electronic vinyl on discogs for a")
    print("                      year (2025), a range (2025-2015) or a list")
    print("                      (2024,2020), newest first, style by style,")
    print("                      linking store releases on strong evidence (ok")
    print("                      is confirmed on the full record). resumes from")
    print("                      reports/discogs-crawl.json, done years skipped.")
    print("                      old unchecked links to the same record are")
    print("                      confirmed. a strong match to another record goes")
    print("                      to reports/discogs-crawl-conflicts.csv")
    print("  -replace            link those strong matches instead, the old link")
    print("                      kept as \"replaced\"")
    print("  -styles <a,b>       styles to crawl, default:")
    for i in range(0, len(STYLES), 6):
        print("                      " + ", ".join(STYLES[i:i + 6]))
    print("  -restart            crawl the year from the first page again")
    print("  -time <hours>       stop after this long, default no limit")
    print("  -dry-run            print what would be linked, write nothing")
    print("  -discogs-key <t>    else discogs-auth.json")
    print("")
    print("  links confirmed by the rules or claude are never touched, nor is a")
    print("  link that was rejected for a release. registry files are written and")
    print("  the changed entries patched to firebase at the end, or on ctrl-c.")
    print("  pull the diig-registry submodule first and push it afterwards, the")
    print("  nightly job works from what is pushed")


def main():
    if "-help" in sys.argv or not ("-xref" in sys.argv or "-year" in sys.argv):
        display_help()
        return
    dry = "-dry-run" in sys.argv
    if not dry:
        dig.setup_firebase_auth()

    stores = registry_stores()
    print(f"indexing {', '.join(stores)}", flush=True)
    reg = Registry(stores)
    print(f"{reg.size()} releases, {len(reg.by_cat)} catnos, {len(reg.by_at)} artist + titles", flush=True)

    try:
        if "-year" in sys.argv:
            token = arg("-discogs-key") or json.load(open("discogs-auth.json"))["token"]
            api = discogs_match.Discogs(token)
            styles = [s.strip() for s in arg("-styles").split(",")] if "-styles" in sys.argv else STYLES
            hours = arg("-time")
            deadline = time.monotonic() + (float(hours) * 3600 if hours else float("inf"))

            state = load_state()
            for year in parse_years(arg("-year")):
                if "-restart" in sys.argv:
                    state.pop(year, None)
                crawl_year(api, reg, year, styles, state, deadline, dry)
                if time.monotonic() >= deadline:
                    print("time limit reached")
                    break
        if "-xref" in sys.argv:
            counts = {}
            xref(reg, counts)
            print(f"xref: {sum(counts.values())} linked " + str(counts))
    finally:
        if dry:
            print("dry run: nothing written")
        else:
            reg.save()


if __name__ == "__main__":
    main()
