import discogs_client
import json
import time
import yt_dlp
import sys
import dig
import rip
import os
import datetime
import discogs_match

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


# skip registry entries that are missing core fields (e.g. legacy partial
# entries) instead of crashing the whole job on a KeyError
def skip_invalid_entry(key, release):
    issues = dig.validate_release(key, release)
    if issues:
        print(f"skipping invalid registry entry {key}: {'; '.join(issues)}")
        return True
    return False


def get_time_limit():
    if "-time" in sys.argv:
        i = sys.argv.index("-time") + 1
        return float(sys.argv[i]) * 60 * 60
    return 5.5 * 60 * 60


# when a release discogs had nothing for gets searched again. the wait doubles
# after each try: a preorder starts at a week, its page tends to appear around
# release, but plenty never get one (and some stores leave stale preorder tags
# up for good), so it backs off to the same ceiling as everything else
RETRY_DAYS = 60
PREORDER_RETRY_DAYS = 7
MAX_RETRY_DAYS = 180


def retry_wait(disc, release):
    tries = max(1, disc.get("tries", 1))
    base = PREORDER_RETRY_DAYS if discogs_match.is_preorder(release) else RETRY_DAYS
    return min(base * 2 ** (tries - 1), MAX_RETRY_DAYS)


def retry_due(disc, release):
    # attempted under older rules: one go with the current ones
    if disc.get("matcher", 0) < discogs_match.MATCHER_VERSION:
        return True
    checked = disc.get("checked")
    if not checked:
        return True
    # out now, when it was a preorder at the last look: once, since
    # has_been_released keeps it reading as out from then on
    if disc.get("preorder") and not discogs_match.is_preorder(release):
        return True
    age = (datetime.date.today() - datetime.date.fromisoformat(checked)).days
    return age >= retry_wait(disc, release)


def describe(release):
    return f"{release.get('artist', '')} - {release.get('title', '')} [{release.get('cat', '')}]"


def populate_discogs_links(api, store):
    reg = dig.load_registry(store)
    counts = {"linked": 0, "candidates": 0, "none": 0, "have": 0, "waiting": 0, "failures": 0}

    # time limit of 5.5hs so we can push any improvements before GH actions kills us
    deadline = time.monotonic() + get_time_limit()
    verbose = "-verbose" in sys.argv

    # newest first, so new arrivals are done before any deadline
    for key in reversed(list(reg)):
        if time.monotonic() >= deadline:
            print("terminating early to beat deadline")
            break
        release = reg[key]
        if skip_invalid_entry(key, release):
            continue
        disc = release.get("discogs")
        if discogs_match.is_linked(disc):
            # -recheck re-matches links, except ones the llm has confirmed
            if "-recheck" not in sys.argv or disc.get("llm_validated"):
                counts["have"] += 1
                continue
        elif isinstance(disc, dict) and not retry_due(disc, release):
            counts["waiting"] += 1
            continue

        print(f"{key} - {describe(release)}")
        try:
            rejected = disc.get("rejected", []) if isinstance(disc, dict) else []
            verdict, signals, cand = discogs_match.match_release(api, release, verbose=verbose, exclude=rejected)
        except Exception as e:
            counts["failures"] += 1
            print(f"    failed: {e}")
            continue
        release["discogs"] = discogs_match.discogs_entry(release, verdict, signals, cand, disc)
        if verdict in ("strong", "ok"):
            counts["linked"] += 1
            print(f"    {verdict} {'+'.join(signals)} -> {cand['url']}")
        elif verdict == "weak":
            counts["candidates"] += 1
            print(f"    candidate {'+'.join(signals)} {cand['url']}")
        else:
            counts["none"] += 1

    # re-check links made by the old algorithms against the current rules
    if "-rescore" in sys.argv:
        rescore_links(api, reg, deadline, counts)

    # verify format of existing discogs links, switching non vinyl to the master
    format_verified = 0
    format_switched = 0
    if "-check-formats" in sys.argv:
        for key in reg:
            if time.monotonic() >= deadline:
                print("terminating early to beat deadline")
                break
            disc = reg[key].get("discogs")
            if not discogs_match.is_linked(disc) or disc.get("format_checked") or "/master/" in disc.get("url", ""):
                continue
            # the crawl only searches vinyl. links it made before it set
            # format_checked itself
            if disc.get("via") == "crawl":
                continue
            try:
                rec = api.get(f"/releases/{disc['id']}")
                if rec is None:
                    continue
                vinyl = is_vinyl_release(rec.get("formats"))
                if vinyl is False and rec.get("master_id"):
                    master = api.get(f"/masters/{rec['master_id']}")
                    if master:
                        print(f"switched to master: {key} {disc['url']} -> {master['uri']}")
                        disc["url"] = master["uri"]
                        disc["id"] = master["id"]
                        format_switched += 1
                else:
                    format_verified += 1
                disc["format_checked"] = True
            except Exception as e:
                print(f"error checking format for {key}: {e}")

    print(f"job complete: {counts['linked']} linked, {counts['candidates']} candidates for review, "
          f"{counts['none']} not found, {counts['have']} already linked / {len(reg)}, "
          f"{counts['waiting']} waiting to retry, {counts['failures']} failures, "
          f"format check: {format_verified} vinyl, {format_switched} switched to master, "
          f"{api.requests} discogs requests")

    dig.write_registry(store, reg)
    dig.patch_releases(reg)


