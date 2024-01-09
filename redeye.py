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
    return {
        "artist": body[:artist_end].strip(),
        "title": body[artist_end+1:].strip()
    }


# try parsing and splitting tracks that do no match the target number of urls
def reparse_and_split_tracks(track_names: list, target: int):
    output_names = []
    side = 'a'
    track = 2
    iter = 0
    concated = ""
    if len(track_names) == 1:
        concated = track_names[0]
        while len(output_names) < target:
            # try lower
            p = concated.find(side + str(track))
            if p == -1:
                # try upper
                p = concated.find(side.upper() + str(track))
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
    else:
        return track_names
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


# find snippit urls by trying id-track and returning when none are found
def get_redeye_snippit_urls(release_id):
    tracks = list()
    cdn = "https://redeye-391831.c.cdn77.org/"
    # check the releaseid exists, this is track-a
    try_url = f"{cdn}{release_id}.mp3"
    try:
        if urllib.request.urlopen(try_url).code == 200:
            tracks.append(f"{cdn}{str(release_id)}.mp3")
            # now iterate until we find no more tracks
            l = 'b'
            while True:
                try_url = f"{cdn}{release_id}{l}.mp3"
                if urllib.request.urlopen(try_url).code == 200:
                    tracks.append(try_url)
                else:
                    break
                l = chr(ord(l) + 1)
    except:
        pass
    return tracks


# get red eye artwork urls trying releaseid-index for different sizes
def get_redeye_artwork_urls(release_id):
    artworks = list()
    cdn = "https://www.redeyerecords.co.uk/imagery/"
    # check the artwork exists
    try:
        for i in range(0, 3):
            try_url = f"{cdn}{release_id}-{i}.jpg"
            if urllib.request.urlopen(try_url).code == 200:
                artworks.append(try_url)
    except:
        pass
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


# scrape an individual page for a category (weekly chart, new releases) and section (techno-electro etc)
def scrape_page(url, store, category, section, counter = 0):
    print(f"scraping page: {url}", flush=True)

    # grab var args
    verbose = "verbose" in sys.argv
    get_urls = "-urls" in sys.argv

    # try and then continue if the page does not exist
    try:
        html_file = urllib.request.urlopen(url)
    except:
        print("error: url not found {}".format(url))
        return

    # store release entries in dict
    releases_dict = dict()

    # load existing registry to speed things up
    reg_filepath = f"registry/{store}.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())

    html_str = html_file.read().decode("utf8")
    grid_elems = parse_redeye_grid_elems(html_str)

    for grid_elem in grid_elems:
        (_, id_elem) = dig.find_parse_elem(grid_elem, 0, "<div id=", ">")
        (_, artist_elem) = dig.find_parse_elem(grid_elem, 0, '<p class="artist"', "</p>")
        (_, tracks_elem) = dig.find_parse_elem(grid_elem, 0, '<p class="tracks"', "</p>")
        (_, label_elem) = dig.find_parse_elem(grid_elem, 0, '<p class="label"', "</p>")
        (_, link_elem) = dig.find_parse_elem(grid_elem, 0, '<a class="link"', "</a>")

        release_dict = dict()
        release_dict["store"] = f"{store}"
        release_dict["id"] = parse_redeye_release_id(id_elem)
        release_dict["track_names"] = parse_redeye_track_names(tracks_elem)
        release_dict["link"] = parse_redeye_release_link(link_elem)
        dig.merge_dicts(release_dict, parse_redeye_label(label_elem))
        dig.merge_dicts(release_dict, parse_redeye_artist(artist_elem))
        id = release_dict["id"]
        release_dict["store_tags"] = dict()
        key = "{}-{}".format(store, release_dict["id"])

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
                release_dict["track_urls"] = get_redeye_snippit_urls(id)

            if not has_artworks:
                release_dict["artworks"] = get_redeye_artwork_urls(id)

        # get indices
        if category in ["weekly_chart", "monthly_chart"]:
            pos = grid_elems.index(grid_elem)
            release_dict["store_tags"]["has_charted"] = True
        else:
            pos = counter

        # assign pos per section
        release_dict[f"{store}-{category}_{section}"] = int(pos)

        # increment counter
        counter += 1

        # merge into main
        merge = dict()
        merge[key] = release_dict
        dig.merge_dicts(releases_dict, merge)

        # validate track counts and try reparsing
        merged = releases_dict[key]
        if "track_urls" in merged and "track_names" in merged:
            if len(merged["track_urls"]) > 0:
                if len(merged["track_urls"]) != len(merged["track_names"]):
                    merged["track_names"] = reparse_and_split_tracks(merged["track_names"], len(merged["track_urls"]))

    # write results back
    release_registry = (json.dumps(releases_dict, indent=4))
    open(reg_filepath, "w+").write(release_registry)

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



