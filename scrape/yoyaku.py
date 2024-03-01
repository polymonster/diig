import urllib.request
import http
import dig
import cgu
import os
import json
import datetime
import sys

def debug(url):
    req = urllib.request.Request(
        url=url,
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    html_file = urllib.request.urlopen(req)
    html_str = html_file.read().decode("utf8")
    related = html_str.find('<section class="related products')
    if related != -1:
        html_str = html_str[:related]

    stock = dig.parse_class_single(html_str, "stock out-of-stock", "p")
    if stock:
        print(stock)
        stock = dig.parse_strip_body(stock)
        print(stock)

    low = dig.parse_class_single(html_str, "last-copies", "p")
    if low:
        print(low)
        low = dig.parse_strip_body(low)
        print(low)


# scrape an individual page for a view (weekly chart, new releases) and section (techno-electro etc)
def scrape_page(url, store, view, section, counter, session_scraped_ids):
    print(f"scraping page: {url}", flush=True)

    req = urllib.request.Request(
        url=url,
        headers={'User-Agent': 'Mozilla/5.0'}
    )

    # try and then continue if the page does not exist
    try:
        html_file = urllib.request.urlopen(req)
    except urllib.error.HTTPError:
        print("error: url not found {}".format(url))
        return -1

    # parse releases from page
    html_str = html_file.read().decode("utf8")

    # find the charts
    sidebar = html_str.find("woocommerce-bestsellers")
    if sidebar != -1:
        if dig.is_view_chart(view):
            # ignore generic charts
            bs2 = html_str.find("id=\"yoyaku_wc_bestsellers-2\"")
            if bs2 != -1:
                html_str = html_str[sidebar:bs2]
            else:
                html_str = html_str[sidebar:]
        else:
            # ignore charts
            html_str = html_str[:sidebar]

    releases = dig.parse_class(html_str, "class=\"ct-media-container\"", "a")

    # open existing reg
    releases_dict = dict()
    reg_filepath = f"registry/{store}.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())

    for release in releases:
        # basic info
        release_dict = dict()
        release_dict["store"] = "yoyaku"
        release_dict["link"] = dig.get_value(release, "href")
        release_dict["id"] = os.path.basename(release_dict["link"].strip("/"))
        key = f'{release_dict["store"]}-{release_dict["id"]}'

        # assign pos per section
        release_dict[f"{store}-{section}-{view}"] = int(counter)
        counter += 1

        # early out for already processed ids during this session
        key = f"{store}-" + release_dict["id"]
        if key in session_scraped_ids:
            if "-verbose" in sys.argv:
                print(f"parsing release: {key}", flush=True)
            continue
        elif "-verbose" in sys.argv:
            print(f"parsing release: {key}", flush=True)

        # main page info
        release_dict["title"] = dig.get_value(release, "aria-label")
        release_dict["store_tags"] = dict()

        # check existing tracks
        track_url_count = 0
        if key in releases_dict:
            if "track_urls" in releases_dict[key]:
                track_url_count = len(releases_dict[key]["track_urls"])

        # look for src set
        srcset = dig.get_value(release, "srcset")
        if srcset != None:
            # images order
            target_w = [
                "100w",
                "400w",
                "600w",
                "768w"
            ]

            release_dict["artworks"] = list()
            imgs = srcset.split(",")
            for w in target_w:
                for img in imgs:
                    if img.endswith(w):
                        release_dict["artworks"].append(img.strip(w).strip())
        else:
            # might have single image
            img = dig.get_value(release, "src")
            if img != None:
                # splat 3
                release_dict["artworks"] = list()
                for i in range(0, 3):
                    release_dict["artworks"].append(img)

        # detail info
        try:
            req = urllib.request.Request(
                url=release_dict["link"],
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            release_html_file = urllib.request.urlopen(req)
        except urllib.error.HTTPError:
            print("error: url not found {}".format(url))
            continue

        # parse release page
        release_html_str = release_html_file.read().decode("utf8")

        # strip related
        related = release_html_str.find('<section class="related products')
        if related != -1:
            release_html_str = release_html_str[:related]

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

        # store tags: preorder / out of stock
        release_dict["store_tags"]["out_of_stock"] = False
        release_dict["store_tags"]["preorder"] = False
        if release_html_str.find("stock out-of-stock") != -1:
            stock = dig.parse_class_single(release_html_str, "stock out-of-stock", "p")
            if stock:
                stock = dig.parse_strip_body(stock).lower()
                if stock == "out of stock":
                    release_dict["store_tags"]["out_of_stock"] = True
                    release_dict["store_tags"]["has_been_out_of_stock"] = True
                else:
                    release_dict["store_tags"]["preorder"] = True

        # store tags: low stock..,
        release_dict["store_tags"]["low_stock"] = False
        if release_html_str.find("last-copies") != -1:
            low = dig.parse_class_single(release_html_str, "last-copies", "p")
            if low:
                low = dig.parse_strip_body(low).lower()
                if low == "last copies" or low == "last copy":
                    release_dict["store_tags"]["low_stock"] = True

        # track urls
        if "-urls" in sys.argv and track_url_count != len(tracklist):
            cdn = "https://yydistribution.ams3.digitaloceanspaces.com/yyplayer/mp3"
            cdn_id = release_dict["cat"]

            id_start = release_dict["id"].rfind("_")
            id_id = release_dict["id"][id_start+1:]

            attempts = [
                cdn_id,
                cdn_id.upper(),
                cdn_id.lower(),
                id_id,
                id_id.upper()
            ]

            release_dict["track_urls"] = list()

            for attempt in attempts:
                attempt_list = list()
                use_attempt = False
                use_named = False
                for i in range(0, len(tracklist)):
                    try:
                        # we need to check if exists
                        linear = f"{cdn}/{attempt}_{i+1}.mp3"
                        if urllib.request.urlopen(linear).code == 200:
                            print(f"use linear naming: {linear}", flush=True)
                            use_attempt = True
                            break
                    except urllib.error.HTTPError:
                        # or use the track prefix
                        name = release_dict["track_names"][i]
                        pp = name.find(".")
                        cp = name.find(":")
                        if pp != -1 and cp != -1:
                            pp = min(pp, cp)
                        if pp == -1 and cp == -1:
                            break
                        else:
                            pp = max(pp, cp)
                        try:
                            track_named = f"{cdn}/{attempt}_{name[:pp]}.mp3"
                            if urllib.request.urlopen(track_named).code == 200:
                                print(f"use track side naming: {name[:pp]}", flush=True)
                                use_attempt = True
                                use_named = True
                                break
                        except urllib.error.HTTPError:
                            break
                        except http.client.InvalidURL:
                            break

                # if we found compatible urls just assume the rest
                if use_attempt:
                    for i in range(0, len(tracklist)):
                        if use_named:
                            name = release_dict["track_names"][i]
                            pp = name.find(".")
                            cp = name.find(":")
                            if pp != -1 and cp != -1:
                                pp = min(pp, cp)
                            else:
                                pp = max(pp, cp)
                            print(f"{cdn}/{attempt}_{name[:pp]}.mp3")
                            attempt_list.append(f"{cdn}/{attempt}_{name[:pp]}.mp3")
                        else:
                            print(f"{cdn}/{attempt}_{i+1}.mp3")
                            attempt_list.append(f"{cdn}/{attempt}_{i+1}.mp3")
                    if len(attempt_list) > len(release_dict["track_urls"]):
                        release_dict["track_urls"] = list(attempt_list)
                    break

            # print status on missing tracks
            ll = release_dict["link"]
            if "-verbose" in sys.argv:
                if "track_urls" in release_dict:
                    if len(release_dict["track_urls"]) == 0:
                        print(attempts)
                        print(f"didn't find tracks for {ll}", flush=True)
                    elif "-verbose" in sys.argv:
                        print(f"found tracks for {ll}", flush=True)

        # track this as scraped already this session
        session_scraped_ids.append(key)

        # merge into main
        merge = dict()
        merge[key] = release_dict
        dig.merge_dicts(releases_dict, merge)

    # write to file
    release_registry = (json.dumps(releases_dict, indent=4))
    open(reg_filepath, "w+").write(release_registry)

    return counter

