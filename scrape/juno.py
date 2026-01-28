import cgu
import json
import sys
import os
import datetime
import dig

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import InvalidSessionIdException
from selenium.common.exceptions import WebDriverException
from urllib3.exceptions import ReadTimeoutError

# parse ide element <div id="item-861163-1" class="dv-item"> to extract the
# id number without the item- prefix
def parse_id(id_elem: str):
    item_str = dig.get_value(id_elem, "id")
    id = item_str.strip("item-")
    return id


# parse link url out of <a href="/products/moy-on-wire-breaking-the-loop-ep-vinyl/861163-01/">
# and concatonate to https://www.juno.co.uk
def parse_link(link_elem: str):
    link = dig.get_value(link_elem, "href")
    return 'https://www.juno.co.uk' + link


# extract label body from a long html string, it is the body element at the very end
def parse_label(label_elem: str):
    start = label_elem.rfind(">")
    return label_elem[start+1:]


# extract the catalogue number of a release from <div class="vi-text mb-1">Cat: UFOS 004. Rel:&nbsp;28 Mar 22
def parse_cat(cat_elem: str):
    info_str = dig.parse_body(cat_elem)
    cat_end = info_str.rfind(".")
    cat_start = info_str.rfind("Cat:") + len("Cat:")
    return info_str[cat_start:cat_end].strip()


# parse small artwork url from <img class="lazy_img img-fluid" src="https://imagescdn.juno.co.uk/150/CS869223-01A.jpg" alt="420">
# construct them as so:
# small - https://imagescdn.juno.co.uk/full/CS861163-01A-BIG.jpg
# med - https://imagescdn.juno.co.uk/300/CS983218-01A-MED.jpg
# large - https://imagescdn.juno.co.uk/150/CS861163-01A.jpg
def parse_artworks(artwork_elem):
    small = dig.get_value(artwork_elem, "src")
    if small.find("data:image") != -1:
        small = dig.get_value(artwork_elem, "data-src")
    med = small.replace("/150/", "/300/").replace(".jpg", "-MED.jpg")
    med = med.replace("-MED-MED", "-MED")
    large = small.replace("/150/", "/full/").replace(".jpg", "-BIG.jpg")
    large = large.replace("-MED-BIG", "-BIG")
    return [small, med, large]


# parse track urls and names out of list of html elems
# <div class="listing-track">
#   <div><a class="btn btn-play-sm" href="https://www.juno.co.uk/MP3/SF869223-01-02-03.mp3" data-ua_action="play" rel="nofollow" data-turbo="false"></a></div>
# <div>Untitled 5 (4:19)</div>
# return as tuple (track_names, track_urls)
def parse_tracks(tracks):
    track_names = []
    track_urls = []
    for track in tracks:
        url = dig.get_value(track, "href")
        nest = 6
        if url is None:
            nest = 4
        else:
            track_urls.append(url)
        name = dig.parse_nested_body(track, nest)
        track_names.append(name)
    return (track_names, track_urls)


# fetch html using selenium driver
def execute_page(url, driver):
    driver.get(url)
    wait = WebDriverWait(driver, 120)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")

    # wait for cloudflare challenge to resolve (page title changes from "Just a moment...")
    print("debug: waiting for cloudflare challenge...")
    try:
        wait.until(lambda d: "Just a moment" not in d.title)
        print("debug: cloudflare challenge passed")
    except Exception as e:
        print(f"warning: cloudflare challenge did not resolve - {e}")

    # wait for product list to actually load
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".product-list .dv-item")))
    except Exception as e:
        print(f"warning: timed out waiting for products - {e}")

    html = driver.execute_script("return document.documentElement.outerHTML")
    return html


