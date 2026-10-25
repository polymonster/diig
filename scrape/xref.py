import collections
import csv
import datetime
import json
import os
import re
import sys
import dig
import discogs_match
from discogs_match import (artist_match, at_key, cat_equal, fold, label_match, norm_cat, norm_label,
                           norm_title, title_match, track_name, track_overlap, trusted)

# the diig registry: one record per real world release, grouping the same
# record across every store. stores are grouped on their own data (catno,
# label, artist, title, tracks: same_record, built from the discogs_match
# comparisons), whatever their discogs links say. each record gets a stable diig id, and the best of
# the stores' data:
#
#   fields   artist, title, label, catno by majority across the stores, then
#            the cleanest spelling (not all caps, no "[green vinyl]" notes),
#            then store priority. juno splits various artists records into
#            artist / title / label wrongly, so it comes last
#   tracks   the count is the most any store lists (snippets come and go per
#            store). the names come from the store with that many tracks and
#            the most of them really named: redeye can put every name in one,
#            juno has "Track 1"
#   discogs  the stores' links. one link, or one confirmed by the rules or
#            claude, becomes the record's link. disagreeing ones are kept in
#            discogs_links to settle later
#
# ids stay with their stores across builds: a group keeps the id most of its
# stores had. an id whose stores all moved to another record is kept as
# {"merged_into": <id>}, so nothing pointing at it breaks.
#
# local only for now: diig-registry/diig/diig.json. in a folder of its own,
# since jobs read every json at the top of diig-registry as a store

OUT_FILE = "diig-registry/diig/diig.json"
CONFLICTS_FILE = "reports/diig-discogs-conflicts.csv"

# whose spelling wins a tie, best first
FIELD_PRIORITY = ["yoyaku", "redeye", "hardwax", "vinylunderground", "decks", "phonica", "juno"]
# whose track names win a tie. redeye's own pages mangle them at times
TRACK_PRIORITY = ["yoyaku", "phonica", "hardwax", "decks", "vinylunderground", "juno", "redeye"]

# an index bucket bigger than this is a common name ("Various - Untitled"),
# not one record. it's skipped, other keys still group its members
MAX_BUCKET = 60


def arg(name, default=None):
    if name in sys.argv:
        return sys.argv[sys.argv.index(name) + 1]
    return default


def stores():
    return dig.stores_list("diig-registry")


def priority(order, key):
    store = key.split("-")[0]
    return order.index(store) if store in order else len(order)


# ── grouping ─────────────────────────────────────────────────────────────────

# the index keys an entry can be grouped on: its catno, its label + catalogue
# number (hardwax lists "002" for MANEUVER02), and its artist + title
def index_keys(r):
    keys = []
    cat = norm_cat(r.get("cat", ""))
    if cat and not cat.isdigit():
        keys.append(f"cat:{cat}")
    num = re.search(r"(\d+)$", cat)
    label = norm_label(r.get("label", ""))
    if num and label:
        keys.append(f"num:{label}|{num.group(1)}")
    at = at_key(r.get("artist", ""), r.get("title", ""))
    if at:
        keys.append(f"at:{at}")
    return keys


# the catalogue number without a variant suffix: FM12077YV, FM12077GS and
# LLL002R are colours and represses of FM12077 and LLL002, one record here.
# a bare number (hardwax's "002") is returned as is
def cat_base(cat):
    c = norm_cat(cat)
    if not c or c.isdigit():
        return c
    return re.sub(r"(?<=\d)[a-z]+$", "", c)


# the tracklists agree both ways: an lp holds every track of the 12" taken
# from it, but not the other way round. None when there's nothing to compare
def tracks_agree(a, b):
    ab = track_overlap(a.get("track_names"), b.get("track_names"))
    ba = track_overlap(b.get("track_names"), a.get("track_names"))
    have = [x for x in (ab, ba) if x is not None]
    if not have:
        return None
    return min(have) >= 0.5


