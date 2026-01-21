import urllib.request
import requests
import http
import dig
import cgu
import os
import json
import datetime
import sys
import html


def fetch_product_json(product_id: int):

    dig.rate_limiter()

    url = "https://yoyaku.io/wp-json/yoyaku/v1/track"
    headers = {
        "Accept": "application/json",
        "Origin": "https://yoyaku.io",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
    }

    # The endpoint accepts form-encoded: id=623892
    resp = requests.post(url, data={"id": product_id}, headers=headers, timeout=20)
    if resp.status_code == 200:
        payload = resp.json()
        if not payload.get("success"):
            return dict()

        return json.loads(json.dumps(payload))

    return dict()


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
def scrape_page(url, store, store_dict, view, section, counter, session_scraped_ids):
    print(f"scraping page: {url}", flush=True)

    # parse releases from page
    html_response = dig.request_url_limited(url)
    if html_response == None:
        return counter + 1
    html_str = html_response.read().decode("utf8")

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
    releases_dict = dig.load_registry(store)
    releases_ex = dig.parse_class(html_str, 'class="product type-product', "li")

    for release in releases:
        # basic info
        release_dict = dict()
        release_dict["store"] = "yoyaku"
        release_dict["link"] = dig.get_value(release, "href")
        release_dict["id"] = os.path.basename(release_dict["link"].strip("/"))

        # assign pos per section
        release_dict[f"{store}-{section}-{view}"] = int(counter)
        counter += 1

        # early out for already processed ids during this session
        key = f"{store}-" + release_dict["id"]
        if key in session_scraped_ids:
            if "-verbose" in sys.argv:
                print(f"quick parse release: {key}", flush=True)
            # merge into main
            merge = dict()
            merge[key] = release_dict
            dig.merge_dicts(releases_dict, merge)
            continue
        elif "-verbose" in sys.argv:
            print(f"parsing release: {key}", flush=True)

        # first implementation did not get the actual internal id
        ii = releases.index(release)
        if ii < len(releases_ex):
            product_info = releases_ex[ii][:releases_ex[ii].find(">") + 1]
            post_id_start = product_info.find("post-") + len("post-")
            post_id_end = product_info.find(" ", post_id_start)
            internal_id = product_info[post_id_start: post_id_end]
            release_dict["internal_id"] = internal_id

            # main page info
            release_dict["store_tags"] = dict()

            # store tags:  out of stock
            release_dict["store_tags"]["out_of_stock"] = False
            if product_info.find("product_cat-out-of-stock") != -1:
                release_dict["store_tags"]["out_of_stock"] = True
                release_dict["store_tags"]["has_been_out_of_stock"] = True

            # store tags:  out of stock
            release_dict["store_tags"]["preorder"] = False
            if product_info.find("product_cat-forthcoming") != -1:
                release_dict["store_tags"]["preorder"] = True

        # check existing tracks
        track_url_count = 0
        if key in releases_dict:
            if "track_urls" in releases_dict[key]:
                track_url_count = len(releases_dict[key]["track_urls"])

        # check eisting images
        img_url_count = 0
        if key in releases_dict:
            if "artworks" in releases_dict[key]:
                img_url_count = len(releases_dict[key]["artworks"])

        # if we have no tracks or images, request product info
        if (track_url_count == 0 or img_url_count == 0) and "-urls" in sys.argv:
            # based on this id we can get json by doing a post request to the API
            product_json = fetch_product_json(release_dict["internal_id"])

            # data and track names
            if "data" in product_json:
                # track names and urls
                release_dict["track_names"] = list()
                release_dict["track_urls"] = list()
                release_dict["artworks"] = list()
                image_path = ""
                for track in product_json["data"]:
                    if "title" in track:
                        release_dict["track_names"].append(track["title"])
                    else:
                        release_dict["track_names"].append("")
                    if "mp3" in track:
                        release_dict["track_urls"].append(track["mp3"])
                    else:
                        release_dict["track_urls"].append("")
                    if "image" in track:
                        image_path = track["image"]

                # infer image set
                if len("image") > 0:
                    release_dict["artworks"].append(image_path)
                    release_dict["artworks"].append(image_path.replace("100x100", "400x400"))
                    release_dict["artworks"].append(image_path.replace("100x100", ""))

            # detail info
            release_html_response = dig.request_url_limited(release_dict["link"])
            if release_html_response == None:
                return -1
            release_html_str = release_html_response.read().decode("utf8")

            # strip related
            related = release_html_str.find('<section class="related products')
            if related != -1:
                release_html_str = release_html_str[:related]

            # title
            title = dig.parse_class_single(release_html_str, "product_title entry-title", "h1")
            title = dig.parse_strip_body(title)
            release_dict["title"] = html.unescape(title)

            # artist info
            pp = release_html_str.find("class=\"product-artists\"")
            pe = release_html_str.find("</span>", pp)
            release_dict["artist"] = dig.parse_strip_body(release_html_str[pp:pe])
            release_dict["artist"] = html.unescape(release_dict["artist"])

            # label info
            pp = release_html_str.find("class=\"product-labels\"")
            pe = release_html_str.find("</span>", pp)
            release_dict["label"] = dig.parse_strip_body(release_html_str[pp:pe])
            release_dict["label_link"] = dig.get_value(release_html_str[pp:pe], "href")
            release_dict["label"] = html.unescape(release_dict["label"])

            # cat
            pp = release_html_str.find("class=\"sku\"")
            pe = release_html_str.find("</span>", pp)
            release_dict["cat"] = dig.parse_strip_body(release_html_str[pp:pe])
            release_dict["cat"] = html.unescape(release_dict["cat"])

        # track this as scraped already this session
        session_scraped_ids.append(key)

        # merge into main
        merge = dict()
        merge[key] = release_dict
        dig.merge_dicts(releases_dict, merge)

    # write to file
    dig.write_registry(store, releases_dict)

    return counter

