import dig
import taste as tastes
import sys
import os
import json
import re
import datetime
import subprocess
from pydantic import BaseModel

# weekly curated homepage. scores this week's new releases against the taste
# profile (taste.py), ranks what is charting across stores for the hype shelf,
# shortlists london gigs (ra.py), then has claude pick and write up the page.
# output goes to diig-registry/homepage/{week}.json and rtdb /homepage
#   python3 homepage.py [-key '<service account json>'] [-days 7] [-dry-run] [-local-only]
#   -dry-run:    no llm call and no writes, prints the shortlists
#   -local-only: no firebase reads or writes (no likes, no rtdb patch)

DB = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app"
REG_DIR = "diig-registry"
MODEL = "claude-sonnet-5-5"
USER = "polymonster"
HYPE_COUNT = 32
PICK_SHORTLIST = 60
GIG_SHORTLIST = 40
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

# fields kept on a homepage card, enough for the web tile, player and links
CARD_FIELDS = ("store", "artist", "title", "label", "cat", "link", "artworks", "track_names", "track_urls", "store_tags", "discogs")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def load_store_regs(stores):
    return {store: dig.load_registry(store) for store in stores}


# registry keys for a store as they were at the last commit before `cutoff`,
# used to find releases first seen this week (the registry has no added date)
def keys_before(store, cutoff):
    rev = subprocess.run(["git", "-C", REG_DIR, "rev-list", "-1", f"--before={cutoff.isoformat()}", "HEAD", "--", f"{store}.json"],
                         capture_output=True, text=True).stdout.strip()
    if not rev:
        return None
    blob = subprocess.run(["git", "-C", REG_DIR, "show", f"{rev}:{store}.json"], capture_output=True, text=True, encoding="utf-8")
    if blob.returncode != 0:
        return None
    return set(json.loads(blob.stdout).keys())


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
        facts += [f"#{p} on the {s} {v.replace('_', ' ')}" for s, v, p in charts]
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


# ── llm ─────────────────────────────────────────────────────────────────────────

class Pick(BaseModel):
    release_id: str
    blurb: str


class Gig(BaseModel):
    event_id: str
    blurb: str


class Homepage(BaseModel):
    headline: str
    intro: str
    picks: list[Pick]
    gigs: list[Gig]


