import urllib.request
import cgu
import json
import sys
import os
import datetime
import dig

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
    cat_end = info_str.find(".")
    cat_start = info_str.find(":") + 1
    return info_str[cat_start:cat_end].strip()


def parse_artworks():
    # https://imagescdn.juno.co.uk/full/CS861163-01A-BIG.jpg
    # https://imagescdn.juno.co.uk/150/CS861163-01A.jpg
    pass

# juno
def scrape_juno(url):
    print("scraping: juno", flush=True)

    # try and then continue if the page does not exist
    try:
        html_file = urllib.request.urlopen(url)
    except:
        return

    html_str = html_file.read().decode("utf8")

    # gets products
    products = dig.parse_div(html_str, 'class="product-list"')

    # separate into items
    releases = dig.parse_div(products[0], 'class="dv-item"')

    for release in releases:
        (_, id_elem) = dig.find_parse_elem(release, 0, "<div id=", ">")
        (_, link_elem) = dig.find_parse_elem(release, 0, "<a href=", ">")
        (_, artwork_elem) = dig.find_parse_elem(release, 0, "<img class", ">")
        # https://imagescdn.juno.co.uk/full/CS861163-01A-BIG.jpg

        (offset, artist_elem) = dig.find_parse_elem(release, 0, '<a class="text-md"', "</a>")
        (offset, title_elem) = dig.find_parse_elem(release, offset, '<a class="text-md"', "</a>")
        (offset, label_elem) = dig.find_parse_elem(release, offset, '<a class="text-md"', "</a>")
        (offset, cat_elem) = dig.find_parse_elem(release, offset, '<div class="vi-text', "<br class")

        # tracks
        tracks = dig.parse_div(release, 'class="listing-track')

        release_dict = dict()
        release_dict["id"] = parse_id(id_elem)
        release_dict["link"] = parse_link(link_elem)
        release_dict["artist"] = dig.parse_body(artist_elem)
        release_dict["title"] = dig.parse_body(title_elem)
        release_dict["label"] = parse_label(label_elem)
        release_dict["cat"] = parse_cat(cat_elem)


        print(json.dumps(release_dict, indent=4))

        print(artwork_elem)

        '''
        for track in tracks:
            print(track)
        '''

        break