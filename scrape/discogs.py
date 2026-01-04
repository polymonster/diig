import discogs_client
import json
import time
import yt_dlp
import re
import sys
import dig
import os
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


def release_search(discogs, release):
    searches = [
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
        },
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
    ]
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
                    print(f"{result.title}: https://www.discogs.com{result.url}")
                else:
                    print(f"https://www.discogs.com{result.url}")
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
    reg_file = f"registry/{store}.json"
    reg = json.loads(open(reg_file, "r").read())
    count = 0
    hits = 0
    prev_attemps = 0
    failures = 0
    for entry in reg:
        if "discogs" not in reg[entry] or "-recheck" in sys.argv:
            if not check_release_limit(count):
                print(f"{entry} - {concat_title(reg[entry])}")
                try:
                    result = release_search(discogs, reg[entry])
                    if result != None:
                        reg[entry]["discogs"] = result
                        count = count + 1
                        hits += 1
                    else:
                        reg[entry]["discogs"] = {
                            "attempted": True
                        }
                except:
                    failures += 1
                    print("failed with exception")
                    time.sleep(1)
                    continue
        else:
            if "attempted" in reg[entry]["discogs"]:
                print(f"{entry} {reg[entry]['cat']} - previously attempted and failed to find")
                prev_attemps += 1
            else:
                print(f"{entry} {reg[entry]['cat']} - already exists")
                hits += 1
    print(f"Job complete: {count} new additions, {hits} have info, {prev_attemps} previously attempted, {failures} failures")
    open(reg_file, "w").write(json.dumps(reg, indent=4))
    dig.patch_releases(json.dumps(reg))


def populate_discogs_likes(discogs, likes_file):
    count = 0
    likes = json.loads(open(likes_file, "r").read())
    for file in os.listdir("registry"):
        if file.endswith(".json"):
            reg_file = f"registry/{file}"
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
                                reg[entry]["discogs"] = {
                                    "attempted": True
                                }
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

    # genre_search(discogs, style='Tech House', year=2023)
    # collection_dump(discogs)


if __name__ == "__main__":
    main()