# the same record, stricter than matching against discogs: two stores both
# give a catno far more often than discogs search hits do, so a different
# catno always means a different record (Soulful Dubs 02 and 03, a song on
# two labels), and the same catno still needs the title or tracks to agree
# (ML9002 and ML9002LP: a 12" and the album it came from)
def same_record(a, b):
    ca, cb = cat_base(a.get("cat", "")), cat_base(b.get("cat", ""))
    label = label_match(a.get("label", ""), [b.get("label", "")])
    title = title_match(a.get("title", ""), b.get("title", ""))
    artist = artist_match(a.get("artist", ""), b.get("artist", ""))
    tracks = tracks_agree(a, b)
    if tracks is False and not title:
        return False

    full_a, full_b = bool(ca) and not ca.isdigit(), bool(cb) and not cb.isdigit()
    if full_a and full_b:
        return ca == cb and (title or tracks is True)
    if ca and cb:
        # a bare number on one side or both: the same number on the same label
        if not (cat_equal(ca, cb) and label):
            return False
        return title or artist or tracks is True
    # no catno to go on (phonica gives none)
    return artist and title and (label or tracks is True)


def group(entries, stats):
    parent = {k: k for k in entries}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    buckets = collections.defaultdict(list)
    for key, r in entries.items():
        for ik in index_keys(r):
            buckets[ik].append(key)

    tried = set()
    for ik, keys in buckets.items():
        if len(keys) < 2:
            continue
        if len(keys) > MAX_BUCKET:
            stats["big_buckets"] += 1
            continue
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if find(a) == find(b) or (a, b) in tried:
                    continue
                tried.add((a, b))
                stats["pairs"] += 1
                if same_record(entries[a], entries[b]):
                    parent[find(a)] = find(b)

    groups = collections.defaultdict(list)
    for key in entries:
        groups[find(key)].append(key)
    return list(groups.values())


# ── canonical data ───────────────────────────────────────────────────────────

def all_caps(s):
    letters = [c for c in s if c.isalpha()]
    return len(letters) > 3 and all(c.isupper() for c in letters)


# majority by normalised value, then the cleanest spelling of it, then store
# priority
def pick(entries, keys, field, norm, quality):
    values = [(k, (entries[k].get(field) or "").strip()) for k in keys]
    values = [(k, v) for k, v in values if norm(v)]
    if not values:
        return ""
    votes = collections.Counter(norm(v) for _, v in values)
    best_norm = max(votes, key=lambda n: (votes[n], -min(priority(FIELD_PRIORITY, k)
                                                         for k, v in values if norm(v) == n)))
    picks = [(k, v) for k, v in values if norm(v) == best_norm]
    picks.sort(key=lambda kv: (quality(kv[1]), -priority(FIELD_PRIORITY, kv[0])), reverse=True)
    return picks[0][1]


def name_quality(v):
    return (not all_caps(v),)


# the plain title: "The Age Of Love" over "The Age Of Love (reissue)"
def title_quality(v):
    return (not all_caps(v), "[" not in v and '"' not in v, -len(v))


# the full catno, unspaced, and the base one over a colour variant
def cat_quality(v):
    return (bool(re.search(r"[A-Za-z]", v)), " " not in v, -len(v))


POSITION = discogs_match.POSITION
DURATION = re.compile(r"\s*\(\d{1,2}:\d{2}\)\s*$")


# a store's track name as shown: no side position, duration or quotes
def display_track(name):
    t = POSITION.sub("", name or "")
    t = DURATION.sub("", t)
    return t.replace('"', "").strip()


