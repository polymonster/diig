import dig
import taste as tastes
import sys
import os
import json
import re
import datetime
import subprocess
import urllib.parse
import concurrent.futures
import anthropic
from pydantic import BaseModel

# weekly curated page. scores this week's new releases against the taste
# profile (taste.py), ranks what is charting across stores for the hype shelf,
# shortlists london gigs (ra.py), then has claude pick and write up the page.
# output goes to diig-registry/weekly/{week}.json and rtdb /weekly
#   python3 weekly.py [-key '<service account json>'] [-days 7] [-dry-run] [-local-only]
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
# the llm shortlists more than the page shows, so picks with a review found can be preferred
PICK_CANDIDATES = PICK_COUNT * 2
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


class Gig(BaseModel):
    event_id: str
    blurb: str


class Weekly(BaseModel):
    headline: str
    intro: str
    picks: list[Pick]
    gigs: list[Gig]


SYSTEM = """You curate the weekly page for diig, a record digging app that \
aggregates new vinyl from independent shops (Juno, Redeye, Phonica, Yoyaku, Hard Wax, \
Decks, Vinyl Underground). The page is shared by everyone who uses diig.

You are given a shortlist of records that arrived in the shops this week and a shortlist \
of upcoming London gigs. Each record is in one of two groups: "known" (an artist the \
curator already follows) or "discovery" (an artist new to them, found through related \
labels, styles or charts).

Choose exactly {picks} picks in order of preference: {half} from "known" and {half} from \
"discovery". Keep variety across labels, shops and styles. Not all of them will make the \
page, so the earlier picks in each group are the ones you most want shown. Choose exactly \
{gigs} gigs, spread across the dates, favouring lineups with the featured artists.

Picks get no blurb from you, their write-ups come from published reviews found separately.

Never mention the curator, a collection, likes by the curator, purchases or why a record \
was chosen.

Gig blurbs are two or three sentences in a dry, knowledgeable voice with no hype words: \
the date, venue and who is playing, with a line of context on the headliners. The \
headline is a few words and the intro is two sentences at most, about the week as a \
whole. Use the exact release_id and event_id values from the input.""".format(picks=PICK_CANDIDATES, half=PICK_CANDIDATES // len(PICK_GROUPS), gigs=GIG_COUNT)


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
    client = dig.anthropic_client()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": llm_input(taste, picks, gigs, week)}],
        output_format=Weekly,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"curation refused: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("curation hit max_tokens")
    print(f"llm usage: {response.usage.input_tokens} in, {response.usage.output_tokens} out")
    return response.parsed_output


REVIEW_SYSTEM = """You find published reviews of vinyl records for diig, a record digging \
app. Search the web for a review of the one record you are given: an editorial write-up \
of that specific release from a magazine, blog, radio show or a shop's own review (for \
example Resident Advisor, Boomkat, Bleep, Pitchfork, The Quietus, Crack, Mixmag, \
XLR8R, Inverted Audio, Ransom Note). Label press releases, tracklists, store listings \
and pages about the artist in general do not count, nor do reviews of a different \
release by the same artist.

If you find one, reply with two or three sentences, about 50 to 70 words, summarising \
what the review says about the record and naming the publication, e.g. "Boomkat hear \
...". Condense a long review to its main points in your own words, quoting at most a \
short phrase or two. Only report what the review says, do not add your own description \
or background. Then a last line "SOURCE: <url>" with the exact url of the review page as \
it appeared in the search results. Reply with nothing but those sentences and the source line.

If no review of this release turns up, reply with exactly NONE."""

REVIEW_SEARCHES = 4
REVIEW_WORKERS = 4


def review_query(c):
    parts = [f"{c.get('artist', '')} - {c.get('title', '')}"]
    if c.get("label"):
        parts.append(f"label: {c['label']}")
    if c.get("cat"):
        parts.append(f"catalogue: {c['cat']}")
    if c.get("track_names"):
        parts.append("tracks: " + ", ".join(c["track_names"][:6]))
    return "\n".join(parts)


# search the web for a review of one pick. the blurb is only kept when its source
# url is one the searches actually returned, so every blurb links to a real page
def find_review(client, c, blocked):
    messages = [{"role": "user", "content": review_query(c)}]
    # the basic search, the dynamic filtering version spends its searches fumbling
    # results in code and comes back with NONE for records that do have reviews
    tools = [{
        "type": "web_search_20250305", "name": "web_search",
        "max_uses": REVIEW_SEARCHES, "blocked_domains": blocked,
    }]
    seen = {}
    for _ in range(3):
        response = client.messages.create(
            model=MODEL, max_tokens=4000, system=REVIEW_SYSTEM, messages=messages, tools=tools,
        )
        # every page the searches returned. an error result has an object, not a list
        for b in response.content:
            if b.type == "web_search_tool_result" and isinstance(b.content, list):
                seen.update({r.url.rstrip("/"): r for r in b.content})
        if response.stop_reason != "pause_turn":
            break
        # long searches pause the turn, send it back to carry on
        messages.append({"role": "assistant", "content": response.content})
    if response.stop_reason != "end_turn":
        print(f"warning: no review for {c['id']}, stopped with {response.stop_reason}")
        return "", None
    # the answer is the text after the last search, earlier text is working notes
    tail = []
    for b in response.content:
        tail = tail + [b.text] if b.type == "text" else []
    text = "".join(tail).strip()
    if text.endswith("NONE"):
        return "", None
    blurb, _, url = text.rpartition("SOURCE:")
    result = seen.get(url.strip().rstrip("/"))
    if not blurb.strip() or not result:
        print(f"warning: dropping review for {c['id']}, source not in search results: {url.strip()[:100]}")
        return "", None
    host = urllib.parse.urlparse(result.url).hostname or ""
    return blurb.strip(), {"url": result.url, "title": result.title, "site": host.removeprefix("www.")}


# domains of the stores diig aggregates, so a review is from somewhere else
def store_domains(regs):
    domains = set()
    for reg in regs.values():
        link = next((r["link"] for r in reg.values() if r.get("link")), None)
        host = urllib.parse.urlparse(link).hostname if link else None
        if host:
            domains.add(host.removeprefix("www."))
    return sorted(domains)


def add_reviews(picks, regs):
    client = dig.anthropic_client()
    blocked = store_domains(regs)

    def review(c):
        try:
            return find_review(client, c, blocked)
        except anthropic.APIError as e:
            print(f"warning: review search failed for {c['id']}: {e}")
            return "", None

    with concurrent.futures.ThreadPoolExecutor(REVIEW_WORKERS) as pool:
        results = list(pool.map(review, picks))
    for c, (blurb, source) in zip(picks, results):
        c["blurb"] = blurb
        if source:
            c["source"] = source
    print(f"found reviews for {sum(1 for b, _ in results if b)} of {len(picks)} picks")


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
            chosen.append(c)
        else:
            print(f"warning: dropping unknown release id from llm: {p.release_id}")
    # hold each group to its half of the candidates in the llm's order, top up a
    # short group from its shortlist, then let over quota picks fill any space left
    quota = PICK_CANDIDATES // len(PICK_GROUPS)
    within, over = [], []
    for c in chosen:
        n = sum(1 for x in within if x["_group"] == c["_group"])
        (within if n < quota else over).append(c)
    for name in PICK_GROUPS:
        short = quota - sum(1 for x in within if x["_group"] == name)
        for c in [c for c in picks_by_id.values() if c["_group"] == name][:max(short, 0)]:
            print(f"warning: topping up {name} picks with {c['id']}")
            within.append(c)
            picks_by_id.pop(c["id"])
    # these are candidates, add_reviews and select_picks cut them down to the page
    out_picks = within + over
    for g in curated.gigs:
        ev = gigs_by_id.pop(g.event_id, None)
        if ev:
            out_gigs.append(dict(strip_private(ev), blurb=g.blurb))
        else:
            print(f"warning: dropping unknown event id from llm: {g.event_id}")
    out_picks, out_gigs = out_picks[:PICK_CANDIDATES], out_gigs[:GIG_COUNT]
    # top up from the shortlists (already in score order) if the llm came back
    # short, so the page always fills whole rows. top up gigs go without a blurb
    for c in list(picks_by_id.values())[:PICK_CANDIDATES - len(out_picks)]:
        print(f"warning: topping up picks with {c['id']}")
        out_picks.append(c)
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


# cut the candidates down to the page, each group taking its half with reviewed
# picks first, in the llm's order. a group short of candidates is filled from the rest
def select_picks(candidates):
    quota = PICK_COUNT // len(PICK_GROUPS)
    chosen = set()
    for name in PICK_GROUPS:
        group = [c for c in candidates if c["_group"] == name]
        ranked = [c for c in group if c.get("blurb")] + [c for c in group if not c.get("blurb")]
        chosen |= {c["id"] for c in ranked[:quota]}
    rest = [c for c in candidates if c["id"] not in chosen]
    rest = [c for c in rest if c.get("blurb")] + [c for c in rest if not c.get("blurb")]
    chosen |= {c["id"] for c in rest[:PICK_COUNT - len(chosen)]}
    return [strip_private(c) for c in candidates if c["id"] in chosen]


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
    add_reviews(page["picks"], regs)
    page["picks"] = select_picks(page["picks"])
    os.makedirs(f"{REG_DIR}/weekly", exist_ok=True)
    open(f"{REG_DIR}/weekly/{week}.json", "w+").write(json.dumps(page, indent=4, ensure_ascii=False))
    print(f"wrote {REG_DIR}/weekly/{week}.json: {len(page['picks'])} picks, {len(page['hype'])} hype, {len(page['gigs'])} gigs")
    if not local_only:
        publish(session, page)
