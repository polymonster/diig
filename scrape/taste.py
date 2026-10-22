import dig
import sys
import json
import os
import re
import time
import datetime
import discogs_client

# builds a taste profile (artists, labels, styles) from a discogs collection
# plus a diig user's likes. run manually when the collection has changed;
# homepage.py reads the output to score releases
#   python3 taste.py -discogs-key <token> -user polymonster [-full] [-local-only]

DB = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app"
TASTE_FILE = "diig-registry/taste/taste.json"


# normalise an artist / label name for matching between discogs and store data
# e.g. "Baby Ford (2)" -> "baby ford", "The Black Dog" -> "black dog"
def norm_name(name: str) -> str:
    if not name:
        return ""
    s = name.lower().strip()
    s = re.sub(r"\s*\(\d+\)$", "", s)
    s = re.sub(r"^the\s+", "", s)
    s = re.sub(r"[^\w\s&'-]", "", s)
    return re.sub(r"\s+", " ", s).strip()


# split a store artist string into individual artists
# e.g. "Moodymann & Theo Parrish feat. X" -> ["moodymann", "theo parrish", "x"]
def split_artists(artist: str) -> list:
    if not artist:
        return []
    parts = re.split(r"\s*(?:,|&|/|\+|\bvs\.?|\bx\b|\bfeat\.?|\bft\.?|\band\b|\bpresents\b)\s*", artist, flags=re.IGNORECASE)
    names = [norm_name(p) for p in parts]
    return [n for n in names if n and n not in ("various", "various artists", "va")]


# keys into an artists table for a store artist string. the whole name is tried
# first so duos like "rhythm & sound" match before being split apart
def artist_keys(artist: str, table: dict) -> list:
    full = norm_name(artist)
    if full in table:
        return [full]
    return split_artists(artist)


def empty_taste():
    return {
        "updated": None,
        "user": None,
        "collection_count": 0,
        "artists": {},
        "labels": {},
        "styles": {},
        "seen_instances": [],
    }


def load_taste():
    if os.path.exists(TASTE_FILE):
        return json.loads(open(TASTE_FILE, "r").read())
    return empty_taste()


def write_taste(taste):
    os.makedirs(os.path.dirname(TASTE_FILE), exist_ok=True)
    open(TASTE_FILE, "w+").write(json.dumps(taste, indent=4))


PLACEHOLDER_NAMES = ("various", "various artists", "unknown artist", "va", "not on label", "unknown")


def entry(table, name, discogs_id=None):
    key = norm_name(name)
    if not key or key in PLACEHOLDER_NAMES or key.startswith("not on label"):
        return None
    if key not in table:
        table[key] = {"name": name, "collection": 0, "liked": 0, "unliked": 0}
    e = table[key]
    if discogs_id and "discogs_id" not in e:
        e["discogs_id"] = discogs_id
    return e


# walk the collection 'All' folder using only basic_information, so no extra
# request is made per release. incremental: only unseen instances are counted
def add_collection(taste, discogs):
    me = discogs.identity()
    seen = set(taste["seen_instances"])
    folder = me.collection_folders[0]
    added = 0
    for item in folder.releases:
        iid = item.data.get("instance_id")
        if iid in seen:
            continue
        info = item.data.get("basic_information", {})
        label_names = [l.get("name") for l in info.get("labels", []) if l.get("name")]
        for a in info.get("artists", []):
            e = entry(taste["artists"], re.sub(r"\s*\(\d+\)$", "", a.get("name", "")), a.get("id"))
            if e:
                e["collection"] += 1
                e.setdefault("labels", [])
                for ln in label_names:
                    if ln not in e["labels"]:
                        e["labels"].append(ln)
        for l in info.get("labels", []):
            e = entry(taste["labels"], l.get("name", ""), l.get("id"))
            if e:
                e["collection"] += 1
        for style in info.get("styles", []):
            taste["styles"][style] = taste["styles"].get(style, 0) + 1
        seen.add(iid)
        added += 1
        if added % 100 == 0:
            print(f"collection: {added} new items processed", flush=True)
            # stay under the discogs 60 requests / minute limit between pages
            time.sleep(1)
    taste["seen_instances"] = sorted(seen)
    taste["collection_count"] = len(seen)
    print(f"collection: added {added} new items ({len(seen)} total)")


def find_uid(session, username):
    uids = session.get(f"{DB}/users.json", params={"shallow": "true"}).json() or {}
    for uid in uids:
        if session.get(f"{DB}/users/{uid}/username.json").json() == username:
            return uid
    return None


# likes are /users/{uid}/likes/{release_id} = timestamp, or 0 once unliked.
# unliked usually means the record was bought, so it is counted separately as
# a strong signal. likes are recounted from scratch on every run
def add_likes(taste, session, username):
    uid = find_uid(session, username)
    if not uid:
        print(f"error: diig user '{username}' not found")
        return
    likes = session.get(f"{DB}/users/{uid}/likes.json").json() or {}
    reg = dig.load_combined_registries("diig-registry")
    for table in (taste["artists"], taste["labels"]):
        for e in table.values():
            e["liked"] = 0
            e["unliked"] = 0
    missing = 0
    for rid, ts in likes.items():
        release = reg.get(rid)
        if not release:
            missing += 1
            continue
        field = "liked" if ts else "unliked"
        for name in artist_keys(release.get("artist", ""), taste["artists"]):
            e = entry(taste["artists"], name)
            if e:
                e[field] += 1
        e = entry(taste["labels"], release.get("label", ""))
        if e:
            e[field] += 1
    taste["user"] = username
    print(f"likes: {len(likes)} likes ({sum(1 for t in likes.values() if not t)} unliked), {missing} not in registry")


if __name__ == "__main__":
    taste = empty_taste() if "-full" in sys.argv else load_taste()

    if "-discogs-key" in sys.argv:
        token = sys.argv[sys.argv.index("-discogs-key") + 1]
    else:
        token = json.loads(open("discogs-auth.json", "r").read())["token"]
    add_collection(taste, discogs_client.Client("diig/1.0", user_token=token))

    if "-user" in sys.argv and "-local-only" not in sys.argv:
        dig.setup_firebase_auth()
        add_likes(taste, dig.auth_session(), sys.argv[sys.argv.index("-user") + 1])

    taste["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write_taste(taste)
    top = sorted(taste["artists"].values(), key=lambda e: -(e["collection"] * 3 + e["unliked"] * 3 + e["liked"]))[:15]
    print("top artists:", ", ".join(e["name"] for e in top))