# links from before the rule matcher carry no "matcher" field. each costs one
# fetch of the linked record, scored with the current rules:
#   strong / ok  kept, with the evidence recorded
#   weak         one field agreeing is how most false positives got in, so it
#                is taken down to a candidate for discogs_validate.py
#   no           searched again from scratch, the old link remembered as rejected
# links confirmed by the llm are left alone
def rescore_links(api, reg, deadline, counts):
    tally = {"kept": 0, "demoted": 0, "replaced": 0, "cleared": 0}
    for key in reversed(list(reg)):
        if time.monotonic() >= deadline:
            print("terminating early to beat deadline")
            break
        release = reg[key]
        disc = release.get("discogs")
        if not discogs_match.is_linked(disc) or "matcher" in disc or disc.get("llm_validated"):
            continue
        if skip_invalid_entry(key, release):
            continue
        try:
            rec = api.record(disc["url"])
            if rec:
                verdict, signals = discogs_match.score(release, discogs_match.candidate_from_record(rec))
            else:
                verdict, signals = "no", ["gone"]
            if verdict == "ok" and discogs_match.is_preorder(release):
                verdict, signals = "weak", signals + ["preorder"]

            if verdict in ("strong", "ok"):
                disc.update(match=verdict, signals=signals, matcher=discogs_match.MATCHER_VERSION)
                tally["kept"] += 1
                continue

            old = disc["url"]
            if verdict == "weak":
                release["discogs"] = discogs_match.discogs_entry(release, "weak", signals,
                                                   {"url": old, "id": disc["id"]}, disc)
                tally["demoted"] += 1
                print(f"{key} - {describe(release)}\n    demoted {'+'.join(signals)} {old}")
                continue

            rejected = disc.get("rejected", []) + [old]
            v, s, cand = discogs_match.match_release(api, release, exclude=rejected)
            release["discogs"] = discogs_match.discogs_entry(release, v, s, cand, {"rejected": rejected})
            tally["replaced" if v in ("strong", "ok") else "cleared"] += 1
            print(f"{key} - {describe(release)}\n    rejected {'+'.join(signals)} {old}")
            if v in ("strong", "ok"):
                print(f"    {v} {'+'.join(s)} -> {cand['url']}")
        except Exception as e:
            counts["failures"] += 1
            print(f"{key} rescore failed: {e}")
    print(f"rescore: {tally['kept']} kept, {tally['demoted']} demoted to candidates, "
          f"{tally['replaced']} replaced, {tally['cleared']} cleared")


def is_vinyl_release(formats):
    """Check if discogs format data indicates a vinyl release."""
    if not formats:
        return None
    return any(str(f.get("name", "") if isinstance(f, dict) else f).lower().strip() == "vinyl" for f in formats)


