import urllib.request
import cgu
import json
import sys
import os
import datetime

# member wise merge 2 dicts, second will overwrite dest
def merge_dicts(dest, second):
    for k, v in second.items():
        if type(v) == dict:
            if k not in dest or type(dest[k]) != dict:
                dest[k] = dict()
            merge_dicts(dest[k], v)
        else:
            dest[k] = v


# find and parse a named html element
def find_parse_elem(text: str, pos: int, ident: str, end_str: str, reverse=False):
    if reverse:
        pos = text[0:pos].rfind(ident)
    else:
        pos = pos + text[pos:].find(ident)
        assert(pos != -1)

    # parse the start element
    end = cgu.enclose("<", ">", text, pos)

    # parse the rest of the body
    last = end-1
    if text[last] != end_str:
        end = last + text[last:].find(end_str)

    # return the result and the iter pos
    elem =  text[pos:end]
    return (end, elem)


# get the value of a html element, ie <a href="value"
def get_value(elem: str, ident: str):
    pos = elem.find(ident + "=")
    if pos != -1:
        val_start, encloser = cgu.find_first(elem, ["\"", "'"], pos)
        val_start = val_start+1
        val_end = val_start + elem[val_start:].find(encloser)
        return elem[val_start:val_end]
    return None


# parse the html tag to return the body text <p class="tag">BODY</p>
def parse_body(elem: str):
    tag_end = cgu.enclose("<", ">", elem, 0)
    return elem[tag_end:]


# etxract the release id number from a red eye records release
def parse_red_eye_release_id(elem: str):
    (id_start, id_end) = cgu.enclose_start_end('"', '"', elem, 0)
    id_end = id_start + elem[id_start:id_end].find('"')
    return elem[id_start:id_end]


# extract the red eye ARTIST - TITLE
def parse_red_eye_artist(elem: str):
    body = parse_body(elem)
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
def parse_red_eye_track_names(elem: str):
    body = parse_body(elem)
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
def parse_red_eye_label(elem: str):
    (cat_start, cat_end) = cgu.enclose_start_end(">", "<", elem, 0)
    (ns, ne) = cgu.enclose_start_end(">", "<", elem, cat_end)
    (label_start, label_end) = cgu.enclose_start_end(">", "<", elem, ne)
    return {
        "cat": elem[cat_start:cat_end],
        "label": elem[label_start:label_end],
        "label_link": get_value(elem, "href")
    }


# parse release link <a href="link"
def parse_red_eye_release_link(elem: str):
    return get_value(elem, "href")


# find snippit urls by trying id-track and returning when none are found
def get_red_eye_snippit_urls(release_id):
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
def get_red_eye_artwork_urls(release_id):
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


# function to sort release
def sort_func(kv):
    if kv != None:
        if "new_releases" in kv[1]:
            return kv[1]["new_releases"]
        else:
            now = datetime.datetime.now()
            return now.timestamp() - kv[1]["added"]


# find and parse all grid elems
def parse_grid_elems(html_str):
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


# scrape redeyerecords.co.uk
def scrape_red_eye(page_count, get_urls=True, test_single=False, verbose=False):
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
        grid_elems = parse_grid_elems(html_str)

        for grid_elem in grid_elems:
            (_, id_elem) = find_parse_elem(grid_elem, 0, "<div id=", ">")
            (_, artist_elem) = find_parse_elem(grid_elem, 0, '<p class="artist"', "</p>")
            (_, tracks_elem) = find_parse_elem(grid_elem, 0, '<p class="tracks"', "</p>")
            (_, label_elem) = find_parse_elem(grid_elem, 0, '<p class="label"', "</p>")
            (_, link_elem) = find_parse_elem(grid_elem, 0, '<a class="link"', "</a>")

            release_dict = dict()
            release_dict["id"] = parse_red_eye_release_id(id_elem)
            release_dict["track_names"] = parse_red_eye_track_names(tracks_elem)
            release_dict["link"] = parse_red_eye_release_link(link_elem)
            merge_dicts(release_dict, parse_red_eye_label(label_elem))
            merge_dicts(release_dict, parse_red_eye_artist(artist_elem))
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
                    release_dict["track_urls"] = get_red_eye_snippit_urls(id)

                if not has_artworks:
                    release_dict["artworks"] = get_red_eye_artwork_urls(id)

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
            merge_dicts(releases_dict, merge)

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
    sort = sorted(releases_dict.items(), key=lambda kv: sort_func(kv))

    releases_dict = dict()

    # add them back in order
    for i in sort:
        k = i[0]
        v = i[1]
        releases_dict[k] = v

    release_registry = (json.dumps(releases_dict, indent=4))
    open("registry/releases.json", "w+").write(release_registry)


# parse entireity of a div section
def parse_div(html_str, div_class):
    divs = []
    while True:
        first = html_str.find(div_class)
        # no more left
        if first == -1:
            break
        start = html_str[:first].rfind("<div ")
        stack = 1
        iter_pos = first
        escape = 5
        while stack > 0:
            open = cgu.us(html_str.find("<div", iter_pos))
            close = html_str.find("</div", iter_pos)
            if close != -1 and open < close:
                stack += 1
                iter_pos = open + 5
            elif close != -1:
                stack -= 1
                iter_pos = close + 5

        divs.append(html_str[start:iter_pos])

        # iterate
        html_str = html_str[iter_pos:]

    return divs

# juno
def scrape_juno(url):
    print("scraping: juno", flush=True)

    # try and then continue if the page does not exist
    try:
        html_file = urllib.request.urlopen(url)
    except:
        return

    html_str = html_file.read().decode("utf8")

    # gets products
    products = parse_div(html_str, 'class="product-list"')

    # separate into items
    releases = parse_div(products[0], 'class="dv-item"')


# main
if __name__ == '__main__':
    get_urls = "-urls" in sys.argv
    test_single = "-test_single" in sys.argv
    verbose = "-verbose" in sys.argv
    store = "redeye"
    if "-store" in sys.argv:
        store = sys.argv[sys.argv.index("-store") + 1]

    if store == "juno":
        scrape_juno("https://www.juno.co.uk/minimal-tech-house/charts/bestsellers/this-week/")
    elif store == "redeye":
        scrape_red_eye(100, get_urls, test_single, verbose)