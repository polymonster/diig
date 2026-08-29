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
import re


# yoyaku reworked the product page markup: the old flat `class="product-artists"`
# / `class="product-labels"` / `class="sku"` spans were replaced by a
# `<dl class="product-facts">` block whose entries carry compound classes, e.g.
# `<div class="product-fact product-fact--primary product-artists">`. the old
# exact-class lookups no longer match anything on the main product (they only hit
# the copies inside the related-products section, which we strip), so artist,
# label and cat all silently parsed to "". these helpers target the new markup.
def strip_markup(fragment: str):
    return html.unescape(" ".join(re.sub(r"<[^>]*>", " ", fragment).split())).strip()


# pull the inner html of a single `product-fact ... <cls>` block from the facts list
def parse_product_fact(release_html_str: str, cls: str):
    match = re.search(
        r"<div[^>]*class=\"[^\"]*\bproduct-fact\b[^\"]*\b" + cls + r"\b[^\"]*\"[^>]*>(.*?)</div>",
        release_html_str,
        re.S,
    )
    if match is None:
        return ""
    # drop the <dt> label ("Artist(s)", "Label"), we only want the <dd> value
    return re.sub(r"<dt>.*?</dt>", "", match.group(1), flags=re.S)


# the wordpress post id doubles as the product id used by the track api. the
# listing pages only expose it via a `post-<id>` class on `li.product`, which is
# absent from the bestseller/chart sidebar markup - so ~32% of the registry never
# got one and could never fetch audio or artwork. the detail page always carries
# it in the body class, so use that as the authoritative source.
def parse_post_id(release_html_str: str):
    match = re.search(r"\bpostid-(\d+)", release_html_str)
    return match.group(1) if match else ""


# build the [100x100, 400x400, full] artwork set the registry expects from any
# single upload url, whichever sized variant we happened to find.
def artwork_set(image_url: str):
    if not image_url:
        return []
    base = re.sub(r"-\d+x\d+(?=\.[a-z]+$)", "", image_url)
    stem, _, ext = base.rpartition(".")
    return [f"{stem}-100x100.{ext}", f"{stem}-400x400.{ext}", base]


# artwork fallback straight off the product page, for releases the track api has
# no data for (no audio previews) or that we have no product id for. multi-image
# releases render a slider of `ct-media-container` thumbs, single-image releases
# render one full size `wp-post-image`.
def parse_gallery_artwork(release_html_str: str):
    gallery = re.search(r"class=\"[^\"]*woocommerce-product-gallery[^\"]*\"(.*)", release_html_str, re.S)
    scope = gallery.group(1) if gallery else release_html_str
    slides = re.findall(r"<span class=\"ct-media-container\"[^>]*>\s*<img[^>]*src=\"([^\"]+)\"", scope)
    if slides:
        return artwork_set(slides[0])
    post_image = re.search(r"<img[^>]*class=\"[^\"]*wp-post-image[^\"]*\"[^>]*>", scope)
    if post_image is None:
        # attribute order varies, try src-first form
        post_image = re.search(r"<img[^>]*wp-post-image[^>]*>", scope)
    if post_image:
        src = dig.get_value(post_image.group(0), "src")
        if src:
            return artwork_set(src)
    return []


# extract clean title text from a yoyaku product page.
# yoyaku formats the <h1> as `<a ...>ARTIST</a> — TITLE`, so the release title
# is only the part after the leading artist link. the old parse
# (dig.parse_strip_body) stopped at the first "</", leaving a dangling
# "<a href=...>ARTIST" fragment in the title field. here we drop the leading
# artist anchor, strip any residual tags, and trim the separator.
def clean_product_title(release_html_str: str):
    elem = dig.parse_class_single(release_html_str, "product_title entry-title", "h1")
    if elem is None:
        return ""
    # inner body between the opening <h1 ...> and the closing </h1>
    body_start = elem.find(">")
    body_end = elem.rfind("</h1")
    if body_start != -1 and body_end != -1:
        elem = elem[body_start + 1:body_end]
    # drop the leading artist links so we keep only the release title portion.
    # there may be several (`<a>ARTIST</a>, <a>ARTIST</a> — TITLE`), so cut
    # after the last one
    stripped = elem.lstrip()
    if stripped[:3].lower() == "<a ":
        close = stripped.rfind("</a>")
        if close != -1:
            after = stripped[close + len("</a>"):]
            # only take the tail if there is an actual title after the artists,
            # otherwise fall back to the full text (better than an empty title)
            if after.strip(" -–—,"):
                elem = after
    # strip any residual html tags and collapse whitespace
    elem = re.sub(r"<[^>]*>", "", elem)
    elem = html.unescape(" ".join(elem.split()))
    # trim a leading dash/space separator left by the "ARTIST — TITLE" split
    return elem.lstrip(" -–—,").strip()