def populate_discogs_likes(api, likes_file):
    likes = json.loads(open(likes_file, "r").read())
    for store in dig.stores_list("diig-registry"):
        reg = dig.load_registry(store)
        for key in likes:
            if key not in reg or skip_invalid_entry(key, reg[key]):
                continue
            release = reg[key]
            if discogs_match.is_linked(release.get("discogs")) and "-recheck" not in sys.argv:
                continue
            print(f"{key} - {describe(release)}")
            try:
                verdict, signals, cand = discogs_match.match_release(api, release)
            except Exception as e:
                print(f"    failed: {e}")
                continue
            release["discogs"] = discogs_match.discogs_entry(release, verdict, signals, cand, release.get("discogs"))
        dig.write_registry(store, reg)
        dig.patch_releases(reg)


def display_help():
    print("discogs.py")
    print("")
    print("  -store <name>       populate discogs links for a store registry")
    print("  -likes <file>       populate discogs links for a likes file")
    print("  -rip                build a local library for your collection")
    print("")
    print("-store options (matching rules in discogs_match.py)")
    print("  links new releases, newest first, on corroborated evidence only.")
    print("  a single agreeing field is saved as a candidate for")
    print("  discogs_validate.py instead of being linked")
    print("  -rescore            re-check links from the old algorithms, one fetch")
    print("                      each: kept, demoted to a candidate, or searched")
    print("                      for again")
    print("  -recheck            re-match every link, except llm confirmed ones")
    print("  -check-formats      switch non vinyl links to their master")
    print("  -time <hours>       stop after this long, default 5.5")
    print("  -verbose            print how every search hit scored")
    print("")
    print("-rip options")
    print("  -dir <path>         output directory (required)")
    print("  -input <path>       import rips you already have instead of")
    print("                      fetching: every folder named after a release")
    print("                      catalogue number is matched to your")
    print("                      collection, converted and tagged to match")
    print("  -source <a>         soulseek, youtube or both (default both)")
    print("                      soulseek first, release links for what is")
    print("                      left. naming one source leaves the other")
    print("                      alone entirely, and the ledger remembers")
    print("                      which sources a release has been through, so")
    print("                      each can be a session of its own")
    print("  -count <n>          stop after n releases, for small batches")
    print("  -folder <id|name>   collection folder, defaults to 'All'")
    print("  -oldest             oldest added first, default is newest first")
    print("  -release <id>       rip a single release by discogs id")
    print("  -retry              re-attempt partial, failed and no match releases")
    print("  -force              re-rip everything, ignoring the ledger")
    print("  -dry-run            print the file to track matches, fetch nothing")
    print("  -todo               list the releases still needing tracks,")
    print("                      newest in the collection first, with the")
    print("                      missing tracks under each. -count <n> keeps")
    print("                      it to a short session, -key-only shows only")
    print("                      releases missing a main track")
    print("  -status             print what the library holds and what is")
    print("                      missing, straight off the ledger. add -list")
    print("                      to list the tracks no source could get, the")
    print("                      ones only your own copy will fix")
    print("  -audit              re-check ripped track lengths against discogs,")
    print("                      and list every short file whether discogs has")
    print("                      a timing for it or not, since a snippet runs")
    print("                      about 1:30 whatever it is a snippet of")
    print("  -short-max <s>      what counts as short for -audit, default 165")
    print("  -filecheck          sync the ledger with files changed by hand.")
    print("                      a deleted file is taken as a wrong rip:")
    print("                      rejected, and its track left to find again.")
    print("                      a file dropped into a release folder is")
    print("                      matched to its track, renamed and tagged.")
    print("                      -dry-run lists the changes without acting")
    print("  -rename             rename loose files under -dir from their own")
    print("                      tags to 'Artist - Title', no track numbers.")
    print("                      offline, never on a rip library, and logged")
    print("                      to .diig-rename-log.json. try -dry-run first")
    print("  -curate <dir>       copy a selection of the library to <dir>,")
    print("                      sized for a stick, see -curate options below")
    print("  -tag                the other way round: tag loose files under")
    print("                      -dir with the artist and title from an")
    print("                      'Artist - Title' filename. fills blank tags,")
    print("                      -force overwrites ones that differ")
    print("")
    print("  a bad rip is flagged by hand in the ledger, .diig-rip-ledger.json")
    print("  in the output directory. add a \"flag\" note with the reason, on")
    print("  one track or on the whole release if the record is wrong:")
    print("      \"A1\": { ..., \"flag\": \"snippet, not the full track\" }")
    print("      { \"id\": 123, ..., \"flag\": \"wrong record entirely\" }")
    print("  the next run moves those files to .diig-rejected, remembers never")
    print("  to take the same copy again, and goes looking afresh.")
    print("  -delete-flagged     delete flagged files instead of moving them")
    print("  -debug              print the length comparison for every track")
    print("  -no-length-check    keep files that run far shorter than the track")
    print("  -quality <kbps>     mp3 bitrate, defaults to 320")
    print("  -cookies-from-browser <name>  sign requests in as you")
    print("  -cookies <file>     netscape cookies.txt to use instead")
    print("  -player-client <a,b>  client to present as, if requests get refused")
    print("  -no-cover           skip embedding release artwork")
    print("  -sleep <seconds>    base pause between downloads, jittered")
    print("  -slow               crawl harder, for when requests get refused")
    print("  -attempts <n>       tries per track before giving up, default 4")
    print("  -backoff <seconds>  first wait after a block, doubles each try")
    print("  -block-limit <n>    stop the session after n blocks in a row")
    print("")
    print("-rip -curate options")
    print("  copies the best of the library that fits the size limit into")
    print("  <dir>: preferred genres first, then neutral, then avoided, newest")
    print("  added first in each. a re-run updates <dir> and removes releases")
    print("  that no longer make the cut. discogs genres are recorded in the")
    print("  ledger first, for releases ripped before they were kept")
    print("      python discogs.py -rip -dir <library> -curate <dir> -gb 30")
    print("  -gb <n>             size limit, required. 30 suits a 32gb stick")
    print("  -prefer <a,b>       genres or styles to put first, default")
    print("                      Electronic")
    print("  -avoid <a,b>        genres or styles to put last, default metal,")
    print("                      hardcore, grind, sludge, doom, crust, thrash")
    print("                      and the like. preferred wins over avoided")
    print("  -dry-run            print the selection, copy nothing")
    print("")
    print("-rip soulseek options (needs slskd running, see scrape/slsk.py)")
    print("  -slsk-test          check the slskd connection and exit")
    print("  -slsk-host <url>    slskd address, default http://localhost:5030")
    print("  -slsk-key <key>     slskd api key, else scrape/slskd-auth.json")
    print("  -slsk-downloads <p> where slskd writes finished transfers")
    print("  -slsk-wait <s>      how long to wait on upload queues, default 300")
    print("  -slsk-min-bitrate <n>  ignore mp3s below n kbps")
    print("  -slsk-search-timeout <ms>  how long peers have to answer")
    print("")
    print("  -api-sleep <s>      pause before each discogs api call, default 1.2")
    print("  -discogs-attempts <n>  tries for a rate limited discogs request")
    print("  -discogs-backoff <s>   first wait after a discogs 429, grows each try")
    print("  -verbose            list skipped and outstanding releases, full errors")


