import urllib.request
import cgu
import json
import sys
import os
import datetime
import dig
import html


# parse id from id="record-{id}" in article
def parse_id(article: str):
    pos = article.find('id="record-')
    if pos == -1:
        return None
    # extract the ID number after "record-"
    start = pos + len('id="record-')
    end = article.find('"', start)
    if end == -1:
        return None
    return article[start:end]


# parse release link from first <a href="/{id}/.../">
def parse_link(article: str):
    # find href to release page (format: /{id}/{slug}/)
    (_, link_elem) = dig.find_parse_elem(article, 0, '<a href="/', '"')
    if link_elem:
        href = dig.get_value(link_elem, "href")
        if href:
            return "https://hardwax.com" + href
    return None


# parse artist from <a class="rn" title="{artist}">
def parse_artist(article: str):
    pos = article.find('class="rn"')
    if pos == -1:
        return ""
    (_, artist_elem) = dig.find_parse_elem(article, pos, '<a class="rn"', '</a>')
    if artist_elem:
        # get title attribute which has clean artist name
        title = dig.get_value(artist_elem, "title")
        if title:
            return html.unescape(title)
        # fallback to body text (remove trailing colon)
        body = dig.parse_body(artist_elem).strip()
        if body.endswith(":"):
            body = body[:-1]
        return html.unescape(body)
    return ""


# parse title from <span class="rp">{title}</span>
def parse_title(article: str):
    pos = article.find('class="rp"')
    if pos == -1:
        return ""
    # find end of span tag
    tag_end = article.find(">", pos)
    if tag_end == -1:
        return ""
    # find closing span
    span_end = article.find("</span>", tag_end)
    if span_end == -1:
        return ""
    # extract body between > and </span>
    body = article[tag_end + 1:span_end]
    return html.unescape(body)


# parse label and catalogue from <div class="qv">
def parse_label_cat(article: str):
    pos = article.find('class="qv"')
    if pos == -1:
        return ("", "")

    # find the qv div containing label and catalogue
    (end, qv_div) = dig.find_parse_elem(article, pos, '<div class="qv"', '</div>')

    # label is first <a> with title attribute
    label = ""
    cat = ""

    # find all <a> tags in qv_div
    a_tags = []
    search_pos = 0
    while True:
        a_start = qv_div.find("<a ", search_pos)
        if a_start == -1:
            break
        a_end = qv_div.find("</a>", a_start)
        if a_end == -1:
            break
        a_tags.append(qv_div[a_start:a_end + 4])
        search_pos = a_end + 4

    # first <a> with title is label
    for a_tag in a_tags:
        title = dig.get_value(a_tag, "title")
        if title:
            label = html.unescape(title)
            break

    # second <a> in qv contains catalogue number (body text)
    if len(a_tags) >= 2:
        cat = dig.parse_body(a_tags[1]).replace("</a>", "").strip()
        cat = html.unescape(cat)

    return (label, cat)


# parse artworks from <img class="aj" src="...">
def parse_artworks(article: str, release_id: str):
    artworks = []

    # find all img tags with class="aj"
    search_pos = 0
    while True:
        pos = article.find('class="aj"', search_pos)
        if pos == -1:
            break

        # find the img tag start
        img_start = article[:pos].rfind("<img ")
        if img_start == -1:
            search_pos = pos + 10
            continue

        img_end = article.find(">", pos)
        img_tag = article[img_start:img_end + 1]

        src = dig.get_value(img_tag, "src")
        if src and src.startswith("https://media.hardwax.com/images/"):
            if src not in artworks:
                artworks.append(src)

        search_pos = pos + 10

    # construct small, medium, large from first artwork
    if artworks:
        first = artworks[0]
        # small is the base URL (e.g., 87718a.jpg)
        small = first
        # large/medium uses 'abig' suffix
        large = first.replace(".jpg", "big.jpg")
        return [small, large, large]

    # fallback: construct from ID
    base = f"https://media.hardwax.com/images/{release_id}"
    return [f"{base}a.jpg", f"{base}abig.jpg", f"{base}abig.jpg"]


