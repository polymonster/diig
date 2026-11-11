import dig
import taste as tastes
import sys
import os
import json
import re
import datetime
import subprocess
import urllib.parse

# weekly curated page. scores this week's new releases against the taste
# profile (taste.py), ranks what is charting across stores for the hype shelf,
# shortlists london gigs (ra.py), then picks a varied page and writes it up from
# the scoring facts. no llm calls.
# output goes to diig-registry/weekly/{week}.json and rtdb /weekly
#   python3 weekly.py [-key '<service account json>'] [-days 7] [-dry-run] [-local-only]
#   -dry-run:    no writes, prints the shortlists and the page
#   -local-only: no firebase reads or writes (no likes, no rtdb patch)

DB = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app"
REG_DIR = "diig-registry"
USER = "polymonster"
HYPE_COUNT = 32
PICK_SHORTLIST = 60
GIG_SHORTLIST = 40
# gigs from the page's monday up to this many days on
GIG_DAYS = 14
# page counts, chosen to fill whole rows at 2, 3 and 4 columns
PICK_COUNT = 12
# picks are split evenly between artists already collected and artists new to the collection
PICK_GROUPS = ("known", "discovery")
GIG_COUNT = 8

# chart style views and how much a position in each counts towards hype
CHART_VIEWS = {
    "weekly_chart": 1.0,
    "bestsellers": 1.0,
    "sales_chart": 1.0,
    "buzz_chart": 1.0,
    "monthly_chart": 0.6,
    "essentials": 0.4,
}

# fields kept on a weekly card, enough for the web tile, player and links
CARD_FIELDS = ("store", "artist", "title", "label", "cat", "link", "artworks", "track_names", "track_urls", "store_tags", "discogs")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def load_store_regs(stores):
    return {store: dig.load_registry(store) for store in stores}


# registry keys for a store as they were at the last commit before `cutoff`,
# used to find releases first seen this week (the registry has no added date)
def git(*args):
    return subprocess.run(["git", "-C", REG_DIR, *args], capture_output=True, text=True, encoding="utf-8")


# reads <store>/ chunks, or <store>.json at commits from before the split
def keys_before(store, cutoff):
    rev = git("rev-list", "-1", f"--before={cutoff.isoformat()}", "HEAD", "--", f"{store}/", f"{store}.json").stdout.strip()
    if not rev:
        return None
    paths = [p for p in git("ls-tree", "--name-only", rev, f"{store}/").stdout.split() if p.endswith(".json")]
    keys = set()
    for path in sorted(paths) or [f"{store}.json"]:
        blob = git("show", f"{rev}:{path}")
        if blob.returncode != 0:
            return None
        keys.update(json.loads(blob.stdout).keys())
    return keys


def new_release_keys(regs, cutoff):
    new = set()
    for store, reg in regs.items():
        old = keys_before(store, cutoff)
        if old is None:
            # no history that far back, fall back to whatever is in a new releases view now
            print(f"warning: no registry history before {cutoff.date()} for {store}, using new_releases views")
            new |= {k for k, r in reg.items() if any(f.endswith("-new_releases") for f in r)}
        else:
            new |= set(reg.keys()) - old
    return new


# chart positions on a release: [(store, view, position)]
def chart_positions(release, store):
    out = []
    for field, val in release.items():
        if not field.startswith(f"{store}-") or not isinstance(val, int):
            continue
        view = next((v for v in CHART_VIEWS if field.endswith(f"-{v}")), None)
        if view:
            out.append((store, view, val))
    return out


# identities a release can be matched on across stores: its discogs id, and its
# artist + title with bracketed suffixes like "(reissue)" or "[Part 1]" removed
def group_keys(release):
    keys = []
    d = release.get("discogs") or {}
    if d.get("id"):
        keys.append(f"discogs-{d['id']}")
    title = re.sub(r"\s*[\(\[].*?[\)\]]", "", release.get("title", ""))
    # compare without spaces or punctuation so "TOS014" and "TOS 014" match
    def squash(s):
        return re.sub(r"[\W_]+", "", tastes.norm_name(s))
    keys.append(f"at-{squash(release.get('artist', ''))}|{squash(title)}")
    return keys


