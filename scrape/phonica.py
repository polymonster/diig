import dig
import os
import json
import time
import sys

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# fetch htl from a cached file if present or spin up a driver and execute the script if not
def cache_page(url, cache_file):
    if not os.path.exists(cache_file):
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        driver = webdriver.Chrome(options)
        driver.get(url)
        html = driver.execute_script("return document.documentElement.outerHTML")
        driver.minimize_window()
        open(cache_file, "w", encoding='utf-8').write(html)
        driver.quit()
        return html
    else:
        return open(cache_file, "r").read()


# fetch html execuing script
def execute_page(url, driver):
    driver.get(url)
    wait = WebDriverWait(driver, 60)
    wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
    html = driver.execute_script("return document.documentElement.outerHTML")
    return html


# scrape detail info for a single product,obtaining mp3 links and image links
def scrape_product(release, url, driver):

    product_html = execute_page(url, driver)

    # find track names and urls
    offset = 0
    (offset, playlist_elems)= dig.find_parse_nested_elems(product_html, offset, '<span class="archive-playlist display-none">', "<span", "</span>")

    cdn = "https://dmpqep8cljqhc.cloudfront.net/"

    offset = 0
    track_names = list()
    track_urls = list()
    while True:
        (offset, track_elem) = dig.find_parse_nested_elems(playlist_elems, offset, '<span id=', '<span id=', "</span>")
        if track_elem.find("<span id=") != -1:
            name = dig.parse_body(track_elem).strip()
            end = name.find("</span>")
            track_names.append(name[:end])
            track_urls.append(cdn + dig.get_value(track_elem, "id").strip())
        else:
            break

    release["track_names"] = track_names
    release["track_urls"] = track_urls

    # find artwork
    offset = 0
    (offset, artwork_elems)= dig.find_parse_nested_elems(product_html, offset, '<meta property="og:image"', "<meta", "</meta>")

    release["artworks"] = [
        dig.get_value(artwork_elems, "content"),
        dig.get_value(artwork_elems, "content"),
        dig.get_value(artwork_elems, "content"),
    ]

    dig.scrape_yield()


# scrape an individual page for a view (essentials, new releases)
def scrape_page(url, store, view, section, counter, session_scraped_ids):
    print(f"scraping phonica: {section} {url}")

    # spin up a driver for the session
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    driver = webdriver.Chrome(options)
    driver.minimize_window()

    # grab registry
    releases_dict = dict()
    reg_filepath = f"registry/{store}.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())

    pos = counter
    porducts_html = execute_page(url, driver)
    product_group = dig.parse_div(porducts_html, 'id="archive-grid-view"')
    for group in product_group:
        place_holders = dig.parse_div(group, 'class="product-place-holder')
        for p in place_holders:
            offset = 0
            (offset, image_elem) = dig.find_parse_elem(p, offset, '<a id=', "</a>")

            # progress log
            id = f"{store}-" + dig.get_value(image_elem, "id")

            if "-verbose" in sys.argv:
                print(f"parsing: {id}")

            if id in session_scraped_ids:
                continue

            (offset, artist_elem) = dig.find_parse_elem(p, offset, '<a id=', "</a>")
            (offset, product_link_elem) = dig.find_parse_elem(p, offset, '<a id=', "</a>")
            (offset, label_elem) = dig.find_parse_elem(p, offset, '<a id=', "</a>")
            (offset, stock_elem) = dig.find_parse_elem(p, offset, '<i id="stock-indicator', "</a>")

            offset = 0
            (offset, title_elem) = dig.find_parse_elem(product_link_elem, offset, '<span class', "</span>")

            release = dict()
            release["store"] = store
            release["id"] = id
            release["title"] = dig.parse_body(title_elem).strip()
            release["link"] = dig.get_value(product_link_elem, "href").strip()
            release["artist"] = dig.parse_body(artist_elem).strip()
            release["label"] = dig.parse_body(label_elem).strip()
            release["label_link"] = dig.get_value(label_elem, "href").strip()
            release["cat"] = ""

            release[f"{store}-{section}-{view}"] = int(pos)

            release["store_tags"] = {
                "out_of_stock": stock_elem.find("circle-shape-red") != -1,
                "preorder": stock_elem.find("circle-shape-blue") != -1
            }

            # merge or scrape deeper
            if id in releases_dict:
                merge = dict()
                merge[id] = release
                dig.merge_dicts(releases_dict, merge)
            else:
                link = release["link"]
                if "-verbose" in sys.argv:
                    print(f"scrape product page: {link}")
                if "-urls" in sys.argv:
                    scrape_product(release, link, driver)
                releases_dict[release["id"]] = release

            session_scraped_ids.append(release["id"])
            pos += 1

    # write to file
    release_registry = (json.dumps(releases_dict, indent=4))
    open(reg_filepath, "w+").write(release_registry)

    dig.scrape_yield()
    return counter + 18