# the track count is the most any store lists. the names come from a store
# with that many, most of them really named
def pick_tracks(entries, keys):
    count = max(max(len(entries[k].get("track_names") or []), len(entries[k].get("track_urls") or []))
                for k in keys)

    def quality(k):
        names = entries[k].get("track_names") or []
        named = len({track_name(n) for n in names} - {""})
        return (len(names) == count, named, -priority(TRACK_PRIORITY, k))

    best = max(keys, key=quality)
    names = entries[best].get("track_names") or []
    if not {track_name(n) for n in names} - {""}:
        return count, [], None
    return count, [display_track(n) for n in names], best


# the whole list from one store: stores give the small, medium and large
# sizes in that order, which the apps choose from
def pick_artworks(entries, keys):
    for k in sorted(keys, key=lambda k: priority(FIELD_PRIORITY, k)):
        art = entries[k].get("artworks") or []
        if art:
            return art
    return []


# the stores' discogs links: one, or one the rules or claude confirmed, is the
# record's link. disagreeing ones are kept to settle later
def pick_discogs(entries, keys):
    links = {}
    for k in keys:
        d = entries[k].get("discogs")
        if not discogs_match.is_linked(d):
            continue
        link = links.setdefault(d["id"], {"id": d["id"], "url": d.get("url", ""), "stores": [], "verified": False})
        link["stores"].append(k)
        if trusted(d):
            link["verified"] = True
    ranked = sorted(links.values(), key=lambda l: (l["verified"], len(l["stores"])), reverse=True)
    if not ranked:
        return None, []
    if len(ranked) == 1:
        return ranked[0], []
    verified = [l for l in ranked if l["verified"]]
    return (verified[0] if len(verified) == 1 else None), ranked


def build_record(entries, keys):
    keys = sorted(keys, key=lambda k: priority(FIELD_PRIORITY, k))
    count, tracks, tracks_from = pick_tracks(entries, keys)
    rec = {
        "artist": pick(entries, keys, "artist", fold, name_quality),
        "title": pick(entries, keys, "title", norm_title, title_quality),
        "label": pick(entries, keys, "label", norm_label, name_quality),
        "cat": pick(entries, keys, "cat", cat_base, cat_quality),
        "track_count": count,
        "tracks": tracks,
        "artworks": pick_artworks(entries, keys),
        "stores": keys,
    }
    if tracks_from:
        rec["tracks_from"] = tracks_from
    link, links = pick_discogs(entries, keys)
    if link:
        rec["discogs"] = link
    if links:
        rec["discogs_links"] = links
    return rec


# ── ids ──────────────────────────────────────────────────────────────────────

def load_previous():
    if os.path.exists(OUT_FILE):
        return json.load(open(OUT_FILE, encoding="utf-8"))
    return {"meta": {"next_id": 1}, "releases": {}, "index": {}}


def new_id(meta):
    n = meta["next_id"]
    meta["next_id"] = n + 1
    return f"dg-{n:06d}"


# biggest groups choose first: each keeps the id most of its stores had
def assign_ids(groups, prev, stats):
    meta = dict(prev["meta"])
    old_index = prev["index"]
    claimed = {}
    for keys in sorted(groups, key=lambda g: (-len(g), min(g))):
        olds = collections.Counter(old_index[k] for k in keys if k in old_index and old_index[k] not in claimed)
        if olds:
            gid = max(olds, key=lambda i: (olds[i], -int(i.split("-")[1])))
            stats["kept_ids"] += 1
        else:
            gid = new_id(meta)
            stats["new_ids"] += 1
        claimed[gid] = keys
    return meta, claimed


def merged_records(prev, index):
    merged = {}
    for gid, rec in prev["releases"].items():
        if "merged_into" in rec:
            merged[gid] = rec
            continue
        moved = collections.Counter(index[k] for k in rec.get("stores", []) if k in index)
        if moved and gid not in moved:
            merged[gid] = {"merged_into": moved.most_common(1)[0][0]}
    return merged


# ── report ───────────────────────────────────────────────────────────────────