# group the same record across stores. a union-find over group_keys, so two
# entries join if they share either a discogs id or an artist + title
def group_releases(entries):
    parent = list(range(len(entries)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner = {}
    for i, (_, release, _) in enumerate(entries):
        for k in group_keys(release):
            if k in owner:
                parent[find(i)] = find(owner[k])
            else:
                owner[k] = i
    groups = {}
    for i, entry in enumerate(entries):
        groups.setdefault(find(i), []).append(entry)
    return groups


def like_counts(session):
    likes = session.get(f"{DB}/likes.json").json() or {}
    return {rid: sum(1 for ts in users.values() if ts) for rid, users in likes.items()}


def user_likes(session):
    uid = tastes.find_uid(session, USER)
    return set((session.get(f"{DB}/users/{uid}/likes.json").json() or {}).keys()) if uid else set()


def taste_weight(e):
    return e["collection"] * 3 + e["unliked"] * 3 + e["liked"]


# artists seen on labels the user collects, and labels that release artists the
# user collects. computed over the whole registry, no extra api calls
def adjacency(regs, taste):
    artists, labels = taste["artists"], taste["labels"]
    adj_artists, adj_labels = set(), set()
    for reg in regs.values():
        for release in reg.values():
            label = tastes.norm_name(release.get("label", ""))
            keys = tastes.artist_keys(release.get("artist", ""), artists)
            if label in labels and taste_weight(labels[label]) >= 2:
                adj_artists |= {k for k in keys if k not in artists}
            if any(k in artists for k in keys) and label and label not in labels:
                adj_labels.add(label)
    return adj_artists, adj_labels


def card(key, release, group=None):
    c = {f: release[f] for f in CARD_FIELDS if f in release}
    c["id"] = key
    if group:
        # one entry per store, preferring an in stock listing
        per_store = {}
        for k, r, s in group:
            oos = bool((r.get("store_tags") or {}).get("out_of_stock"))
            if s not in per_store or (per_store[s]["out_of_stock"] and not oos):
                per_store[s] = {
                    "store": s, "id": k, "link": r.get("link", ""),
                    "preorder": bool((r.get("store_tags") or {}).get("preorder")),
                    "out_of_stock": oos,
                }
        c["stores"] = [per_store[s] for s in sorted(per_store)]
    return c


# pick which store's entry fronts each card, rotating across the stores a
# record is available on so artwork requests are spread over store cdns
def rotate_cards(ranked_groups):
    usage = {}
    cards = []
    for group in ranked_groups:
        with_art = [g for g in group if g[1].get("artworks")] or group
        key, release, store = min(with_art, key=lambda g: (usage.get(g[2], 0), g[2]))
        usage[store] = usage.get(store, 0) + 1
        cards.append(card(key, release, group))
    return cards


def build_hype(regs, likes):
    charting = []
    for store, reg in regs.items():
        for key, release in reg.items():
            if chart_positions(release, store) and not dig.validate_release(key, release):
                charting.append((key, release, store))
    scored = []
    for group in group_releases(charting).values():
        positions = [p for k, r, s in group for p in chart_positions(r, s)]
        chart_stores = {p[0] for p in positions}
        chart_score = sum(CHART_VIEWS[view] / (1 + pos / 20) for _, view, pos in positions)
        sold = any((r.get("store_tags") or {}).get("has_sold_out") for _, r, _ in group)
        n_likes = sum(likes.get(k, 0) for k, _, _ in group)
        score = len(chart_stores) * 3 + chart_score + (1 if sold else 0) + n_likes * 1.5
        scored.append((score, group))
    scored.sort(key=lambda s: -s[0])
    return rotate_cards([g for _, g in scored[:HYPE_COUNT]])


def signal_text(e):
    parts = []
    if e["collection"]:
        parts.append(f"{e['collection']} in collection")
    if e["unliked"]:
        parts.append(f"{e['unliked']} bought")
    if e["liked"]:
        parts.append(f"{e['liked']} liked")
    return ", ".join(parts)


def score_pick(release, store, taste, adj_artists, adj_labels, top_styles, likes_n):
    artists, labels = taste["artists"], taste["labels"]
    score, why, facts = 0.0, [], []
    keys = tastes.artist_keys(release.get("artist", ""), artists)
    # the two strongest artist matches count, so a long VA tracklist can't
    # outscore a single artist the user collects
    matched = sorted((artists[k] for k in keys if k in artists), key=lambda e: -taste_weight(e))[:2]
    for e in matched:
        score += 10 + min(taste_weight(e), 10)
        why.append(f"artist {e['name']}: {signal_text(e)}")
    adjacent = [k for k in keys if k not in artists and k in adj_artists]
    if adjacent and not matched:
        score += 4
        why.append("artist releases on labels in the collection")
    label = tastes.norm_name(release.get("label", ""))
    if label in labels:
        e = labels[label]
        score += 6 + min(taste_weight(e), 6)
        why.append(f"label {e['name']}: {signal_text(e)}")
    elif label in adj_labels:
        score += 3
        why.append("label releases artists in collection")
    styles = [f for f, v in release.items() if v == "genre_tag"]
    style_hits = [s for s in styles if s in top_styles]
    if style_hits:
        score += min(len(style_hits), 3)
    charts = chart_positions(release, store)
    if charts:
        score += 2 * len(charts)
        why.append("charting " + ", ".join(f"{v} #{p}" for _, v, p in charts))
        # a release can sit in several sections of the same chart, quote its best spot
        best = {}
        for s, v, p in charts:
            best[(s, v)] = min(p, best.get((s, v), p))
        facts += [f"#{p} on the {s} {v.replace('_', ' ')}" for (s, v), p in best.items()]
    if (release.get("store_tags") or {}).get("has_sold_out"):
        score += 2
        why.append("has sold out before")
        facts.append(f"has sold out before at {store}")
    if likes_n:
        score += 1.5 * likes_n
        why.append(f"{likes_n} diig likes")
        facts.append(f"liked by {likes_n} diig users")
    # why is private scoring detail for -dry-run only, facts are safe to publish
    return score, why, styles, facts, bool(matched)


def build_pick_shortlist(regs, new_keys, taste, likes, liked_by_user):
    adj_artists, adj_labels = adjacency(regs, taste)
    top_styles = {s for s, _ in sorted(taste["styles"].items(), key=lambda x: -x[1])[:20]}
    entries = [(k, r, s) for s, reg in regs.items() for k, r in reg.items()
               if k in new_keys and not dig.validate_release(k, r)]
    pools = {g: [] for g in PICK_GROUPS}
    for group in group_releases(entries).values():
        if any(k in liked_by_user for k, _, _ in group):
            continue
        best = None
        for key, release, store in group:
            scored = score_pick(release, store, taste, adj_artists, adj_labels, top_styles, likes.get(key, 0))
            if not best or scored[0] > best[0]:
                best = scored
        if best[0] > 0:
            pools["known" if best[4] else "discovery"].append((best, group))
    # an even split between known artists and discoveries, each pool in score order
    shortlist = []
    for name, pool in pools.items():
        pool.sort(key=lambda s: -s[0][0])
        shortlist += [(name, scored, group) for scored, group in pool[:PICK_SHORTLIST // len(PICK_GROUPS)]]
    cards = rotate_cards([g for _, _, g in shortlist])
    for c, (name, (score, why, styles, facts, _), _) in zip(cards, shortlist):
        c["_group"] = name
        c["_score"] = round(score, 1)
        c["_why"] = why
        c["_styles"] = styles
        c["_facts"] = facts
    return cards


def build_gig_shortlist(events, taste, adj_artists):
    artists = taste["artists"]
    scored = []
    for ev in events:
        hits, adj = [], []
        for name in ev["lineup"]:
            k = tastes.norm_name(name)
            if k in artists:
                hits.append(name)
            elif k in adj_artists:
                if name not in adj:
                    adj.append(name)
        score = 10 * len(hits) + 3 * len(adj) + ev["attending"] / 200
        scored.append((score, dict(ev, _in_collection=hits, _adjacent=adj)))
    scored.sort(key=lambda s: -s[0])
    return [ev for _, ev in scored[:GIG_SHORTLIST]]


# ── selection and text ──────────────────────────────────────────────────────────
# no llm: the page is chosen and written from the scores and facts above

def primary_style(c):
    return c["_styles"][0] if c.get("_styles") else ""


# take `count` from `items` in order, first under the strict rules, then relaxing
# them one at a time so the page still fills. each rule is (key_fn, max_per_key)
def take_diverse(items, count, rules):
    chosen = []
    for n in range(len(rules), -1, -1):
        active = rules[:n]
        for item in items:
            if len(chosen) >= count:
                return chosen
            if any(item is c for c in chosen):
                continue
            if all(sum(1 for c in chosen if key(c) and key(c) == key(item)) < cap for key, cap in active):
                chosen.append(item)
    return chosen


PICK_RULES = [
    (lambda c: tastes.norm_name(c.get("label", "")), 1),
    (primary_style, 2),
]


# each group takes its half in score order, kept varied across labels and styles.
# a group short of candidates is filled from the other
def select_picks(cards):
    quota = PICK_COUNT // len(PICK_GROUPS)
    chosen = []
    for name in PICK_GROUPS:
        chosen += take_diverse([c for c in cards if c["_group"] == name], quota, PICK_RULES)
    rest = [c for c in cards if not any(c is x for x in chosen)]
    chosen += take_diverse(rest, PICK_COUNT - len(chosen), PICK_RULES)
    return chosen


def pick_blurb(c):
    parts = []
    if c.get("_styles"):
        parts.append(" · ".join(c["_styles"][:3]))
    n = len(c.get("track_names") or [])
    if n:
        parts.append(f"{n} track{'s' if n != 1 else ''}")
    facts = c.get("_facts") or []
    if facts:
        parts.append(", ".join(facts))
    if len(c.get("stores") or []) > 1:
        parts.append(f"in {len(c['stores'])} shops")
    if any(s.get("preorder") for s in c.get("stores") or []):
        parts.append("pre-order")
    return ". ".join(p[:1].upper() + p[1:] for p in parts) + "." if parts else ""


# gigs in the page's window, best scored first, at most two a night and one per venue
GIG_RULES = [
    (lambda g: g["venue"], 1),
    (lambda g: g["date"], 2),
]


def select_gigs(gigs):
    return sorted(take_diverse(gigs, GIG_COUNT, GIG_RULES), key=lambda g: g["date"])


def gig_blurb(g):
    lineup = g.get("lineup") or []
    parts = []
    if lineup:
        parts.append(", ".join(lineup[:4]) + (f" and {len(lineup) - 4} more" if len(lineup) > 4 else ""))
    genres = [x for x in (g.get("genres") or []) if isinstance(x, str)]
    if genres:
        parts.append(" · ".join(genres[:3]))
    if g.get("attending"):
        parts.append(f"{g['attending']} going")
    return ". ".join(parts) + "." if parts else ""


def headline(picks, week):
    counts = {}
    for c in picks:
        for s in c.get("_styles", [])[:2]:
            counts[s] = counts.get(s, 0) + 1
    top = [s for s, _ in sorted(counts.items(), key=lambda x: -x[1])[:2]]
    return " and ".join(top) if top else f"Week {week.split('-W')[-1]}"


def intro(n_new, n_shops, hype, gigs):
    out = [f"{n_new} new records across {n_shops} shops this week."]
    if hype:
        h = hype[0]
        n = len(h.get("stores") or [])
        out.append(f"{h.get('artist', '')} - {h.get('title', '')} tops the charts" + (f" in {n} shops." if n > 1 else "."))
    if gigs:
        out.append(f"{len(gigs)} London gigs from {format_day(gigs[0]['date'])} to {format_day(gigs[-1]['date'])}.")
    return " ".join(out)


def format_day(date):
    d = datetime.date.fromisoformat(date)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


# ── output ──────────────────────────────────────────────────────────────────────

def strip_private(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def assemble(picks, gigs, hype, week, n_new, n_shops):
    chosen = select_picks(picks)
    chosen_gigs = select_gigs(gigs)
    out_picks = [dict(strip_private(c), blurb=pick_blurb(c)) for c in chosen]
    out_gigs = [dict(strip_private(g), blurb=gig_blurb(g)) for g in chosen_gigs]
    return {
        "week": week,
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "headline": headline(chosen, week),
        "intro": intro(n_new, n_shops, hype, chosen_gigs),
        "picks": out_picks,
        "gigs": out_gigs,
        "hype": hype,
    }


def ensure_read_rule(session):
    rules = session.get(f"{DB}/.settings/rules.json").json()
    if "weekly" in rules["rules"]:
        return
    rules["rules"]["weekly"] = {".read": "auth.uid !== null"}
    response = session.put(f"{DB}/.settings/rules.json", json.dumps(rules, indent=4))
    assert response.status_code == 200, response.text
    print("added /weekly read rule")


def publish(session, page):
    ensure_read_rule(session)
    for path in ("weekly/current", f"weekly/archive/{page['week']}"):
        response = session.put(f"{DB}/{path}.json", json.dumps(page))
        assert response.status_code == 200, response.text
    print(f"published weekly {page['week']}")


if __name__ == "__main__":
    dry_run = "-dry-run" in sys.argv
    local_only = "-local-only" in sys.argv
    days = int(arg("-days", 7))

    now = datetime.datetime.now(datetime.timezone.utc)
    # runs sunday night, so the page is keyed to the iso week starting next day
    iso = (now + datetime.timedelta(days=1)).isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"

    taste = json.loads(open(tastes.TASTE_FILE, "r").read())
    stores = json.loads(open("stores.json", "r").read())
    regs = load_store_regs(stores)

    session = None
    likes, liked_by_user = {}, set()
    if not local_only:
        dig.setup_firebase_auth()
        session = dig.auth_session()
        likes = like_counts(session)
        liked_by_user = user_likes(session)

    new_keys = new_release_keys(regs, now - datetime.timedelta(days=days))
    print(f"{len(new_keys)} new releases in the last {days} days")

    hype = build_hype(regs, likes)
    picks = build_pick_shortlist(regs, new_keys, taste, likes, liked_by_user)
    adj_artists, _ = adjacency(regs, taste)
    ra_file = f"{REG_DIR}/ra/london.json"
    events = json.loads(open(ra_file, "r").read())["events"] if os.path.exists(ra_file) else []
    # only gigs in the page's window, falling back to anything upcoming on a thin fortnight
    monday = datetime.date.fromisocalendar(iso.year, iso.week, 1)
    window = [e for e in events if monday.isoformat() <= e["date"] < (monday + datetime.timedelta(days=GIG_DAYS)).isoformat()]
    events = window if len(window) >= GIG_COUNT else [e for e in events if e["date"] >= monday.isoformat()]
    gigs = build_gig_shortlist(events, taste, adj_artists)

    if dry_run:
        print("\n── pick shortlist ──")
        for c in picks:
            print(f"{c['_score']:5.1f}  {c['_group']:9}  {c['artist']} - {c['title']} [{c.get('label', '')}] ({', '.join(s['store'] for s in c['stores'])})")
            for w in c["_why"]:
                print(f"         {w}")
            for f in c["_facts"]:
                print(f"         fact: {f}")
        print("\n── hype ──")
        for c in hype:
            print(f"  {c['artist']} - {c['title']}  art:{c['store']}  shops:{', '.join(s['store'] for s in c['stores'])}")
        print("\n── gig shortlist ──")
        for g in gigs:
            print(f"  {g['date']} {g['title']} @ {g['venue']}  {g['_in_collection']} {g['_adjacent'][:3]} ({g['attending']})")

    n_shops = sum(1 for reg in regs.values() if new_keys & reg.keys())
    page = assemble(picks, gigs, hype, week, len(new_keys), n_shops)
    if dry_run:
        print(f"\n── page ──\n{page['headline']}\n{page['intro']}")
        for c in page["picks"]:
            print(f"  {c['artist']} - {c['title']}: {c['blurb']}")
        for g in page["gigs"]:
            print(f"  {g['date']} {g['venue']}: {g['blurb']}")
        sys.exit(0)

    os.makedirs(f"{REG_DIR}/weekly", exist_ok=True)
    open(f"{REG_DIR}/weekly/{week}.json", "w+").write(json.dumps(page, indent=4, ensure_ascii=False))
    print(f"wrote {REG_DIR}/weekly/{week}.json: {len(page['picks'])} picks, {len(page['hype'])} hype, {len(page['gigs'])} gigs")
    if not local_only:
        publish(session, page)
