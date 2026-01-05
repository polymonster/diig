import dig
import os
import json
import time
import sys
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import InvalidSessionIdException
from selenium.common.exceptions import WebDriverException


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


# fetch html execuing script
def get_json(driver, url, api_url, id, offset):
    driver.get(url)

    wait = WebDriverWait(driver, 60)
    wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
    driver.execute_script("return document.documentElement.outerHTML")

    # Extract cookies from Selenium
    cookies = driver.get_cookies()
    session = requests.Session()
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])

    # Prepare headers and payload
    payload = {
        "id": id,
        "href": url,
        "offset": str(offset)
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": url,
        "Origin": "https://www.phonicarecords.com",
        "User-Agent": driver.execute_script("return navigator.userAgent;")
    }

    # Make the request using the same session
    response = session.post(api_url, data=payload, headers=headers)
    j = json.loads(response.text)

    return j


# scrape an individual page for a view (essentials, new releases)
def scrape_page(url, store, store_dict, view, section, counter, session_scraped_ids):
    # replace category id
    category_id = "0"
    if "category_id" in store_dict:
        if section in store_dict["category_id"]:
            category_id = store_dict["category_id"][section]
        elif view in store_dict["category_id"]:
            category_id = store_dict["category_id"][view]

    url = url.replace("${{category_id}}", category_id)

    print(f"scraping phonica: {section} {url}")

    # grab registry
    releases_dict = dict()
    reg_filepath = f"registry/{store}.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())

    # spin up a driver for the session
    attempts = 0
    while True:
        try:
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')
            driver = webdriver.Chrome(options)
            driver.minimize_window()

            pos = counter
            api_url = store_dict["views"][view]["api_url"]
            products = get_json(driver, url, api_url, category_id, pos)
            break
        except (InvalidSessionIdException, WebDriverException):
            attempts += 1
            if attempts > 5:
                raise
            print(f"Failed to get_json with exception. retrying after {attempts} attempts")
            dig.scrape_yield()

    store_url = "https://www.phonicarecords.com"
    for (key, product) in products.items():
        # phonica dict is not pure releases, we only care about digits
        if not key.isdigit():
            continue

        # progress log
        id = f"{store}-" + product["id_web"]
        if "-verbose" in sys.argv:
            print(f"parsing: {id}")

        # asign tracker
        release = dict()
        release[f"{store}-{section}-{view}"] = int(pos)

        # skip already processed
        if id in session_scraped_ids:
            if id in releases_dict:
                merge = dict()
                merge[id] = release
                dig.merge_dicts(releases_dict, merge)
            continue

        # asign info
        slug = product.get("slug", "")
        release["store"] = store
        release["id"] = id
        release["label_link"] = ""
        release["cat"] = ""
        release["title"] = product.get("album", "")
        release["link"] = f"{store_url}/{slug}"
        release["artist"] = product.get("artist", "")
        release["label"] = product.get("label", "")

        # audio / tracknames
        if "-urls" in sys.argv:
            cdn = "https://dmpqep8cljqhc.cloudfront.net/"
            release["track_names"] = list()
            release["track_urls"] = list()
            if "product_playlist" in product:
                for track in product["product_playlist"]:
                    if "trackname" in track:
                        release["track_names"].append(track["trackname"])
                    if "filename" in track:
                        fn = track["filename"]
                        release["track_urls"].append(f"{cdn}{fn}")
            # artworks
            if "cover" in product:
                audio_cdn = "https://d1c4rk9le5opln.cloudfront.net/"
                cover = product["cover"]
                release["artworks"] = [
                    f"{audio_cdn}{cover}",
                    f"{audio_cdn}{cover}",
                    f"{audio_cdn}{cover}",
                ]

        # stock tracker
        release["store_tags"] = {
            "out_of_stock": product.get("has_stock", "0") == "0",
            "preorder": product.get("is_preorder", "0") == "1"
        }

        # merge
        if id in releases_dict:
            merge = dict()
            merge[id] = release
            dig.merge_dicts(releases_dict, merge)
        else:
            releases_dict[release["id"]] = release

        session_scraped_ids.append(release["id"])
        pos += 1

    # write to file
    release_registry = (json.dumps(releases_dict, indent=4))
    open(reg_filepath, "w+").write(release_registry)

    driver.quit()
    dig.scrape_yield()
    return counter + 18
