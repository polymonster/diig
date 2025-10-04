import dig
import os
import json

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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

# scrape detail info for a single product,obtaining mp3 links and image links
def scrape_product(release):
    product_html = cache_page("https://www.phonicarecords.com/product/doc-n-p1ll-rx-prescriptions-volume-2-serenity-now/205828/", "phonica_product.html")

    offset = 0
    (offset, playlist_elems)= dig.find_parse_nested_elems(product_html, offset, '<span class="archive-playlist display-none">', "<span", "</span>")

    offset = 0
    track_names = list()
    track_urls = list()
    while True:
        (offset, track_elem) = dig.find_parse_nested_elems(playlist_elems, offset, '<span id=', '<span id=', "</span>")
        if track_elem.find("<span id=") != -1:
            name = dig.parse_body(track_elem).strip()
            end = name.find("</span>")
            track_names.append(name[:end])
            track_urls.append(dig.get_value(track_elem, "id").strip())
        else:
            break

    release["track_names"] = track_names
    release["track_urls"] = track_urls


# scrape an individual page for a view (essentials, new releases)
def scrape_page(url, store, view, section, counter, session_scraped_ids):
    print(f"scraping phonica: {section} {url}")

    porducts_html = cache_page("https://www.phonicarecords.com/essentials/6/all", "phonica_products.html")

    releases = dict()

    # TODO:
    # id
    # label_link
    # cat
    # artworks
    # store_tags

    product_group = dig.parse_div(porducts_html, 'id="archive-grid-view-home-category-6"')
    for group in product_group:
        place_holders = dig.parse_div(group, 'class="product-place-holder')
        for p in place_holders:
            offset = 0
            (offset, image_elem) = dig.find_parse_elem(p, offset, '<a id=', "</a>")
            (offset, artist_elem) = dig.find_parse_elem(p, offset, '<a id=', "</a>")
            (offset, product_link_elem) = dig.find_parse_elem(p, offset, '<a id=', "</a>")
            (offset, label_elem) = dig.find_parse_elem(p, offset, '<a id=', "</a>")

            offset = 0
            (offset, title_elem) = dig.find_parse_elem(product_link_elem, offset, '<span class', "</span>")

            release = dict()
            release["store"] = "phonica"
            release["title"] = dig.parse_body(title_elem).strip()
            release["link"] = dig.get_value(product_link_elem, "href").strip()
            release["artist"] = dig.parse_body(artist_elem).strip()
            release["label"] = dig.parse_body(label_elem).strip()

            scrape_product(release)

            print(json.dumps(release, indent=4))