# parse every field we take off the product detail page into release_dict.
# shared by the scrape and the backfill so the two can never drift apart.
def parse_detail_page(release_html_str: str, release_dict: dict):
    # strip related products, they repeat the same markup for other releases
    related = release_html_str.find('<section class="related products')
    if related != -1:
        release_html_str = release_html_str[:related]

    release_dict["title"] = clean_product_title(release_html_str)

    # artist. empty is legitimate for various-artists releases
    release_dict["artist"] = strip_markup(parse_product_fact(release_html_str, "product-artists"))

    # label. the <dd> holds the label link followed by the catalogue number span,
    # so cut at the span to keep the label name on its own
    label_fact = parse_product_fact(release_html_str, "product-labels")
    label_name = re.split(r"<span[^>]*class=\"[^\"]*product-fact__catalog", label_fact, maxsplit=1)[0]
    release_dict["label"] = strip_markup(label_name)
    release_dict["label_link"] = dig.get_value(label_fact, "href")

    # cat. `class="sku"` is gone; the catalogue number now lives in a span inside
    # the label fact, prefixed by a screen-reader-only "Catalogue number:" label
    catalog = re.search(r"class=\"[^\"]*product-fact__catalog[^\"]*\"[^>]*>(.*?)</span>\s*</dd>", label_fact, re.S)
    if catalog:
        release_dict["cat"] = re.sub(r"^Catalogue number:\s*", "", strip_markup(catalog.group(1)))
    else:
        release_dict["cat"] = ""

    # the product id, needed for the track api
    post_id = parse_post_id(release_html_str)
    if post_id:
        release_dict["internal_id"] = post_id

    return release_html_str


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

    html_str = dig.strip_scripts_styles(html_str)
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

        # fetch track urls and artworks if missing and -urls flag is set
        needs_url_fetch = (track_url_count == 0 or img_url_count == 0) and "-urls" in sys.argv

        # fetch detail page if artist is missing (mandatory) or we need url info
        needs_detail_fetch = "artist" not in releases_dict.get(key, {}) or needs_url_fetch

        # the detail page is parsed first because it is the only reliable source
        # of the product id: the chart sidebar has no `li.product` markup to read
        # `post-<id>` from, so chart-only releases previously never got one and so
        # never fetched any audio or artwork
        release_html_str = ""
        if needs_detail_fetch:
            release_html_response = dig.request_url_limited(release_dict["link"])
            if release_html_response == None:
                return -1
            release_html_str = release_html_response.read().decode("utf8")
            release_html_str = parse_detail_page(release_html_str, release_dict)

        if needs_url_fetch:
            # internal_id may be missing if releases_ex was shorter than releases
            # fall back to a previously stored value if available
            if not release_dict.get("internal_id"):
                release_dict["internal_id"] = releases_dict.get(key, {}).get("internal_id", "")

        if needs_url_fetch and release_dict.get("internal_id"):
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
                if image_path:
                    release_dict["artworks"] = artwork_set(image_path)

        # some releases carry no audio previews at all, so the track api returns
        # nothing for them. the product page still shows the sleeve, so fall back
        # to that rather than leaving them with no artwork
        if needs_url_fetch and not release_dict.get("artworks") and release_html_str:
            release_dict["artworks"] = parse_gallery_artwork(release_html_str)

        # validate before adding to the registry so we never persist a
        # malformed entry (e.g. leftover html in the title). when the registry
        # already holds the detail info, release_dict is only a partial
        # fragment (store/link/id/pos), so validate the merged result rather
        # than the fragment. skip on failure without marking it scraped, so it
        # is retried on the next run.
        merged_entry = dict()
        dig.merge_dicts(merged_entry, releases_dict.get(key, dict()))
        dig.merge_dicts(merged_entry, release_dict)
        issues = dig.validate_release(key, merged_entry)
        if issues:
            print(f"skipping malformed entry {key}:", flush=True)
            for issue in issues:
                print(f"  - {issue}", flush=True)
            continue

        # track this as scraped already this session
        session_scraped_ids.append(key)

        # merge into main
        merge = dict()
        merge[key] = release_dict
        dig.merge_dicts(releases_dict, merge)

    # write to file
    dig.write_registry(store, releases_dict)

    return counter