def report(releases, entries, stats):
    live = {g: r for g, r in releases.items() if "merged_into" not in r}
    spans = collections.Counter(len({k.split("-")[0] for k in r["stores"]}) for r in live.values())
    with_link = sum(1 for r in live.values() if "discogs" in r)
    conflicts = [(g, r) for g, r in live.items() if r.get("discogs_links")]
    unsettled = sum(1 for _, r in conflicts if "discogs" not in r)
    named = sum(1 for r in live.values() if r["tracks"])

    print(f"{len(entries)} store releases -> {len(live)} diig records "
          f"({stats['new_ids']} new ids, {stats['kept_ids']} kept, "
          f"{sum(1 for r in releases.values() if 'merged_into' in r)} merged)")
    print(f"  {stats['pairs']} pairs compared, {stats['big_buckets']} oversized index buckets skipped")
    print("  stores per record: " + ", ".join(f"{n}: {spans[n]}" for n in sorted(spans)))
    print(f"  {with_link} with a discogs link, {len(conflicts)} where the stores' links disagree "
          f"({unsettled} unsettled), {named} with named tracks")

    print("\nlargest records, worth a look for over-grouping:")
    for g, r in sorted(live.items(), key=lambda gr: -len(gr[1]["stores"]))[:12]:
        print(f"  {g} {len(r['stores'])}: {r['artist']} - {r['title']} [{r['cat']}]")
        if "-verbose" in sys.argv:
            for k in r["stores"]:
                e = entries[k]
                print(f"      {k}: {e.get('artist')} - {e.get('title')} [{e.get('cat')}]")

    if conflicts and "-dry-run" not in sys.argv:
        os.makedirs(os.path.dirname(CONFLICTS_FILE), exist_ok=True)
        with open(CONFLICTS_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["diig_id", "artist", "title", "label", "cat", "chosen", "links"])
            for g, r in conflicts:
                w.writerow([g, r["artist"], r["title"], r["label"], r["cat"],
                            r.get("discogs", {}).get("url", ""),
                            " ".join(f"{l['url']} ({'+'.join(l['stores'])}{', verified' if l['verified'] else ''})"
                                     for l in r["discogs_links"])])
        print(f"\nstores' disagreeing discogs links: {CONFLICTS_FILE}")


def display_help():
    print("xref.py: build the diig registry, one record per release across all stores")
    print("")
    print("  groups every store's releases on their own data (catno, label,")
    print("  artist, title, tracks) and writes diig-registry/diig/diig.json:")
    print("    releases  diig id -> artist, title, label, cat, tracks, artworks,")
    print("              the store keys, and the discogs link(s)")
    print("    index     store key -> diig id")
    print("  ids are kept across builds. no discogs requests, nothing written to")
    print("  firebase or the store registries")
    print("")
    print("  -dry-run            print the report, write nothing")
    print("  -verbose            list the store entries of the largest records")


def main():
    if "-help" in sys.argv:
        display_help()
        return

    print(f"loading {', '.join(stores())}", flush=True)
    entries = {}
    for store in stores():
        for key, r in dig.load_registry(store).items():
            if not dig.validate_release(key, r):
                entries[key] = r

    stats = collections.Counter()
    groups = group(entries, stats)
    prev = load_previous()
    meta, claimed = assign_ids(groups, prev, stats)
    index = {k: gid for gid, keys in claimed.items() for k in keys}
    releases = merged_records(prev, index)
    for gid, keys in claimed.items():
        releases[gid] = build_record(entries, keys)
    releases = dict(sorted(releases.items()))

    report(releases, entries, stats)
    if "-dry-run" in sys.argv:
        print("\ndry run: nothing written")
        return
    meta.update(version=1, built=datetime.datetime.now().isoformat(timespec="seconds"))
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "releases": releases, "index": dict(sorted(index.items()))},
                  f, indent=1, ensure_ascii=False)
    print(f"\nwrote {OUT_FILE}")


if __name__ == "__main__":
    main()
