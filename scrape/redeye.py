import urllib.request
import dig
import cgu
import os
import json
import datetime
import sys

# etxract the release id number from a red eye records release
def parse_redeye_release_id(elem: str):
    (id_start, id_end) = cgu.enclose_start_end('"', '"', elem, 0)
    id_end = id_start + elem[id_start:id_end].find('"')
    return elem[id_start:id_end]


# extract the red eye ARTIST - TITLE
def parse_redeye_artist(elem: str):
    body = dig.parse_body(elem)
    artist_end = body.find("-")
    if artist_end == -1:
        artist_end = len(elem)
    return {
        "artist": body[:artist_end].strip(),
        "title": body[artist_end+1:].strip()
    }


# try parsing and splitting tracks that do no match the target number of urls
def reparse_and_split_tracks(track_names: list, target: int):
    output_names = []

    concated = ""
    for name in track_names:
        concated += name

    # search for a1 b1, or 01, 02 etc, also try a, b, 0, 1 etc
    sides = ["a", "0"]
    for side in sides:
        track = 2
        iter = 0
        while len(output_names) < target:
            # try lower
            p = concated.find(side + str(track))
            if p == -1:
                # try upper
                p = concated.find(side.upper() + str(track))
            if p == -1:
                # try upper without track number
                p = concated.find(side.upper())
            if p == -1:
                # try lower without track number
                p = concated.find(side)
            if p != -1:
                output_names.append(concated[:p])
                concated = concated[p:]
                track += 1
            else:
                side = chr(ord(side) + 1)
                track = 1
            if iter > target:
                break
            iter += 1
        if output_names == target:
            break

    if len(concated) > 0:
        output_names.append(concated)
    return output_names


# extract the red eye track names (separated by '\n' '/' ',')
def parse_redeye_track_names(elem: str):
    body = dig.parse_body(elem)
    tracks = body.splitlines()
    # some are separated by '/'
    if len(tracks) == 1:
        tracks = body.split("/")
    # some are separated by ','
    if len(tracks) == 1:
        tracks = body.split(",")
    # strip out empty entries and strip whitespace and trailing commas
    strip_tracks = []
    for track in tracks:
        ss = track.strip().strip(",")
        if len(ss) > 0:
            strip_tracks.append(ss)
    return strip_tracks


# parse label info from release it has CAT<br><a href="link">LABEL_NAME</a>
def parse_redeye_label(elem: str):
    (cat_start, cat_end) = cgu.enclose_start_end(">", "<", elem, 0)
    (ns, ne) = cgu.enclose_start_end(">", "<", elem, cat_end)
    (label_start, label_end) = cgu.enclose_start_end(">", "<", elem, ne)
    return {
        "cat": elem[cat_start:cat_end],
        "label": elem[label_start:label_end],
        "label_link": dig.get_value(elem, "href")
    }


# parse release link <a href="link"
def parse_redeye_release_link(elem: str):
    return dig.get_value(elem, "href")


# get redeye snippet urls inspecting the release page to get track count and assuming convention:
# release_id, release_idb, release_idc...
def get_redeye_snippit_urls(release_url, cdn, release_id):
    tracks = list()

    release_html = dig.request_url_limited(release_url)
    if release_html == None:
        return -1
    release_html = dig.fetch_cache_page(release_url, "references/redeye_release.html")

    play_div = dig.parse_div(release_html, 'class="play"')
    if len(play_div) > 0:
        pos = 0
        while True:
            (pos, elem) = dig.find_parse_elem(play_div[0], pos, "<a class='btn-play'", "</a>")
            if elem.find("></a><a class='btn-play-all'>") != -1:
                break
            else:
                suffix = dig.get_value(elem, "data-sample")
                if suffix == "a":
                    suffix = ""
                tracks.append(f"{cdn}{release_id}{suffix}.mp3")

    return tracks
    

# get red eye artwork urls trying releaseid-index for different sizes
def get_redeye_artwork_urls(release_id):
    artworks = list()
    cdn = "https://www.redeyerecords.co.uk/imagery/"
    # check the artwork exists
    for i in range(0, 3):
        artworks.append(f"{cdn}{release_id}-{i}.jpg")
    return artworks


# find and parse all grid elems
def parse_redeye_grid_elems(html_str):
    releases_html = []
    while True:
        first = html_str.find('class="releaseGrid')
        # no more left
        if first == -1:
            break
        start = html_str[:first].rfind("<div ")
        stack = 1
        iter_pos = first
        while stack > 0:
            open = html_str.find("<div", iter_pos)
            close = html_str.find("</div", iter_pos)
            if open != 1 and close != -1 and open < close:
                stack += 1
                iter_pos = open + 5
            elif close != -1:
                stack -= 1
                iter_pos = close + 5

        releases_html.append(html_str[start:iter_pos])

        # iterate
        html_str = html_str[iter_pos:]

    return releases_html