SYSTEM = """You curate the weekly homepage for diig, a record digging app that \
aggregates new vinyl from independent shops (Juno, Redeye, Phonica, Yoyaku, Hard Wax, \
Decks, Vinyl Underground). The page is shared by everyone who uses diig.

You are given a shortlist of records that arrived in the shops this week and a shortlist \
of upcoming London gigs. Each record is in one of two groups: "known" (an artist the \
curator already follows) or "discovery" (an artist new to them, found through related \
labels, styles or charts).

Choose exactly {picks} picks: {half} from "known" and {half} from "discovery". Keep variety \
across labels, shops and styles. Choose exactly {gigs} gigs, spread across the dates, \
favouring lineups with the featured artists.

Write for a reader who may never have heard of the artist. A pick blurb is three or four \
sentences, about 70 to 90 words, in a dry, knowledgeable record-shop voice with no hype \
words. Introduce the artist or label briefly (where they are from, what they are known \
for, notable earlier releases or aliases) and then say what this record is: format, \
remixers, collaborators, reissue or new material, and anything notable in the track \
titles or credits. Only state background you are confident is accurate; if an artist is \
too obscure to know, describe the record and the label instead of guessing. You have not \
heard the records, so do not describe the sound beyond what the styles and titles support.

Never mention the curator, a collection, likes by the curator, purchases or why a record \
was chosen. Chart positions and sold-out history may be mentioned when they add something.

Gig blurbs are two or three sentences: the date, venue and who is playing, with a line \
of context on the headliners. The headline is a few words and the intro is two sentences \
at most, about the week as a whole. Use the exact release_id and event_id values from \
the input.""".format(picks=PICK_COUNT, half=PICK_COUNT // len(PICK_GROUPS), gigs=GIG_COUNT)


def llm_input(taste, picks, gigs, week):
    top_styles = sorted(taste["styles"].items(), key=lambda x: -x[1])[:12]
    return json.dumps({
        "week": week,
        "styles": [s for s, _ in top_styles],
        "releases": [{
            "release_id": c["id"],
            "artist": c.get("artist", ""),
            "title": c.get("title", ""),
            "label": c.get("label", ""),
            "cat": c.get("cat", ""),
            "shops": [s["store"] for s in c["stores"]],
            "tracks": (c.get("track_names") or [])[:6],
            "styles": c["_styles"],
            "group": c["_group"],
            "facts": c["_facts"],
        } for c in picks],
        "gigs": [{
            "event_id": g["id"],
            "title": g["title"],
            "date": g["date"],
            "venue": g["venue"],
            "lineup": g["lineup"][:12],
            "featured_artists": g["_in_collection"] + g["_adjacent"],
            "attending": g["attending"],
        } for g in gigs],
    }, ensure_ascii=False)


def curate(taste, picks, gigs, week):
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": llm_input(taste, picks, gigs, week)}],
        output_format=Homepage,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"curation refused: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("curation hit max_tokens")
    print(f"llm usage: {response.usage.input_tokens} in, {response.usage.output_tokens} out")
    return response.parsed_output


# ── output ──────────────────────────────────────────────────────────────────────

def strip_private(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def assemble(curated, picks, gigs, hype, week):
    picks_by_id = {c["id"]: c for c in picks}
    gigs_by_id = {g["id"]: g for g in gigs}
    out_gigs = []
    chosen = []
    for p in curated.picks:
        c = picks_by_id.pop(p.release_id, None)
        if c:
            chosen.append((c, p.blurb))
        else:
            print(f"warning: dropping unknown release id from llm: {p.release_id}")
    # hold each group to its half of the page in the llm's order, top up a short
    # group from its shortlist, then let over quota picks fill any space left
    quota = PICK_COUNT // len(PICK_GROUPS)
    within, over = [], []
    for c, blurb in chosen:
        n = sum(1 for x, _ in within if x["_group"] == c["_group"])
        (within if n < quota else over).append((c, blurb))
    for name in PICK_GROUPS:
        short = quota - sum(1 for x, _ in within if x["_group"] == name)
        for c in [c for c in picks_by_id.values() if c["_group"] == name][:max(short, 0)]:
            print(f"warning: topping up {name} picks with {c['id']}")
            within.append((c, ""))
            picks_by_id.pop(c["id"])
    out_picks = [dict(strip_private(c), blurb=b) for c, b in within + over]
    for g in curated.gigs:
        ev = gigs_by_id.pop(g.event_id, None)
        if ev:
            out_gigs.append(dict(strip_private(ev), blurb=g.blurb))
        else:
            print(f"warning: dropping unknown event id from llm: {g.event_id}")
    out_picks, out_gigs = out_picks[:PICK_COUNT], out_gigs[:GIG_COUNT]
    # top up from the shortlists (already in score order) if the llm came back
    # short, so the page always fills whole rows. these go without a blurb
    for c in list(picks_by_id.values())[:PICK_COUNT - len(out_picks)]:
        print(f"warning: topping up picks with {c['id']}")
        out_picks.append(dict(strip_private(c), blurb=""))
    for ev in list(gigs_by_id.values())[:GIG_COUNT - len(out_gigs)]:
        print(f"warning: topping up gigs with {ev['id']}")
        out_gigs.append(dict(strip_private(ev), blurb=""))
    return {
        "week": week,
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": MODEL,
        "headline": curated.headline,
        "intro": curated.intro,
        "picks": out_picks,
        "gigs": sorted(out_gigs, key=lambda g: g["date"]),
        "hype": hype,
    }


def ensure_read_rule(session):
    rules = session.get(f"{DB}/.settings/rules.json").json()
    if "homepage" in rules["rules"]:
        return
    rules["rules"]["homepage"] = {".read": "auth.uid !== null"}
    response = session.put(f"{DB}/.settings/rules.json", json.dumps(rules, indent=4))
    assert response.status_code == 200, response.text
    print("added /homepage read rule")


def publish(session, page):
    ensure_read_rule(session)
    for path in ("homepage/current", f"homepage/archive/{page['week']}"):
        response = session.put(f"{DB}/{path}.json", json.dumps(page))
        assert response.status_code == 200, response.text
    print(f"published homepage {page['week']}")


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
    gigs = build_gig_shortlist(events, taste, adj_artists)

    if dry_run:
        print("\n── pick shortlist ──")
        for c in picks:
            print(f"{c['_score']:5.1f}  {c['_group']:9}  {c['artist']} - {c['title']} [{c.get('label', '')}] ({', '.join(s['store'] for s in c['stores'])})")
            for w in c["_why"]:
                print(f"         {w}")
            for f in c["_facts"]:
                print(f"         llm fact: {f}")
        print("\n── hype ──")
        for c in hype:
            print(f"  {c['artist']} - {c['title']}  art:{c['store']}  shops:{', '.join(s['store'] for s in c['stores'])}")
        print("\n── gig shortlist ──")
        for g in gigs:
            print(f"  {g['date']} {g['title']} @ {g['venue']}  {g['_in_collection']} {g['_adjacent'][:3]} ({g['attending']})")
        sys.exit(0)

    page = assemble(curate(taste, picks, gigs, week), picks, gigs, hype, week)
    os.makedirs(f"{REG_DIR}/homepage", exist_ok=True)
    open(f"{REG_DIR}/homepage/{week}.json", "w+").write(json.dumps(page, indent=4, ensure_ascii=False))
    print(f"wrote {REG_DIR}/homepage/{week}.json: {len(page['picks'])} picks, {len(page['hype'])} hype, {len(page['gigs'])} gigs")
    if not local_only:
        publish(session, page)
