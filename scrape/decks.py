import urllib.request
import json
import sys
import html
import dig


# fetch MP3 URLs from Audio API
# returns (track_urls, track_names) or ([], []) on failure
def fetch_audio_urls(code: str):
    api_url = f"https://www.decks.de/decks/rpc/getAudio.php?id={code}"
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": "https://www.decks.de/",
        }
        req = urllib.request.Request(url=api_url, headers=headers)
        response = urllib.request.urlopen(req)
        data = json.loads(response.read().decode("utf-8"))
        return (data.get("sound", []), data.get("track", []))
    except Exception as e:
        if "-verbose" in sys.argv:
            print(f"audio API error for {code}: {e}", flush=True)
        return ([], [])


# parse release code from findTrack.php?code=XXX link
def parse_id(release_html: str):
    pos = release_html.find('findTrack.php?code=')
    if pos == -1:
        return None
    start = pos + len('findTrack.php?code=')
    end = release_html.find('"', start)
    if end == -1:
        end = release_html.find("'", start)
    if end == -1:
        return None
    return release_html[start:end]


# parse release link from href to track page
def parse_link(release_html: str, code: str):
    # look for full track URL like https://www.decks.de/track/artist-title/code
    marker = 'href="https://www.decks.de/track/'
    pos = release_html.find(marker)
    if pos != -1:
        start = pos + len('href="')
        end = release_html.find('"', start)
        if end != -1:
            return release_html[start:end]
    # also try relative URL format
    marker2 = f'/decks/workfloor/lists/findTrack.php?code={code}'
    if marker2 in release_html:
        return f"https://www.decks.de{marker2}"
    # fallback: construct from code
    return f"https://www.decks.de/track/{code}"


# parse artist from LArtist div
def parse_artist(release_html: str):
    pos = release_html.find('class="LArtist')
    if pos == -1:
        return ""
    # find the <a> inside
    a_start = release_html.find('<a', pos)
    if a_start == -1 or a_start > pos + 200:
        return ""
    # find closing tag
    a_end = release_html.find('</a>', a_start)
    if a_end == -1:
        return ""
    # extract body text (after >)
    body_start = release_html.find('>', a_start)
    if body_start == -1 or body_start > a_end:
        return ""
    artist = release_html[body_start + 1:a_end]
    return html.unescape(artist.strip())


# parse title from LTitel div
def parse_title(release_html: str):
    pos = release_html.find('class="LTitel')
    if pos == -1:
        return ""
    # find the start of div
    div_start = release_html.find('>', pos)
    if div_start == -1:
        return ""
    # find closing tag or next element
    div_end = release_html.find('</div>', div_start)
    if div_end == -1:
        return ""
    title_html = release_html[div_start + 1:div_end]
    # remove any span with format info
    span_pos = title_html.find('<span')
    if span_pos != -1:
        title_html = title_html[:span_pos]
    return html.unescape(title_html.strip())


# parse label name from LLabel div (not LLabelcat)
def parse_label(release_html: str):
    # search for LLabel followed by space (to avoid matching LLabelcat)
    pos = release_html.find('class="LLabel ')
    if pos == -1:
        pos = release_html.find('class="LLabel"')
    if pos == -1:
        return ""
    div_start = release_html.find('>', pos)
    if div_start == -1:
        return ""
    div_end = release_html.find('</div>', div_start)
    if div_end == -1:
        return ""
    label = release_html[div_start + 1:div_end]
    return html.unescape(label.strip())


# parse catalog number from LLabelcat div
def parse_cat(release_html: str):
    pos = release_html.find('class="LLabelcat')
    if pos == -1:
        return ""
    div_start = release_html.find('>', pos)
    if div_start == -1:
        return ""
    div_end = release_html.find('</div>', div_start)
    if div_end == -1:
        return ""
    cat = release_html[div_start + 1:div_end]
    return html.unescape(cat.strip())


