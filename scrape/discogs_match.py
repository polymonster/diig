import re
import time
import unicodedata
import requests
from rapidfuzz import fuzz

# rule based matching of store releases to discogs, shared by the nightly job
# (discogs.py) and the llm validator (discogs_validate.py).
#
# a link is only made on corroborated evidence: two independent fields agreeing
# (catalogue number + label, artist + title...) and nothing contradicting them.
# a single agreeing field (just the catno, just a common title) is how most of
# the old false positives got in, so those are kept as a "candidate" for the
# llm to look at instead of being linked.

# bump when the rules change, so releases that failed under older rules get
# another go
MATCHER_VERSION = 2

API = "https://api.discogs.com"
USER_AGENT = "diig/1.0 +https://diig.app"


# ── discogs api ──────────────────────────────────────────────────────────────

class Discogs:
    # plain REST rather than discogs_client, whose lazy attribute fetching
    # makes it hard to see (and pace) how many requests are going out.
    # authenticated limit is 60 a minute
    def __init__(self, token, sleep=1.1):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Discogs token={token}",
            "User-Agent": USER_AGENT,
        })
        self.sleep = sleep
        self.last = 0.0
        self.requests = 0

    def get(self, path, params=None):
        for attempt in range(6):
            wait = self.last + self.sleep - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.requests += 1
            res = self.session.get(f"{API}{path}", params=params, timeout=30)
            if res.status_code == 429:
                backoff = 10 * (attempt + 1)
                print(f"    discogs rate limited, waiting {backoff}s")
                time.sleep(backoff)
                continue
            if res.status_code == 404:
                return None
            res.raise_for_status()
            return res.json()
        raise RuntimeError(f"discogs still rate limited: {path}")

    # a release or master by its www.discogs.com url
    def record(self, url):
        m = re.search(r"/(release|master)/(\d+)", url or "")
        if not m:
            return None
        kind, rid = m.group(1), m.group(2)
        data = self.get(f"/{kind}s/{rid}")
        if data is None:
            return None
        data["_kind"] = kind
        # masters carry no label or catalogue number, which are the best
        # evidence we have, so borrow them from the main release
        if kind == "master" and data.get("main_release"):
            main = self.get(f"/releases/{data['main_release']}")
            if main:
                data["labels"] = main.get("labels", [])
                data["formats"] = main.get("formats", [])
        return data

    def search(self, **params):
        data = self.get("/database/search", {"type": "release", "per_page": 15, **params})
        return (data or {}).get("results", [])


# ── normalising ──────────────────────────────────────────────────────────────

def fold(s):
    # lowercase ascii-ish text: accents off, & as and, punctuation to spaces
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\(\d+\)", " ", s)        # discogs disambiguation, "Orion (12)"
    s = s.replace("*", "")                # discogs name variation marker
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# format words shops add to catalogue numbers: BL170V, SS7021EP, MDLP60
CAT_SUFFIX = re.compile(r"(v|lp|ep|cd|rp|x|r|vinyl|repress|black|ltd)$")


def norm_cat(cat):
    c = re.sub(r"[^a-z0-9]", "", fold(cat))
    if not c or c in ("none", "na", "nocat"):
        return ""
    # only strip a suffix after a digit, so the label prefix is never eaten
    m = re.match(r"^(.*\d)" + CAT_SUFFIX.pattern, c)
    if m:
        c = m.group(1)
    # leading zeros: BAO99 and BAO099 are the same number
    return re.sub(r"\d+", lambda d: str(int(d.group())), c)


# discogs sometimes files a catno without the label prefix the shop uses:
# SALON018 on the shop, 018 on discogs
def cat_equal(a, b):
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return short.isdigit() and long.endswith(short) and not long[-len(short) - 1].isdigit()


LABEL_NOISE = {"records", "recordings", "record", "music", "label", "ltd", "limited",
               "rec", "recs", "digital", "white", "the", "audio", "productions"}


def norm_label(label):
    words = [w for w in fold(label).split() if w not in LABEL_NOISE]
    return " ".join(words)


TITLE_NOISE = re.compile(
    r"\b(ep|lp|12|7|10|vinyl|repress|reissue|remastered|remaster|limited|edition|"
    r"ltd|deluxe|coloured|colored|180g|2x12|2xlp|3xlp|double|clear|gatefold)\b")


def norm_title(title):
    t = fold(re.sub(r"\[[^\]]*\]", " ", title or ""))
    return re.sub(r"\s+", " ", TITLE_NOISE.sub(" ", t)).strip()


# numbers in a title name a volume, part or series entry: "EP 3", "Vol.10",
# "WITNESS09". two titles with different numbers are different records
def title_numbers(title):
    return {str(int(n)) for n in re.findall(r"\d+", fold(title)) if len(n) < 5}


VARIOUS = {"various", "various artists", "va", "v a", "compilation"}


