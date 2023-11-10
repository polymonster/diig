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
    # strip out empty entries and strip whitespace
    strip_tracks = []
    for track in tracks:
        if len(track) > 0:
            strip_tracks.append(track.strip())
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


# scrape redeyerecords.co.uk
def scrape_red_eye(page_count, get_urls=True, test_single=False, verbose=False):
    print("scraping: redeye", flush=True)

    urls = [
        ("https://www.redeyerecords.co.uk/techno-electro/weekly-chart", "weekly_chart"),
        ("https://www.redeyerecords.co.uk/techno-electro/monthly-chart", "monthly_chart"),
        ("https://www.redeyerecords.co.uk/techno-electro/new-releases/", "new_releases")
    ]

    for page in range(2, page_count):
        urls.append((f"https://www.redeyerecords.co.uk/techno-electro/new-releases/page-{page}", "new_releases"))

    # store release entries in dict
    releases_dict = dict()

    # load existing registry to speed things up
    reg_filepath = "registry/releases.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())

    # reset the chart and release pos
    for release in releases_dict:
        release = releases_dict[release]
        for (url, category) in urls:
            if "added" not in release:
                now = datetime.datetime.now()
                release["added"] = now.timestamp()
            if category in release:
                release.pop(category, None)

    new_releases = 0
    for (url, category) in urls:
        print(f"scraping page: {url}", flush=True)

        # try and then continue if the page does not exist
        try:
            html_file = urllib.request.urlopen(url)
        except:
            continue

        html_str = html_file.read().decode("utf8")
        releases = cgu.find_all_tokens('class="releaseGrid grid', html_str)

        for release_pos in releases:
            (pos, id_elem) = find_parse_elem(html_str, release_pos, "<div id=", ">", reverse=True)
            (_, artist_elem) = find_parse_elem(html_str, pos, '<p class="artist"', "</p>")
            (_, tracks_elem) = find_parse_elem(html_str, pos, '<p class="tracks"', "</p>")
            (_, label_elem) = find_parse_elem(html_str, pos, '<p class="label"', "</p>")
            (_, link_elem) = find_parse_elem(html_str, pos, '<a class="link"', "</a>")

            release_dict = dict()
            release_dict["id"] = parse_red_eye_release_id(id_elem)
            release_dict["track_names"] = parse_red_eye_track_names(tracks_elem)
            release_dict["link"] = parse_red_eye_release_link(link_elem)
            merge_dicts(release_dict, parse_red_eye_label(label_elem))
            merge_dicts(release_dict, parse_red_eye_artist(artist_elem))
            id = release_dict["id"]

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
                release_dict[category] = releases.index(release_pos)
            else:
                release_dict[category] = new_releases
                new_releases += 1

            # merge into main
            merge = dict()
            merge[release_dict["id"]] = release_dict
            merge_dicts(releases_dict, merge)

        # for dev just bail out after the first page
        if test_single:
            break

    # add added time
    for release in releases_dict:
        release = releases_dict[release]
        for (url, category) in urls:
            if "added" not in release:
                now = datetime.datetime.now()
                release["added"] = now.timestamp()

    release_registry = (json.dumps(releases_dict, indent=4))
    open("registry/releases.json", "w+").write(release_registry)


# main
if __name__ == '__main__':
    get_urls = "-urls" in sys.argv
    test_single = "-test_single" in sys.argv
    verbose = "-verbose" in sys.argv
    scrape_red_eye(100, get_urls, test_single, verbose)