# parse artworks from image URLs - construct small, medium, large
def parse_artworks(release_html: str, code: str):
    # extract last character for end_X folder
    end_char = code[-1] if code else 'x'

    # base URL pattern
    base = f"https://gfx67.decks.de/decks/gfx"

    # small (co_mid is the medium size they use)
    small = f"{base}/co_mid/front/end_{end_char}/{code}.jpg"
    # medium - same as small for now (they don't have explicit medium)
    medium = small
    # large - try co_large or use co_mid
    large = f"{base}/co_large/front/end_{end_char}/{code}.jpg"

    return [small, medium, large]


# parse tracks from SoundList div
def parse_tracks(release_html: str):
    track_names = []
    track_urls = []

    # find the SoundList section
    sound_pos = release_html.find('class="SoundList')
    if sound_pos == -1:
        return (track_names, track_urls)

    # find end of SoundList
    sound_end = release_html.find('</div>\n<div class="scroll-div">', sound_pos)
    if sound_end == -1:
        sound_end = len(release_html)

    sound_section = release_html[sound_pos:sound_end]

    # parse each OneListen div
    search_pos = 0
    while True:
        listen_pos = sound_section.find('class="OneListen"', search_pos)
        if listen_pos == -1:
            break

        # find end of this listen block
        next_listen = sound_section.find('class="OneListen"', listen_pos + 20)
        if next_listen == -1:
            listen_block = sound_section[listen_pos:]
        else:
            listen_block = sound_section[listen_pos:next_listen]

        # extract track name from TrackNametxt span
        name_pos = listen_block.find('class="TrackNametxt"')
        if name_pos != -1:
            name_start = listen_block.find('>', name_pos)
            name_end = listen_block.find('</span>', name_start)
            if name_start != -1 and name_end != -1:
                track_name = listen_block[name_start + 1:name_end]
                track_names.append(html.unescape(track_name.strip()))

        # extract play URL
        url_pos = listen_block.find('href="https://www.decks.de/play/')
        if url_pos != -1:
            url_start = url_pos + len('href="')
            url_end = listen_block.find('"', url_start)
            if url_end != -1:
                track_urls.append(listen_block[url_start:url_end])

        search_pos = listen_pos + 20

    return (track_names, track_urls)


# parse stock status from stockBlocktxt div
def parse_stock_status(release_html: str):
    out_of_stock = False
    preorder = False

    # look for stockBlocktxt
    pos = release_html.find('class="stockBlocktxt')
    if pos != -1:
        div_start = release_html.find('>', pos)
        div_end = release_html.find('</div>', div_start)
        if div_start != -1 and div_end != -1:
            status = release_html[div_start + 1:div_end].lower().strip()
            if 'out of stock' in status or 'sold out' in status:
                out_of_stock = True
            if 'presale' in status or 'preorder' in status:
                preorder = True

    # also check for RecOutOfStock class
    if release_html.find('RecOutOfStock') != -1:
        out_of_stock = True

    return (out_of_stock, preorder)


# parse chart position from nowChartsPos div (for chart views)
def parse_chart_position(release_html: str):
    pos = release_html.find('class="nowChartsPos"')
    if pos == -1:
        return None
    div_start = release_html.find('>', pos)
    div_end = release_html.find('</div>', div_start)
    if div_start != -1 and div_end != -1:
        try:
            return int(release_html[div_start + 1:div_end].strip())
        except ValueError:
            return None
    return None


# parse genre tags from StyleBox div
def parse_genre_tags(release_html: str):
    tags = []
    pos = release_html.find('class="StyleBox')
    if pos == -1:
        return tags

    # find end of StyleBox
    box_end = release_html.find('</div>\n', pos + 100)
    if box_end == -1:
        box_end = pos + 500

    style_section = release_html[pos:box_end]

    # find all LStyle divs
    search_pos = 0
    while True:
        style_pos = style_section.find('class="LStyle"', search_pos)
        if style_pos == -1:
            break

        # find the <a> inside
        a_end = style_section.find('</a>', style_pos)
        if a_end != -1:
            # find the body text
            body_start = style_section.rfind('>', style_pos, a_end)
            if body_start != -1:
                tag = style_section[body_start + 1:a_end].strip()
                if tag and tag not in tags:
                    tags.append(html.unescape(tag))

        search_pos = style_pos + 15

    return tags