def main():
    if "-help" in sys.argv:
        display_help()
        return

    # loose files, worked from their own tags and names, nothing to ask discogs
    if "-rip" in sys.argv and "-rename" in sys.argv:
        rip.rename_library()
        return
    if "-rip" in sys.argv and "-tag" in sys.argv:
        rip.tag_from_names()
        return

    if "-discogs-key" in sys.argv:
        token = sys.argv[sys.argv.index("-discogs-key") + 1]
    else:
        token = json.loads(open("discogs-auth.json", "r").read())["token"]

    print("logging in to discogs")
    discogs = discogs_client.Client('MyDiscogsApp/1.0', user_token=token)

    # ripping only talks to discogs and youtube, it needs no firebase writes
    if "-rip" not in sys.argv:
        dig.setup_firebase_auth()

    user = discogs.identity()
    print("logged in as:", user)

    if "-rip" in sys.argv:
        rip.rip_collection(discogs, token)
    elif "-store" in sys.argv:
        store = sys.argv[sys.argv.index("-store") + 1]
        populate_discogs_links(discogs_match.Discogs(token), store)
    elif "-likes" in sys.argv:
        populate_discogs_likes(discogs_match.Discogs(token), sys.argv[sys.argv.index("-likes") + 1])


if __name__ == "__main__":
    main()