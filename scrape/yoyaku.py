import urllib.request
import dig
import cgu
import os
import json
import datetime
import sys

# scrape an individual page for a view (weekly chart, new releases) and section (techno-electro etc)
def scrape_page(url, store, view, section, counter = 0):
    print(f"scraping page: {url}", flush=True)

    req = urllib.request.Request(
        url=url,
        headers={'User-Agent': 'Mozilla/5.0'}
    )

    # try and then continue if the page does not exist
    try:
        html_file = urllib.request.urlopen(req)
    except:
        print("error: url not found {}".format(url))
        return -1

    # parse releases from page
    html_str = html_file.read().decode("utf8")
    releases = dig.parse_class(html_str, "class=\"ct-media-container\"", "a")

    # open existing reg
    releases_dict = dict()
    reg_filepath = f"registry/{store}.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())

    for release in releases:
        release_dict = dict()
        release_dict["store"] = "yoyaku"
        release_dict["link"] = dig.get_value(release, "href")
        release_dict["title"] = dig.get_value(release, "aria-label")
        release_dict["id"] = os.path.basename(release_dict["link"].strip("/"))
        key = f'{release_dict["store"]}-{release_dict["id"]}'

        if key not in releases_dict or "-force" in sys.argv:
            srcset = dig.get_value(release, "srcset")

            # images order
            target_w = [
                "100w",
                "400w",
                "768w"
            ]

            release_dict["artworks"] = list()
            imgs = srcset.split(",")
            for w in target_w:
                for img in imgs:
                    if img.endswith(w):
                        release_dict["artworks"].append(img.strip(w).strip())

            # detail info
            try:
                req = urllib.request.Request(
                    url=release_dict["link"],
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                release_html_file = urllib.request.urlopen(req)
            except:
                print("error: url not found {}".format(url))
                return

            # parse release page
            release_html_str = release_html_file.read().decode("utf8")

            # artist info
            pp = release_html_str.find("class=\"product-artists\"")
            pe = release_html_str.find("</span>", pp)
            release_dict["artist"] = dig.parse_strip_body(release_html_str[pp:pe])

            # label info
            pp = release_html_str.find("class=\"product-labels\"")
            pe = release_html_str.find("</span>", pp)
            release_dict["label"] = dig.parse_strip_body(release_html_str[pp:pe])
            release_dict["label_link"] = dig.get_value(release_html_str[pp:pe], "href")

            # cat
            pp = release_html_str.find("class=\"sku\"")
            pe = release_html_str.find("</span>", pp)
            release_dict["cat"] = dig.parse_strip_body(release_html_str[pp:pe])

            # tracklist
            release_dict["track_names"] = list()
            tracklist = dig.parse_class(release_html_str, "class=\"track fwap-play\"", "a")
            for track in tracklist:
                release_dict["track_names"].append(dig.parse_strip_body(track))

            # track urls
            cdn = "https://yydistribution.ams3.digitaloceanspaces.com/yyplayer/mp3"
            cdn_id = release_dict["cat"].upper()

            id_start = release_dict["id"].rfind("_")
            id_id = release_dict["id"][id_start+1:]

            attempts = [
                cdn_id,
                cdn_id.lower(),
                id_id,
                id_id.upper()
            ]

            release_dict["track_urls"] = list()

            fails = 0
            for attempt in attempts:
                attempt_list = list()
                for i in range(0, len(tracklist)):
                    try:
                        # we need to check if exists
                        linear = f"{cdn}/{attempt}_{i+1}.mp3"
                        if urllib.request.urlopen(linear).code == 200:
                            attempt_list.append(linear)
                    except:
                        # or use the track prefix
                        name = release_dict["track_names"][i]
                        pp = name.find(".")
                        cp = name.find(":")
                        if pp != -1 and cp != -1:
                            pp = min(pp, cp)
                        else:
                            pp = max(pp, cp)
                        try:
                            track_named = f"{cdn}/{attempt}_{name[:pp]}.mp3"
                            if urllib.request.urlopen(track_named).code == 200:
                                attempt_list.append(track_named)
                        except:
                            fails += 1
                            break

                if len(attempt_list) > len(release_dict["track_urls"]):
                    release_dict["track_urls"] = list(attempt_list)
                    break

            # info
            ll = release_dict["link"]
            if len(release_dict["track_urls"]) == 0:
                print(attempts)
                print(f"didn't find tracks for {ll}", flush=True)
            elif "-verbose" in sys.argv:
                print(f"found tracks for {ll}", flush=True)


        # assign pos per section
        release_dict[f"{store}-{section}-{view}"] = int(counter)
        counter += 1

        # merge into main
        merge = dict()
        merge[key] = release_dict
        dig.merge_dicts(releases_dict, merge)

    # write to file
    release_registry = (json.dumps(releases_dict, indent=4))
    open(reg_filepath, "w+").write(release_registry)

    return counter