# scrape an individual page for a view (weekly chart, new releases) and section (techno-electro etc)
def scrape_page(url, store, view, section, counter, session_scraped_ids):
    print(f"scraping page: {url}", flush=True)

    # grab var args
    verbose = "verbose" in sys.argv
    get_urls = "-urls" in sys.argv

    html_file = dig.request_url_limited(url)
    if html_file == None:
        return -1

    # store release entries in dict
    releases_dict = dict()

    # load existing registry to speed things up
    reg_filepath = f"registry/{store}.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())

    html_str = html_file.read().decode("utf8")
    grid_elems = parse_redeye_grid_elems(html_str)

    for grid_elem in grid_elems:
        # basic info
        (_, id_elem) = dig.find_parse_elem(grid_elem, 0, "<div id=", ">")
        release_dict = dict()
        release_dict["store_tags"] = dict()
        release_dict["store"] = f"{store}"
        release_dict["id"] = parse_redeye_release_id(id_elem)
        id = release_dict["id"]

        key = "{}-{}".format(store, release_dict["id"])

        # get indices
        if view in ["weekly_chart", "monthly_chart"]:
            pos = grid_elems.index(grid_elem)
            release_dict["store_tags"]["has_charted"] = True
        else:
            pos = counter

        # assign pos per section
        release_dict[f"{store}-{section}-{view}"] = int(pos)
        counter += 1

        # early out for already processed ids during this session
        key = f"{store}-" + release_dict["id"]
        if key in session_scraped_ids:
            if "-verbose" in sys.argv:
                print(f"parsing release: {key}", flush=True)
            # merge into main
            merge = dict()
            merge[key] = release_dict
            dig.merge_dicts(releases_dict, merge)
            continue
        elif "-verbose" in sys.argv:
            print(f"parsing release: {key}", flush=True)

        (_, artist_elem) = dig.find_parse_elem(grid_elem, 0, '<p class="artist"', "</p>")
        (_, tracks_elem) = dig.find_parse_elem(grid_elem, 0, '<p class="tracks"', "</p>")
        (_, label_elem) = dig.find_parse_elem(grid_elem, 0, '<p class="label"', "</p>")
        (_, link_elem) = dig.find_parse_elem(grid_elem, 0, '<a class="link"', "</a>")

        release_dict["track_names"] = parse_redeye_track_names(tracks_elem)
        release_dict["link"] = parse_redeye_release_link(link_elem)
        dig.merge_dicts(release_dict, parse_redeye_label(label_elem))
        dig.merge_dicts(release_dict, parse_redeye_artist(artist_elem))

        # add store tags
        if grid_elem.find("price preorder") != -1:
            release_dict["store_tags"]["preorder"] = True
        else:
            release_dict["store_tags"]["preorder"] = False

        if grid_elem.find("Out Of Stock") != -1:
            release_dict["store_tags"]["out_of_stock"] = True
            release_dict["store_tags"]["has_been_out_of_stock"] = True
        else:
            release_dict["store_tags"]["out_of_stock"] = False

        # extra print for debugging long jobs
        if verbose:
            print(f"scraping release urls: {id}", flush=True)

        # this takes a little while so its useful to skip during dev
        if get_urls:
            # check if we already have urls and skip them
            has_artworks = False
            has_tracks = False
            if key in releases_dict:
                if "track_urls" in releases_dict[key]:
                    if len(releases_dict[key]["track_urls"]) > 0:
                        has_tracks = True
                if "artworks" in releases_dict[key]:
                    if len(releases_dict[key]["artworks"]) > 0:
                        has_artworks = True

            if not has_tracks:
                release_dict["track_urls"] = get_redeye_snippit_urls(release_dict["link"], "https://sounds.redeyerecords.co.uk/", id)

            if not has_artworks:
                release_dict["artworks"] = get_redeye_artwork_urls(id)

        # merge into main
        merge = dict()
        merge[key] = release_dict
        dig.merge_dicts(releases_dict, merge)

        # flagg for scraped this session
        session_scraped_ids.append(key)

        # validate track counts and try reparsing
        merged = releases_dict[key]
        if "track_urls" in merged and "track_names" in merged:
            if len(merged["track_urls"]) > 0:
                if len(merged["track_urls"]) != len(merged["track_names"]):
                    merged["track_names"] = reparse_and_split_tracks(merged["track_names"], len(merged["track_urls"]))

    # write results back
    release_registry = (json.dumps(releases_dict, indent=4))
    open(reg_filepath, "w+").write(release_registry)

    dig.scrape_yield()
    return counter


# reformat data to v2 version which was modified to accomodate firebase, multiple stores and more+
def reformat_v2():
    # load existing registry to speed things up
    reg_filepath = "registry/releases.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())

        for (k, v) in releases_dict.items():
            # ensure we have store: redeye
            v["store"] = "redeye"

            # remove the loose has_charted tag
            if "has_charted" in v:
                del v["has_charted"]

            # move section grouped charts and latest
            # move separate tags to grouped 'sections'
            if "tags" in v:
                sections = [
                    "weekly_chart",
                    "monthly_chart",
                    "new_releases"
                ]
                for section in sections:
                    if section in v:
                        if "techno" in v["tags"]:
                            v["{}-{}-{}".format("redeye", section, "techno-electro")] = v[section]
                        if "house" in v["tags"]:
                            v["{}-{}-{}".format("redeye", section, "house-disco")] = v[section]
                        del v[section]
                del v["tags"]

        # prepend redeye to release keys
        formatted = dict()
        for (k, v) in releases_dict.items():
            formatted["{}-{}".format("redeye", k)] = v

        # write
        formatted_reg = (json.dumps(formatted, indent=4))
        open("registry/redeye.json", "w+").write(formatted_reg)