# split HTML into individual release blocks
def split_releases(html_str: str):
    releases = []

    # releases are separated by findTrack.php?code= links
    search_pos = 0
    while True:
        start = html_str.find('findTrack.php?code=', search_pos)
        if start == -1:
            break

        # find the next release or end
        next_release = html_str.find('findTrack.php?code=', start + 20)
        if next_release == -1:
            release_block = html_str[start:]
        else:
            release_block = html_str[start:next_release]

        # only include if it has actual release data (artist, title)
        if 'class="LArtist' in release_block or 'class="LTitel' in release_block:
            releases.append(release_block)

        search_pos = start + 20

    return releases


# scrape a single page with counter tracking
def scrape_page(url, store, store_dict, view, section, counter, session_scraped_ids):
    print(f"scraping: decks {url}", flush=True)

    # make HTTP request
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.decks.de/",
        }
        req = urllib.request.Request(url=url, headers=headers)
        html_file = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        print(f"error: {e.code} {e.reason}")
        return -1

    html_str = html_file.read().decode("iso-8859-1")

    # load existing registry
    releases_dict = dig.load_registry(store)

    # split into release blocks
    releases = split_releases(html_str)

    if len(releases) == 0:
        return -1

    is_chart = view in ["buzz_chart", "sales_chart"]

    for release_html in releases:
        release_dict = dict()
        store_tags = dict()

        # parse release ID (code)
        release_id = parse_id(release_html)
        if not release_id:
            continue

        release_dict["store"] = store
        release_dict["id"] = release_id

        # early out for already processed ids
        key = f"{store}-{release_id}"
        if key in session_scraped_ids:
            if "-verbose" in sys.argv:
                print(f"skipping duplicate: {key}", flush=True)
            continue
        elif "-verbose" in sys.argv:
            print(f"parsing release: {key}", flush=True)

        # parse release fields
        release_dict["link"] = parse_link(release_html, release_id)
        release_dict["artist"] = parse_artist(release_html)
        release_dict["title"] = parse_title(release_html)
        release_dict["label"] = parse_label(release_html)
        release_dict["cat"] = parse_cat(release_html)
        release_dict["artworks"] = parse_artworks(release_html, release_id)

        # check if we already have MP3 URLs in registry (skip API call if so)
        existing = releases_dict.get(key, {})
        existing_urls = existing.get("track_urls", [])
        if existing_urls and len(existing_urls) > 0 and not existing_urls[0].startswith("https://www.decks.de/play/"):
            # already have real MP3 URLs, reuse them
            track_urls = existing_urls
            track_names = existing.get("track_names", [])
            if "-verbose" in sys.argv:
                print(f"  reusing {len(track_urls)} cached MP3 URLs", flush=True)
        else:
            # fetch from Audio API
            (track_urls, track_names) = fetch_audio_urls(release_id)
            if "-verbose" in sys.argv:
                print(f"  fetched {len(track_urls)} MP3 URLs from API", flush=True)

        release_dict["track_names"] = track_names
        release_dict["track_urls"] = track_urls

        # stock status
        (out_of_stock, preorder) = parse_stock_status(release_html)
        store_tags["out_of_stock"] = out_of_stock
        store_tags["has_sold_out"] = out_of_stock
        store_tags["preorder"] = preorder

        # chart position
        if is_chart:
            chart_pos = parse_chart_position(release_html)
            if chart_pos is not None:
                store_tags["has_charted"] = True
                release_dict[f"{store}-{section}-{view}"] = chart_pos
            else:
                store_tags["has_charted"] = True
                release_dict[f"{store}-{section}-{view}"] = counter
                counter += 1
        else:
            store_tags["has_charted"] = False
            release_dict[f"{store}-{section}-{view}"] = counter
            counter += 1

        release_dict["store_tags"] = store_tags

        # genre tags
        genre_tags = parse_genre_tags(release_html)
        for tag in genre_tags:
            tag_key = dig.firebase_compliant_key(tag)
            release_dict[tag_key] = "genre_tag"

        # merge into main registry
        merge = dict()
        merge[key] = release_dict
        dig.merge_dicts(releases_dict, merge)

        # mark as done this session
        session_scraped_ids.append(key)

    # write to file
    dig.write_registry(store, releases_dict)

    dig.scrape_yield()
    return counter