def artist_parts(artist):
    a = fold(artist)
    a = re.sub(r"\b(feat|featuring|ft|vs|versus|presents|pres|with|x)\b", ",", a)
    parts = re.split(r"\s*(?:,|/|\band\b)\s*", a)
    return {p.strip() for p in parts if p.strip()}


def is_various(artist):
    a = fold(artist)
    return a in VARIOUS or a.startswith("various ")


def strip_mix(name):
    return fold(re.sub(r"\((original|extended|club|radio)?\s*mix\)", "", name or "", flags=re.I))


# ── evidence ─────────────────────────────────────────────────────────────────

# a discogs search hit or full record reduced to the fields we compare
def candidate_from_hit(hit):
    title = hit.get("title", "")
    artist, _, rtitle = title.partition(" - ")
    if not rtitle:
        artist, rtitle = "", title
    return {
        "id": hit.get("id"),
        "url": f"https://www.discogs.com{hit['uri']}" if str(hit.get("uri", "")).startswith("/") else hit.get("uri"),
        "artist": artist,
        "title": rtitle,
        "labels": hit.get("label", []),
        "catnos": [hit.get("catno", "")],
        "formats": hit.get("format", []),
        "tracks": None,   # search hits carry no tracklist
    }


def candidate_from_record(rec):
    labels = rec.get("labels", [])
    return {
        "id": rec.get("id"),
        "url": rec.get("uri"),
        "artist": " & ".join(a.get("name", "") for a in rec.get("artists", [])),
        "title": rec.get("title", ""),
        "labels": [l.get("name", "") for l in labels],
        "catnos": [l.get("catno", "") for l in labels],
        "formats": [f.get("name", "") for f in rec.get("formats", [])],
        "tracks": [t.get("title", "") for t in rec.get("tracklist", []) if t.get("type_", "track") == "track"],
    }


def label_match(store_label, labels):
    sl = norm_label(store_label)
    if len(sl) < 2:
        return False
    for l in labels:
        dl = norm_label(l)
        if not dl:
            continue
        if sl == dl or fuzz.ratio(sl, dl) >= 90:
            return True
        # sublabels and longer names: "Running Back Double Copy" / "Running Back"
        if min(len(sl), len(dl)) >= 5 and (sl.startswith(dl) or dl.startswith(sl)):
            return True
    return False


def artist_match(store_artist, disc_artist):
    if is_various(store_artist) or is_various(disc_artist):
        return is_various(store_artist) and is_various(disc_artist)
    sa, da = fold(store_artist), fold(disc_artist)
    if not sa or not da:
        return False
    if sa == da or fuzz.token_set_ratio(sa, da) >= 92:
        return True
    return bool(artist_parts(store_artist) & artist_parts(disc_artist))


def title_match(store_title, disc_title):
    st, dt = norm_title(store_title), norm_title(disc_title)
    if not st or not dt:
        return False
    if title_numbers(store_title) != title_numbers(disc_title):
        return False
    return st == dt or fuzz.token_sort_ratio(st, dt) >= 90


# fraction of the store's track names found in the discogs tracklist, None
# when there is nothing to compare
def track_overlap(store_tracks, disc_tracks):
    st = [strip_mix(t) for t in (store_tracks or []) if t and len(strip_mix(t)) > 2]
    dt = [strip_mix(t) for t in (disc_tracks or []) if t]
    if len(st) < 2 or not dt:
        return None
    hits = sum(1 for t in st if max(fuzz.token_set_ratio(t, d) for d in dt) >= 85)
    return hits / len(st)


# compare a store release against one discogs candidate. returns the verdict
#   strong  catno and label agree, plus one more field
#   ok      corroborated: two fields agree with nothing against
#   weak    a single field agrees, worth an llm look but not a link
#   no      nothing useful, or a contradiction
# and the list of signals behind it, kept in the registry for auditing
def score(release, cand):
    store_cat = norm_cat(release.get("cat", ""))
    disc_cats = [norm_cat(c) for c in cand["catnos"] if norm_cat(c)]

    cat = bool(store_cat) and any(cat_equal(store_cat, d) for d in disc_cats)
    cat_conflict = bool(store_cat) and bool(disc_cats) and not cat
    label = label_match(release.get("label", ""), cand["labels"])
    artist = artist_match(release.get("artist", ""), cand["artist"])
    title = title_match(release.get("title", ""), cand["title"])
    numbers_conflict = (title_numbers(release.get("title", "")) != title_numbers(cand["title"])
                        and bool(title_numbers(cand["title"])))
    tracks = track_overlap(release.get("track_names"), cand["tracks"])
    tracks_good = tracks is not None and tracks >= 0.5
    tracks_bad = tracks is not None and tracks < 0.25

    signals = [name for name, on in (("cat", cat), ("label", label), ("artist", artist),
                                     ("title", title), ("tracks", tracks_good)) if on]

    # contradictions first. same label, other catalogue number: another
    # release in the series (WITNESS09 against WITNESS01)
    if label and cat_conflict and not tracks_good:
        return "no", signals + ["cat-conflict"]
    # same artist and label but a different volume or part
    if numbers_conflict and not cat and not tracks_good:
        return "no", signals + ["number-conflict"]
    # a tracklist that doesn't match is a different record, unless the artist
    # or title says otherwise (shops' track names can be junk). catno + label
    # alone don't outvote it, those collide across small labels
    if tracks_bad and not (artist or title):
        return "no", signals + ["tracks-conflict"]

    if cat and label and (artist or title or tracks_good):
        return "strong", signals
    # everything but the catno, which discogs may not list
    if artist and title and tracks_good and (label or not cat_conflict):
        return "strong", signals
    if cat and (label or artist or title or tracks_good):
        return "ok", signals
    if artist and title and (not cat_conflict or tracks_good):
        return "ok", signals
    # the same tracks by the same artist or on the same label: the music
    # matches even when the catno is written differently
    if tracks_good and (artist or label):
        return "ok", signals
    if len(signals) >= 1 and not cat_conflict:
        return "weak", signals
    return "no", signals