# parse tracks from <ul class="sc"> containing <li class="rq">
def parse_tracks(article: str):
    track_names = []
    track_urls = []

    # find all track list items
    search_pos = 0
    while True:
        pos = article.find('class="rq"', search_pos)
        if pos == -1:
            break

        # find the li tag
        li_start = article[:pos].rfind("<li ")
        if li_start == -1:
            search_pos = pos + 10
            continue

        li_end = article.find("</li>", pos)
        if li_end == -1:
            search_pos = pos + 10
            continue

        li_tag = article[li_start:li_end + 5]

        # find <a class="sa" href="...mp3"> for audio URL
        a_pos = li_tag.find('class="sa"')
        if a_pos != -1:
            a_start = li_tag[:a_pos].rfind("<a ")
            a_end = li_tag.find("</a>", a_pos)
            if a_start != -1 and a_end != -1:
                a_tag = li_tag[a_start:a_end + 4]

                # get audio URL
                href = dig.get_value(a_tag, "href")
                if href and href.endswith(".mp3"):
                    track_urls.append(href)

                # get track name from title attribute (cleaner)
                title = dig.get_value(a_tag, "title")
                if title:
                    # title is "Artist: Track Name" - extract just track part
                    if ": " in title:
                        track_name = title.split(": ", 1)[1]
                    else:
                        track_name = title
                    track_names.append(html.unescape(track_name))

        search_pos = pos + 10

    return (track_names, track_urls)


# scrape a single page with counter tracking
def scrape_page(url, store, store_dict, view, section, counter, session_scraped_ids):
    print("scraping: hardwax ", url, flush=True)

    # try and then continue if the page does not exist
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://hardwax.com/",
        }
        req = urllib.request.Request(
            url=url,
            headers=headers
        )
        html_file = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        print("error:", e.code, e.reason)
        return -1

    html_str = html_file.read().decode("utf8")

    # store release entries in dict
    releases_dict = dict()

    # parse articles containing releases
    articles = dig.parse_class(html_str, 'class="co cq px"', "article")

    if len(articles) == 0:
        return -1

    # open existing reg
    releases_dict = dig.load_registry(store)

    for article in articles:
        release_dict = dict()
        store_tags = dict()

        # get release ID from record-{id} attribute
        release_id = parse_id(article)

        if not release_id:
            continue

        release_dict["store"] = f"{store}"
        release_dict["id"] = release_id

        # early out for already processed ids during this session
        key = f"{store}-{release_id}"
        if key in session_scraped_ids:
            if "-verbose" in sys.argv:
                print(f"skipping duplicate: {key}", flush=True)
            continue
        elif "-verbose" in sys.argv:
            print(f"parsing release: {key}", flush=True)

        # parse release fields
        release_dict["link"] = parse_link(article)
        release_dict["artist"] = parse_artist(article)
        release_dict["title"] = parse_title(article)
        (label, cat) = parse_label_cat(article)
        release_dict["label"] = label
        release_dict["cat"] = cat
        release_dict["artworks"] = parse_artworks(article, release_id)
        (track_names, track_urls) = parse_tracks(article)
        release_dict["track_names"] = track_names
        release_dict["track_urls"] = track_urls

        # stock status - hardwax shows availability differently
        # check for "out of stock" or similar indicators
        if article.find("out of stock") != -1 or article.find("sold out") != -1:
            store_tags["out_of_stock"] = True
            store_tags["has_sold_out"] = True
        else:
            store_tags["out_of_stock"] = False

        store_tags["has_charted"] = False
        store_tags["preorder"] = False

        release_dict["store_tags"] = store_tags

        # assign position per section/view
        release_dict[f"{store}-{section}-{view}"] = int(counter)
        counter += 1

        # merge into main
        merge = dict()
        merge[key] = release_dict
        dig.merge_dicts(releases_dict, merge)

        # mark as done this session
        session_scraped_ids.append(key)

    # write to file
    dig.write_registry(store, releases_dict)

    dig.scrape_yield()
    return counter