def backfill_missing():
    store = "yoyaku"
    releases_dict = dig.load_registry(store)

    # select entries that need repairing: missing artist, or a title with
    # leftover html (e.g. a dangling "<a href=...>" fragment from the old
    # parser). note: title == artist is NOT treated as broken - yoyaku has
    # legitimately self-titled releases (e.g. "Revlux — Revlux").
    # the markup change also left entries with no product id, no artwork, no
    # audio, and a label field that fell back to the catalogue number, so repair
    # those here too.
    def needs_backfill(v):
        title = v.get("title") or ""
        if "artist" not in v or "<" in title or not title.strip():
            return True
        if not v.get("internal_id") or not v.get("artworks") or not v.get("track_urls"):
            return True
        # label parsed as the cat number is the signature of the broken parse
        return bool(v.get("label")) and v.get("label") == v.get("cat")

    missing = {k: v for k, v in releases_dict.items() if needs_backfill(v)}
    print(f"found {len(missing)} entries to backfill", flush=True)

    # repairing the whole backlog is two rate limited requests per entry, so do
    # the releases the app is currently showing first (those carry a chart / new
    # release position key) and allow the rest to be worked through in chunks
    # with `-limit N` across several runs.
    def in_live_view(item):
        return any(k.startswith(f"{store}-") for k in item[1])

    ordered = sorted(missing.items(), key=lambda item: not in_live_view(item))
    if "-limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("-limit") + 1])
        ordered = ordered[:limit]
        print(f"limited to {len(ordered)} entries this run", flush=True)
    missing = dict(ordered)

    updated = dict()
    for key, release in missing.items():
        print(f"backfilling: {key}", flush=True)

        response = dig.request_url_limited(release["link"])
        if response is None:
            print(f"  failed to fetch: {release['link']}", flush=True)
            continue

        release_html_str = response.read().decode("utf8")
        release_html_str = parse_detail_page(release_html_str, release)

        # audio previews and artwork, keyed off the product id we just parsed
        if release.get("internal_id") and (not release.get("track_urls") or not release.get("artworks")):
            product_json = fetch_product_json(release["internal_id"])
            if "data" in product_json:
                release["track_names"] = list()
                release["track_urls"] = list()
                image_path = ""
                for track in product_json["data"]:
                    release["track_names"].append(track.get("title", ""))
                    release["track_urls"].append(track.get("mp3", ""))
                    if "image" in track:
                        image_path = track["image"]
                if image_path:
                    release["artworks"] = artwork_set(image_path)

        # releases with no audio previews get no api data at all, take the sleeve
        # off the product page instead
        if not release.get("artworks"):
            release["artworks"] = parse_gallery_artwork(release_html_str)

        issues = dig.validate_release(key, release)
        if issues:
            print(f"  skipping malformed entry: {issues}", flush=True)
            continue

        releases_dict[key] = release
        updated[key] = release
        print(
            f"  -> {release.get('artist', '?')} - {release.get('title', '?')}"
            f" [{release.get('label', '?')} / {release.get('cat', '?')}]"
            f" {len(release.get('artworks') or [])} art, {len(release.get('track_urls') or [])} trk",
            flush=True,
        )

    if updated:
        dig.write_registry(store, releases_dict)
        print(f"wrote {len(updated)} updated entries to registry", flush=True)
        if "-local-only" not in sys.argv:
            dig.setup_firebase_auth()
            dig.patch_releases(updated)
            print(f"patched {len(updated)} entries to Firebase", flush=True)
    else:
        print("nothing to backfill", flush=True)