# scape a single page with counter tracking
def scrape_page(url, store, store_dict, view, section, counter, session_scraped_ids):
    print("scraping: juno ", url, flush=True)

    # spin up a driver for the session with retry logic
    attempts = 0
    while True:
        try:
            options = uc.ChromeOptions()
            # note: headless mode gets blocked by cloudflare turnstile
            driver = uc.Chrome(options=options, headless=False)
            html_str = execute_page(url, driver)
            break
        except (InvalidSessionIdException, WebDriverException, ReadTimeoutError) as e:
            attempts += 1
            if attempts > 5:
                print(f"error: failed after {attempts} attempts - {e}")
                return -1
            print(f"Failed with exception, retrying after {attempts} attempts")
            dig.scrape_yield()

    # store release entries in dict
    releases_dict = dict()

    # gets products
    products = dig.parse_div(html_str, 'class="product-list"')

    if len(products) == 0:
        driver.quit()
        return -1

    # separate into items
    releases = dig.parse_div(products[0], 'class="dv-item"')

    # open existing reg
    releases_dict = dig.load_registry(store)

    for release in releases:
        # basic info
        (_, id_elem) = dig.find_parse_elem(release, 0, "<div id=", ">")
        release_dict = dict()
        store_tags = dict()
        release_dict["store"] = f"{store}"
        release_dict["id"] = parse_id(id_elem)

        # chart pos
        if view in ["weekly_chart", "monthly_chart"]:
            # chart pos are listed
            pos = dig.parse_nested_body(release, 4).strip()
            store_tags["has_charted"] = True
        else:
            # latest pos is manually tracked
            pos = counter

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

        (_, link_elem) = dig.find_parse_elem(release, 0, "<a href=", ">")
        (_, artwork_elem) = dig.find_parse_elem(release, 0, "<img class", ">")

        # handle VA case
        if release.find("<strong>VARIOUS</strong>") != -1:
            artist_elem = "<strong>VARIOUS"
            offset = 0
        else:
            (offset, artist_elem) = dig.find_parse_elem(release, 0, '<a class="text-md"', "</a>")

        (offset, title_elem) = dig.find_parse_elem(release, offset, '<a class="text-md"', "</a>")
        (offset, label_elem) = dig.find_parse_elem(release, offset, '<a class="text-md"', "</a>")
        (offset, cat_elem) = dig.find_parse_elem(release, offset, '<div class="vi-text', "<br class")

        # tracks
        tracks = dig.parse_div(release, 'class="listing-track')

        # sold out
        if release.find(">out of stock<") != -1:
            store_tags["out_of_stock"] = True
            store_tags["has_sold_out"] = True
        else:
            store_tags["out_of_stock"] = False

        # TODO: preorder

        # extract values from the html sections
        release_dict["link"] = parse_link(link_elem)
        release_dict["artist"] = dig.parse_body(artist_elem)

        release_dict["title"] = dig.parse_body(title_elem)
        if release_dict["title"].find("<span") != -1:
            print(release)
            assert(0)

        release_dict["label"] = parse_label(label_elem)
        release_dict["cat"] = parse_cat(cat_elem)
        release_dict["artworks"] = parse_artworks(artwork_elem)
        release_dict["store_tags"] = store_tags
        (release_dict["track_names"], release_dict["track_urls"]) = parse_tracks(tracks)

        # assign pos per section
        release_dict[f"{store}-{section}-{view}"] = int(pos)

        # increment counter to track indices
        counter += 1

        # genre tags are just loose in the object so they can be queried
        tags_span = dig.parse_class(release, 'class="juno-tags-tag"', "span")
        for tag_span in tags_span:
            tag_str = dig.parse_nested_body(tag_span, 2).strip()
            tag_str = dig.firebase_compliant_key(tag_str)
            release_dict[tag_str] = "genre_tag"

        # merge into main
        merge = dict()
        merge[key] = release_dict
        dig.merge_dicts(releases_dict, merge)

        # mark as done this session
        session_scraped_ids.append(key)

    # write to file
    dig.write_registry(store, releases_dict)

    driver.quit()
    dig.scrape_yield()
    return counter