RANK = {"strong": 3, "ok": 2, "weak": 1, "no": 0}


def rank(verdict, signals, cand):
    vinyl = any("vinyl" in str(f).lower() for f in cand.get("formats") or [])
    return (RANK[verdict], len(signals), vinyl)


# ── search ───────────────────────────────────────────────────────────────────

def searches(release):
    artist = (release.get("artist") or "").strip()
    title = (release.get("title") or "").strip()
    label = (release.get("label") or "").strip()
    cat = (release.get("cat") or "").strip()
    clean = norm_title(title) or title
    out = []
    if cat:
        out.append({"catno": cat})
        # discogs indexes catnos with their own spacing, "BAO 099"
        spaced = re.sub(r"^([A-Za-z]+)[\s\-]*(\d)", r"\1 \2", cat)
        if spaced != cat:
            out.append({"catno": spaced})
    if artist and not is_various(artist):
        out.append({"artist": artist, "release_title": clean})
    if label and clean:
        out.append({"label": label, "release_title": clean})
    if clean:
        out.append({"q": f"{'' if is_various(artist) else artist} {clean}".strip()})
    return out


# find the discogs record for a store release. returns
#   (verdict, signals, candidate)
# where verdict is strong / ok for a link, weak for a candidate to review and
# None when nothing came close. fetches full records (for tracklists and every
# label's catno) only for the few hits that need them
# the discogs id in a release / master url, "rejected" lists are urls
def url_id(url):
    m = re.search(r"/(?:release|master)/(\d+)", url or "")
    return int(m.group(1)) if m else None


# exclude: discogs urls already ruled out for this release, never offered again
def match_release(api, release, max_fetch=3, verbose=False, exclude=()):
    verdict, signals, cand = _match(api, release, max_fetch, verbose, {url_id(u) for u in exclude})
    # a preorder often has no discogs page yet, so whatever comes close is
    # more likely a different record: only link one on the strongest evidence
    if verdict == "ok" and is_preorder(release):
        return "weak", signals + ["preorder"], cand
    return verdict, signals, cand


# not out yet, so unlikely to be on discogs. a release the scrapers have seen
# out before (has_been_released) and that is back on preorder is a repress,
# which discogs will have. juno entries from before it tagged preorders only
# show it as "<section>-preorders" rank keys
def is_preorder(release):
    tags = release.get("store_tags") or {}
    if tags.get("has_been_released"):
        return False
    if "preorder" in tags:
        return bool(tags["preorder"])
    return any(k.endswith("-preorders") for k in release)


def _match(api, release, max_fetch, verbose, exclude):
    seen = set(exclude)
    scored = []
    for params in searches(release):
        for hit in api.search(**params):
            if hit.get("id") in seen:
                continue
            seen.add(hit.get("id"))
            cand = candidate_from_hit(hit)
            verdict, signals = score(release, cand)
            if verbose:
                print(f"      {verdict:6} {signals} {hit.get('title')} [{hit.get('catno')}]")
            scored.append((verdict, signals, cand))
            if verdict == "strong":
                return verdict, signals, cand
        # a corroborated hit from a specific search is enough, the looser
        # searches after it only add noise
        if any(v == "ok" for v, _, _ in scored):
            break

    # search hits carry one catno and no tracklist: fetch the best few and
    # score them again on the full record, which can confirm or rule them out
    scored.sort(key=lambda x: rank(*x), reverse=True)
    best = None
    for verdict, signals, cand in scored[:max_fetch]:
        if verdict == "no":
            break
        rec = api.record(cand["url"])
        if not rec:
            continue
        full = candidate_from_record(rec)
        full["url"] = cand["url"]
        v2, s2 = score(release, full)
        if verbose:
            print(f"      full {v2:6} {s2} {full['artist']} - {full['title']}")
        if best is None or rank(v2, s2, full) > rank(*best):
            best = (v2, s2, full)
        if v2 == "strong":
            break
    if best is None or best[0] == "no":
        return None, [], None
    return best