# scrape redeyerecords.co.uk
def scrape_legacy(page_count, get_urls=True, test_single=False, verbose=False):
    print("scraping: redeye", flush=True)

    x = lambda a : a + 10

    # categories
    urls = [
        ("https://www.redeyerecords.co.uk/techno-electro/weekly-chart", "weekly_chart", ["techno", "electro"]),
        ("https://www.redeyerecords.co.uk/techno-electro/monthly-chart", "monthly_chart", ["techno", "electro"]),
        ("https://www.redeyerecords.co.uk/techno-electro/new-releases/", "new_releases", ["techno", "electro"])
    ]

    for page in range(2, page_count):
        urls.append((f"https://www.redeyerecords.co.uk/techno-electro/new-releases/page-{page}", "new_releases", ["techno", "electro"]))

    urls.append(
        ("https://www.redeyerecords.co.uk/house-disco/weekly-chart", "weekly_chart", ["house", "disco"])
    )

    urls.append(
        ("https://www.redeyerecords.co.uk/house-disco/monthly-chart", "monthly_chart", ["house", "disco"])
    )

    urls.append(
        ("https://www.redeyerecords.co.uk/house-disco/new-releases/", "new_releases", ["house", "disco"])
    )

    for page in range(2, page_count):
        urls.append((f"https://www.redeyerecords.co.uk/house-disco/new-releases/page-{page}", "new_releases", ["house", "disco"]))

    # store release entries in dict
    releases_dict = dict()

    # load existing registry to speed things up
    reg_filepath = "registry/releases.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())

    # reset the chart and release pos
    for release in releases_dict:
        release = releases_dict[release]
        for (url, category, tags) in urls:
            if "added" not in release:
                now = datetime.datetime.now()
                release["added"] = now.timestamp()
            if category in release:
                release.pop(category, None)

    new_releases = 0
    for (url, category, tags) in urls:
        print(f"scraping page: {url}", flush=True)

        # try and then continue if the page does not exist
        try:
            html_file = urllib.request.urlopen(url)
        except:
            continue

        html_str = html_file.read().decode("utf8")
        grid_elems = parse_redeye_grid_elems(html_str)

        for grid_elem in grid_elems:
            (_, id_elem) = dig.find_parse_elem(grid_elem, 0, "<div id=", ">")
            (_, artist_elem) = dig.find_parse_elem(grid_elem, 0, '<p class="artist"', "</p>")
            (_, tracks_elem) = dig.find_parse_elem(grid_elem, 0, '<p class="tracks"', "</p>")
            (_, label_elem) = dig.find_parse_elem(grid_elem, 0, '<p class="label"', "</p>")
            (_, link_elem) = dig.find_parse_elem(grid_elem, 0, '<a class="link"', "</a>")

            release_dict = dict()
            release_dict["store"] = "redeye"
            release_dict["id"] = parse_redeye_release_id(id_elem)
            release_dict["track_names"] = parse_redeye_track_names(tracks_elem)
            release_dict["link"] = parse_redeye_release_link(link_elem)
            dig.merge_dicts(release_dict, parse_redeye_label(label_elem))
            dig.merge_dicts(release_dict, parse_redeye_artist(artist_elem))
            id = release_dict["id"]
            release_dict["tags"] = dict()
            release_dict["store_tags"] = dict()

            # add tags
            for tag in tags:
                release_dict["tags"][tag] = True

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
                if id in releases_dict:
                    if "track_urls" in releases_dict[id]:
                        if len(releases_dict[id]["track_urls"]) > 0:
                            has_tracks = True
                    if "artworks" in releases_dict[id]:
                        if len(releases_dict[id]["artworks"]) > 0:
                            has_artworks = True

                if not has_tracks:
                    release_dict["track_urls"] = get_redeye_snippit_urls(id)

                if not has_artworks:
                    release_dict["artworks"] = get_redeye_artwork_urls(id)

            # assign indices
            if category in ["weekly_chart", "monthly_chart"]:
                release_dict[category] = grid_elems.index(grid_elem)
                release_dict["store_tags"]["has_charted"] = True
            else:
                release_dict[category] = new_releases
                new_releases += 1

            # merge into main
            merge = dict()
            merge[release_dict["id"]] = release_dict
            dig.merge_dicts(releases_dict, merge)

            # validate track counts and try reparsing
            merged = releases_dict[release_dict["id"]]
            if "track_urls" in merged and "track_names" in merged:
                if len(merged["track_urls"]) > 0:
                    if len(merged["track_urls"]) != len(merged["track_names"]):
                        merged["track_names"] = reparse_and_split_tracks(merged["track_names"], len(merged["track_urls"]))

        # for dev just bail out after the first page
        if test_single:
            break

    # add added time
    for release in releases_dict:
        release = releases_dict[release]
        for (url, category, tags) in urls:
            if "added" not in release:
                now = datetime.datetime.now()
                release["added"] = now.timestamp()

    # sort the entries
    sort = sorted(releases_dict.items(), key=lambda kv: dig.sort_func(kv))

    releases_dict = dict()

    # add them back in order
    for i in sort:
        k = i[0]
        v = i[1]
        releases_dict[k] = v

    release_registry = (json.dumps(releases_dict, indent=4))
    open("registry/releases.json", "w+").write(release_registry)
