import json
import sys
import html
import dig


def parse_tracks(description_html):
    # description_html is decoded HTML from the product JSON block, e.g.:
    # <p><a href="https://cdn.shopify.com/.../track.mp3">Track Name</a></p>
    track_names = []
    track_urls = []
    pos = 0
    while True:
        mp3_pos = description_html.find('.mp3"', pos)
        if mp3_pos == -1:
            mp3_pos = description_html.find('.mp3\'', pos)
        if mp3_pos == -1:
            break
        a_start = description_html.rfind('<a ', 0, mp3_pos)
        if a_start == -1:
            pos = mp3_pos + 5
            continue
        a_end = description_html.find('</a>', a_start)
        if a_end == -1:
            pos = mp3_pos + 5
            continue
        a_tag = description_html[a_start:a_end + 4]
        href = dig.get_value(a_tag, 'href')
        if href and href.endswith('.mp3'):
            name = dig.parse_strip_body(a_tag).strip()
            track_urls.append(href)
            track_names.append(html.unescape(name).strip("<span>"))
        pos = a_end + 4
    return track_names, track_urls


def parse_description_from_page(page_html):
    # tracks live inside a <script type="application/json" data-product-json> block.
    # the description field contains HTML-encoded anchor tags pointing to mp3 files.
    # json.loads() decodes the unicode escapes (< -> <) automatically.
    marker = '<script type="application/json" data-product-json>'
    start = page_html.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = page_html.find('</script>', start)
    if end == -1:
        return ""
    try:
        data = json.loads(page_html[start:end])
        return data.get("description", "") or data.get("body_html", "")
    except Exception:
        return ""


def scrape_page(url, store, store_dict, view, section, counter, session_scraped_ids):
    print(f"scraping vinylunderground: {section} {url}", flush=True)

    response = dig.request_url_limited(url)
    if response is None:
        return -1

    try:
        data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"error parsing json: {e}")
        return -1

    products = data.get("products", [])
    if not products:
        return -1

    releases_dict = dig.load_registry(store)

    for product in products:
        release_id = str(product["id"])
        key = f"{store}-{release_id}"

        # update tracker only
        if key in session_scraped_ids:
            if key in releases_dict:
                releases_dict[key][f"{store}-{section}-{view}"] = counter
            counter += 1
            continue

        # update stock info only
        if key in releases_dict:
            releases_dict[key][f"{store}-{section}-{view}"] = counter
            variants = product.get("variants", [])
            out_of_stock = not variants[0].get("available", False) if variants else True
            product_type = product.get("product_type", "")
            releases_dict[key]["store_tags"]["out_of_stock"] = out_of_stock
            releases_dict[key]["store_tags"]["preorder"] = product_type.lower() in ["inbound", "presale"]
            session_scraped_ids.append(key)
            counter += 1
            continue

        # full update
        if "-verbose" in sys.argv:
            print(f"parsing: {key}", flush=True)

        raw_title = product.get("title", "")
        if " / " in raw_title:
            artist, title = raw_title.split(" / ", 1)
        elif " | " in raw_title:
            artist, title = raw_title.split(" | ", 1)
        else:
            artist, title = "", raw_title

        variants = product.get("variants", [])
        cat = variants[0].get("sku", "") if variants else ""
        out_of_stock = not variants[0].get("available", False) if variants else True

        images = product.get("images", [])
        artworks = [images[0]["src"]] * 3 if images else []

        product_type = product.get("product_type", "")
        preorder = product_type.lower() in ["inbound", "presale"]

        release = {
            "store": store,
            "id": release_id,
            "link": f"https://vinylunderground.co.uk/products/{product['handle']}",
            "artist": artist.strip(),
            "title": title.strip(),
            "label": product.get("vendor", ""),
            "label_link": "",
            "cat": cat,
            "artworks": artworks,
            "track_names": [],
            "track_urls": [],
            "store_tags": {
                "out_of_stock": out_of_stock,
                "preorder": preorder,
                "has_sold_out": False,
                "has_charted": False,
            },
            f"{store}-{section}-{view}": counter,
        }

        if "-urls" in sys.argv:
            handle = product.get("handle", "")
            detail_url = f"https://vinylunderground.co.uk/products/{handle}"
            detail_response = dig.request_url_limited(detail_url)
            if detail_response:
                page_html = detail_response.read().decode("utf-8")
                description_html = parse_description_from_page(page_html)
                if description_html:
                    track_names, track_urls = parse_tracks(description_html)
                    release["track_names"] = track_names
                    release["track_urls"] = track_urls

        dig.merge_dicts(releases_dict, {key: release})
        session_scraped_ids.append(key)
        counter += 1

    dig.write_registry(store, releases_dict)
    return counter
