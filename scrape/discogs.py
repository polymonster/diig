import discogs_client
import json
import time
import yt_dlp
import re
import sys
import dig
import os
import unicodedata
from rapidfuzz import fuzz

def hyperlink(text, url):
    ESC = "\033"
    return f"{ESC}]8;;{url}{ESC}\\{text}{ESC}]8;;{ESC}\\"


def get_audio_url(video_url):
    ydl_opts = {
        'format': 'bestaudio[abr<=128]',
        'quiet': True,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return info['url']
    except Exception as e:
        print(f"Error extracting audio URL: {e}")
        return None


def list_videos(release):
    if not hasattr(release, "videos"):
        return []
    unique_videos = list()
    unique_video_keys = set()
    for video in release.videos:
        if video.url not in unique_video_keys:
            unique_videos.append({
                "url": video.url,
                "title": video.title
            })
            unique_video_keys.add(video.url)
    return unique_videos


def print_audio_links(videos):
    for video in videos:
        audio_url = get_audio_url(video['url'])
        if audio_url:
            link = hyperlink(video['title'], audio_url)
            print(f"    {link}")


def print_image_links(release):
    links = ""
    for img in release.images:
        links += hyperlink(img['type'], img['uri']) + " "
    print(f"    images [ {links}]")


def genre_search(discogs, style, year):
    results = discogs.search(
        style=style,
        type='release',
        year=year,
        sort='year',
        sort_order='desc'
    )
    for release in results.page(1):
        print(f"{release.title} ({release.year})")
        print_image_links(release)
        print_audio_links(list_videos(release))


def strip_suffix(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)$", "", name).strip()


def discogs_title(release):
    if(release['artist'].lower().find("various") != -1):
        return "various"
    else:
        return release['artist']


def caseless_cmp(a, b):
    return a.lower() == b.lower()


def caseless_spaceless_cmp(a, b):
    a = a.replace(' ', '')
    b = b.replace(' ', '')
    return a.lower() == b.lower()


def concat_title(release):
    return f"{release['artist']} - {release['title']}"


def concat_title_2(release):
    return f"{discogs_title(release)} - {release['title']}"


def concat_title_3(release):
    return f"{release['artist']} - {strip_format_suffix(release['title'])}"


def tracklist_match_unordered(db, discogs, threshold=60):
    used = set()
    for a in db:
        best = max(
            ((i, fuzz.ratio(a, b)) for i, b in enumerate(discogs) if i not in used),
            key=lambda x: x[1],
            default=(None, 0)
        )
        if best[1] < threshold:
            return False
        used.add(best[0])
    return True


def search_title(title):
    # Remove trailing format tags like "3xLP", "2x12", "CD", etc.
    title = re.sub(
        r'\s*\b\d+\s*(x)?\s*(LP|12|7|CD|CASS|CASSETTE|EP)\b\s*$',
        '',
        title,
        flags=re.IGNORECASE
    )

    # Remove ANY number of trailing (...) groups
    title = re.sub(
        r'(?:\s*\([^)]*\)\s*)+$',
        '',
        title
    )

    return title.strip()


def throttled_search(func, **kwargs):
    time.sleep(1)
    return func(**kwargs)


def check_search_limit(count):
    if "-searches" in sys.argv:
        i = sys.argv.index("-searches") + 1
        if count < int(sys.argv[i]):
            return False
        else:
            return True
    return False


def check_release_limit(count):
    if "-releases" in sys.argv:
        i = sys.argv.index("-releases") + 1
        if count < int(sys.argv[i]):
            return False
        else:
            return True
    return False


def get_time_limit():
    if "-time" in sys.argv:
        i = sys.argv.index("-time") + 1
        return float(sys.argv[i]) * 60 * 60
    return 5.5 * 60 * 60


ZERO_WIDTH = [
    "\u200B",  # zero width space
    "\u200C",  # zero width non-joiner
    "\u200D",  # zero width joiner
    "\uFEFF",  # zero width no-break space
]

def normalize_unicode(s: str) -> str:
    if not s:
        return ""

    # Normalize to NFC (canonical composed form)
    s = unicodedata.normalize("NFC", s)

    # Remove zero-width characters
    for zw in ZERO_WIDTH:
        s = s.replace(zw, "")

    # Normalize whitespace
    s = re.sub(r"\s+", " ", s).strip()

    # Lowercase for comparison
    return s.lower()


FORMAT_KEYWORDS = [
    r"\b\d+x\b",          # 2x, 3x, etc.
    r"\b\d+\s*lp\b",      # 2 LP, 3LP
    r"\b\d+\s*cd\b",
    r"\b\d+\s*12",        # 12", 12”
    r"\b\d+\s*inch\b",
    r"\b\d+\s*g\b",       # 180g, 140g
    r"vinyl",
    r"gatefold",
    r"promo",
    r"test pressing",
    r"limited",
    r"ltd",
    r"reissue",
    r"remaster",
]

FORMAT_REGEX = re.compile("|".join(FORMAT_KEYWORDS), re.IGNORECASE)

def remove_parens_and_brackets(s: str) -> str:
    s = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def strip_format_suffix(title: str) -> str:
    if not title:
        return ""

    parts = [p.strip() for p in title.split(" - ")]

    # If only one or two parts, nothing to strip
    if len(parts) <= 2:
        title = title.strip()
        title = title.strip("-")
        title = title.strip("EP")
        title = title.strip("LP")
        return remove_parens_and_brackets(search_title(title.strip()))

    # Check last part for format keywords
    last = parts[-1]
    if FORMAT_REGEX.search(last):
        return " - ".join(parts[:-1]).strip()

    title = title.strip()
    title = title.strip("-")
    title = title.strip("EP")
    title = title.strip("LP")
    return remove_parens_and_brackets(search_title(title.strip()))


def normalize_discogs_title(title: str) -> str:
    if not title:
        return ""

    # Remove Discogs disambiguation numbers: (11), (2), (123), etc.
    # Only when they appear right after a name, not in the middle of a title.
    title = re.sub(r'\s*\(\d+\)', '', title)

    # Normalize whitespace
    title = re.sub(r'\s+', ' ', title).strip()

    return normalize_unicode(title.lower())


def normalize_local_title(title: str) -> str:
    if not title:
        return ""

    # Remove label suffix after '|'
    if '|' in title:
        title = title.split('|')[0]

    # Normalize whitespace
    title = re.sub(r'\s+', ' ', title).strip()

    return normalize_unicode(title.lower())


def titles_match(local_title: str, discogs_title: str) -> bool:
    return normalize_local_title(local_title) == normalize_discogs_title(discogs_title)


def is_vinyl_release(formats):
    """Check if discogs format data indicates a vinyl release."""
    if not formats:
        return None
    for fmt in formats:
        if isinstance(fmt, dict):
            name = fmt.get('name', '').lower().strip()
        else:
            name = str(fmt).lower().strip()
        if name == 'vinyl':
            return True
    return False


def release_search_3(discogs, release):
    """
    Third-pass search: single API call, heavy client-side fuzzy matching.
    Searches by label name and scores results locally.
    """
    label = release.get('label', '').strip()
    title = strip_format_suffix(release.get('title', ''))
    artist = release.get('artist', '').strip()
    cat = release.get('cat', '').strip()

    # Build search query - prioritize label for electronic/vinyl releases
    if label:
        query = label
    elif artist and artist.lower() not in ('various', 'va'):
        query = artist
    else:
        return None

    try:
        results = throttled_search(discogs.search, q=query, type='release')
    except:
        return None

    # Prepare normalized local values for comparison
    local_artist = normalize_local_title(artist)
    local_title = normalize_local_title(title)
    local_full = normalize_local_title(f"{artist} - {title}")
    local_label = normalize_local_title(label)
    local_cat = re.sub(r'[\s\-\.]', '', cat.lower()) if cat else ''

    best_match = None
    best_score = 0

    # Process first page only (no pagination API calls)
    for i, result in enumerate(results):
        if i >= 50:
            break

        score = 0
        result_data = result.data or {}

        # Title matching (max 100 points)
        if hasattr(result, 'title') and result.title:
            result_title_norm = normalize_discogs_title(result.title)
            # Try matching against full "artist - title" and title-only
            title_score = max(
                fuzz.ratio(local_full, result_title_norm),
                fuzz.ratio(local_title, result_title_norm),
                fuzz.token_set_ratio(local_full, result_title_norm)
            )
            score += title_score

        # Catno matching (bonus 80 points for exact, 40 for partial)
        result_cat = result_data.get('catno', '')
        if result_cat and local_cat:
            result_cat_norm = re.sub(r'[\s\-\.]', '', result_cat.lower())
            if local_cat == result_cat_norm:
                score += 80
            elif fuzz.ratio(local_cat, result_cat_norm) > 85:
                score += 40

        # Label matching from result.data (bonus up to 50 points)
        result_labels = result_data.get('label', [])
        if result_labels and local_label:
            if isinstance(result_labels, list):
                for rl in result_labels:
                    label_score = fuzz.ratio(local_label, normalize_discogs_title(rl))
                    if label_score > 75:
                        score += min(50, label_score // 2)
                        break

        # Artist matching from result.data (bonus up to 30 points)
        # Format field sometimes contains artist info
        result_format = result_data.get('format', [])
        result_title_raw = result.title if hasattr(result, 'title') else ''
        if local_artist and result_title_raw:
            # Discogs titles are often "Artist - Title"
            if ' - ' in result_title_raw:
                result_artist = normalize_discogs_title(result_title_raw.split(' - ')[0])
                artist_score = fuzz.ratio(local_artist, result_artist)
                if artist_score > 80:
                    score += min(30, artist_score // 3)

        if score > best_score:
            best_score = score
            best_match = result

    # Threshold: need decent title match (70+) plus some other signal
    if best_match and best_score >= 140:
        print(f"{release['link']} -> {best_match.url} (score: {best_score})")
        return {
            "url": f"{best_match.url}",
            "id": best_match.id
        }

    if "-verbose" in sys.argv:
        print(f"No match (algo 3): {concat_title(release)} ({cat}) best: {best_score}")
    return None


def release_search_2(discogs, release):
    title = strip_format_suffix(concat_title_3(release))
    searches = list()
    # searches based on catno, if we have one
    if len(release['cat']) > 0:
        searches.extend([
            {
                "search": throttled_search(discogs.search,
                    q=title,
                    type='release'
                ),
                "search_keys": ['catno'],
            }
        ])
    for search in searches:
        for result in search["search"]:
            if titles_match(title, result.title):
                print(f"{release['link']} -> {result.url}")
                return {
                    "url": f"{result.url}",
                    "id": result.id
                }
    

def release_search(discogs, release):
    searches = list()
    # searches based on catno, if we have one
    if len(release['cat']) > 0:
        searches.extend([
            {
                "search": throttled_search(discogs.search,
                    catno=release['cat'],
                    type='release'
                ),
                "search_keys": ['catno'],
            },
            {
                "search": throttled_search(discogs.search,
                    q=search_title(release['cat'])
                ),
                "search_keys": [],
            }
        ])
    # searches based on title
    searches.extend([
        {
            "search": throttled_search(discogs.search,
                q=search_title(release['title'])
            ),
            "search_keys": [],
        },
        {
            "search": throttled_search(discogs.search,
                artist=release['artist'],
                title=search_title(release['title']),
                type='release'
            ),
            "search_keys": ['artist', 'title'],
        },
        {
            "search": throttled_search(discogs.search,
                title= search_title(release['title']),
                type='release'
            ),
            "search_keys": ['title'],
        }
    ])
    if "-verbose" in sys.argv:
        counts = []
        for search in searches:
            counts.append(len(search['search']))
        print(counts)
    count = 0
    score = 0
    searches = sorted(searches, key=lambda x: len(x["search"]))
    for search in searches:
        for result in search["search"]:
            # handle missing release or forward a rate limit exception
            try:
                hasattr(result, "labels")
                time.sleep(1)
            except discogs_client.exceptions.HTTPError as e:
                if e.status_code == 404:
                    continue
                else:
                    raise
            count += 1
            if check_search_limit(count):
                print(f"No results found for (after {count} attempts): {concat_title(release)} ({release['cat']})")
                return None
            if "-verbose" in sys.argv:
                if hasattr(result, "title"):
                    print(f"{result.title}: {result.url}")
                else:
                    print(f"{result.url}")
            # match title, this gives us the best / most reliable
            if hasattr(result, "title"):
                if caseless_cmp(release['title'], result.title):
                    score += 1
                    break
                if caseless_cmp(concat_title(release), result.title):
                    score += 1
                    break
                if caseless_cmp(concat_title_2(release), result.title):
                    score += 1
                    break
            # match by catno if the search was not artist / title
            if "catno" not in search["search_keys"]:
                if result.data.get("catno"):
                    if caseless_spaceless_cmp(result.data.get("catno"), release['cat']):
                        score += 1
                        break
            # now match based on label
            if hasattr(result, "labels"):
                for label in result.labels:
                    if caseless_cmp(release['label'], strip_suffix(label.name)):
                        score += 1
            if score > 0:
                break
            # or artists
            if hasattr(result, "artists"):
                for artist in result.artists:
                    if caseless_cmp(release['artist'], strip_suffix(artist.name)):
                        score += 1
            if score > 0:
                break
            # extract track names from discogs
            tracklist = result.data.get("tracklist")
            if tracklist:
                tracks = []
                for track in tracklist:
                    tracks.append(track["title"])
                if len(tracks) == len(release["track_names"]):
                    if tracklist_match_unordered(release["track_names"], tracks):
                        score += 1
            if score > 0:
                break
            time.sleep(1)
        if score > 0:
            break
        time.sleep(1)
    if score > 0:
        print(f"{release['link']} -> {result.url}")
        return {
            "url": f"{result.url}",
            "id": result.id
        }
    print(f"No results found for: {concat_title(release)} ({release['cat']})")
    for search in searches:
        for result in search["search"]:
            if hasattr(result, "title"):
                print(f"    {result.title} ({result.data.get('catno')})")
    if "-assert" in sys.argv:
        assert(0)
    time.sleep(1)


def collection_dump(discogs):
    user = discogs.identity()
    folders = user.collection_folders
    for folder in folders:
        for item in folder.releases:
            release = item.release
            print(f"{release.title}")
            print_image_links(release)
            print_audio_links(list_videos(release))
            time.sleep(1)


def populate_discogs_links(discogs, store):
    reg = dig.load_registry(store)

    count = 0
    hits = 0
    prev_attemps = 0
    failures = 0
    preorders = 0

    # time limit of 5.5hs so we can push any improvements before GH actions kills us
    deadline = time.monotonic() + get_time_limit()

    # iterate over all entries
    if "-skip0" not in sys.argv:
        for entry in reg:
            if time.monotonic() >= deadline:
                print("terminating early to beat deadline")
                break        
            if "discogs" not in reg[entry] or "-recheck" in sys.argv:
                print(f"{entry} - {concat_title(reg[entry])}")
                try:
                    result = release_search(discogs, reg[entry])
                    if result != None:
                        reg[entry]["discogs"] = result
                        count = count + 1
                        hits += 1
                    else:
                        attempted_info = {"attempted": True}
                        if reg[entry].get("store_tags", {}).get("preorder"):
                            attempted_info["preorder"] = True
                        reg[entry]["discogs"] = attempted_info
                except:
                    failures += 1
                    print("failed with exception")
                    time.sleep(1)
                    continue
            else:
                if "attempted" in reg[entry]["discogs"]:
                    if "-verbose" in sys.argv:
                        print(f"{entry} {reg[entry]['cat']} - previously attempted and failed to find")
                    prev_attemps += 1
                else:
                    if "-verbose" in sys.argv:
                        print(f"{entry} {reg[entry]['cat']} - already exists")
                    hits += 1

    # fall through and try anything that was previously attempted
    for entry in reg:
        if time.monotonic() >= deadline:
            print("terminating early to beat deadline")
            break
        if "discogs" in reg[entry] and "attempted" in reg[entry]["discogs"]:
            if reg[entry]["discogs"].get("preorder"):
                preorders += 1
            print(f"{entry} - {concat_title(reg[entry])}")
            try:
                attempted_val = reg[entry]["discogs"].get("attempted")
                if isinstance(attempted_val, bool):
                    # First fallthrough: try algorithm 2
                    result = release_search_2(discogs, reg[entry])
                    next_attempt_index = 0
                elif attempted_val == 0:
                    # Second fallthrough: try algorithm 3 (label-based fuzzy)
                    result = release_search_3(discogs, reg[entry])
                    next_attempt_index = 1
                else:
                    # Already exhausted all algorithms
                    if "-verbose" in sys.argv:
                        print(f"{entry} {reg[entry]['cat']} - exhausted all {attempted_val + 1} algorithms")
                    continue
                if result != None:
                    reg[entry]["discogs"] = result
                    count = count + 1
                    hits += 1
                else:
                    attempted_info = {"attempted": next_attempt_index}
                    if reg[entry].get("store_tags", {}).get("preorder"):
                        attempted_info["preorder"] = True
                    reg[entry]["discogs"] = attempted_info
            except:
                failures += 1
                print("failed with exception")
                time.sleep(1)
                continue


    # Third pass: verify format of existing discogs links
    if "-check-formats" in sys.argv:
        format_verified = 0
        format_switched = 0
        for entry in reg:
            if time.monotonic() >= deadline:
                print("terminating early to beat deadline")
                break
            if "discogs" not in reg[entry]:
                continue
            disc = reg[entry]["discogs"]
            if "attempted" in disc:
                continue
            if disc.get("format_checked"):
                continue
            release_id = disc.get("id")
            if not release_id:
                continue
            try:
                time.sleep(1)
                discogs_release = discogs.release(release_id)
                formats = discogs_release.data.get('formats')
                vinyl = is_vinyl_release(formats)
                if vinyl or vinyl is None:
                    print(f"verified vinyl {release_id}")
                    disc["format_checked"] = True
                    format_verified += 1
                else:
                    print(f"not vinyl {release_id}")
                    # not vinyl, try to get master release
                    master_id = discogs_release.data.get('master_id')
                    if master_id:
                        time.sleep(1)
                        master = discogs.master(master_id)
                        print(f"Switched to master: {entry} {disc['url']} -> {master.url}")
                        disc["url"] = f"{master.url}"
                        disc["id"] = master.id
                        disc["format_checked"] = True
                        format_switched += 1
                    else:
                        disc["format_checked"] = True
                        format_verified += 1
            except Exception as e:
                print(f"Error checking format for {entry}: {e}")
                time.sleep(1)
            continue

    print(f"Job complete: {count} new additions, {hits} have info / {len(reg)}, {prev_attemps} previously attempted ({preorders} preorders), {failures} failures, format check: {format_verified} verified vinyl, {format_switched} switched to master")
    
    # write to file
    dig.write_registry(store, reg)
    dig.patch_releases(json.dumps(reg))


def populate_discogs_likes(discogs, likes_file):
    count = 0
    likes = json.loads(open(likes_file, "r").read())
    for file in os.listdir("diig-registry"):
        if file.endswith(".json"):
            reg_file = f"diig-registry/{file}"
            reg = json.loads(open(reg_file, "r").read())
            for entry in likes:
                if entry in reg:
                    if "discogs" not in reg[entry] or "-recheck" in sys.argv:
                        print(f"{entry} - {concat_title(reg[entry])}")
                        try:
                            result = release_search(discogs, reg[entry])
                            if result != None:
                                reg[entry]["discogs"] = result
                                count = count + 1
                                if check_release_limit(count):
                                    break
                            else:
                                attempted_info = {"attempted": True}
                                if reg[entry].get("store_tags", {}).get("preorder"):
                                    attempted_info["preorder"] = True
                                reg[entry]["discogs"] = attempted_info
                        except:
                            time.sleep(1)
                            continue
                else:
                    if "attempted" in reg[entry]["discogs"]:
                        print(f"{entry} {reg[entry]['cat']} - previously attempted and failed to find")
                    else:
                        print(f"{entry} {reg[entry]['cat']} - already exists")
            open(reg_file, "w").write(json.dumps(reg, indent=4))
            dig.patch_releases(json.dumps(reg))


def main():
    if "-discogs-key" in sys.argv:
        token = sys.argv[sys.argv.index("-discogs-key") + 1]
    else:
        token = json.loads(open("discogs-auth.json", "r").read())["token"]

    print("logging in to discogs")
    discogs = discogs_client.Client('MyDiscogsApp/1.0', user_token=token)
    dig.setup_firebase_auth()

    user = discogs.identity()
    print("logged in as:", user)

    if "-store" in sys.argv:
        store = sys.argv[sys.argv.index("-store") + 1]
        populate_discogs_links(discogs, store)
    elif "-likes" in sys.argv:
        populate_discogs_likes(discogs, sys.argv[sys.argv.index("-likes") + 1])


if __name__ == "__main__":
    main()