import cgu
import sys
import datetime
import redeye
import json
import os

from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

# global key for this session, not functional but saves passing through
global auth_key


# return true if the supplied `view` name is a chart
def is_view_chart(view):
    if view in ["weekly_chart", "monthly_chart"]:
        return True
    return False

# member wise merge 2 dicts, second will overwrite dest
def merge_dicts(dest, second):
    for k, v in second.items():
        if type(v) == dict:
            if k not in dest or type(dest[k]) != dict:
                dest[k] = dict()
            merge_dicts(dest[k], v)
        else:
            dest[k] = v


# find and parse a named html element
def find_parse_elem(text: str, pos: int, ident: str, end_str: str, reverse=False):
    if reverse:
        pos = text[0:pos].rfind(ident)
    else:
        pos = pos + text[pos:].find(ident)
        assert(pos != -1)

    # parse the start element
    end = cgu.enclose("<", ">", text, pos)

    # parse the rest of the body
    last = end-1
    if text[last] != end_str:
        end = last + text[last:].find(end_str)

    # return the result and the iter pos
    elem =  text[pos:end]
    return (end, elem)


# get the value of a html element, ie <a href="value"
def get_value(elem: str, ident: str):
    pos = elem.find(ident + "=")
    if pos != -1:
        val_start, encloser = cgu.find_first(elem, ["\"", "'"], pos)
        val_start = val_start+1
        val_end = val_start + elem[val_start:].find(encloser)
        return elem[val_start:val_end]
    return None


# parse the html tag to return the body text <p class="tag">BODY</p>
def parse_body(elem: str):
    tag_end = cgu.enclose("<", ">", elem, 0)
    return elem[tag_end:]


# parse the html tag to return the body text <p class="tag">BODY</p> + strip any extraneous html
def parse_strip_body(elem: str):
    tag_end = cgu.enclose("<", ">", elem, 0)
    body_end = elem.find("</", tag_end)
    if body_end != -1:
        return elem[tag_end:body_end]
    return elem[tag_end:]


# iteratively parse body to extract an element within a nested section
def parse_nested_body(elem: str, depth: int):
    iter = elem
    for i in range(0, depth):
        iter = parse_body(iter)
    end = iter.find("<")
    return iter[:end]


# function to sort release
def sort_func(kv):
    if kv != None:
        if "new_releases" in kv[1]:
            return kv[1]["new_releases"]
        else:
            now = datetime.datetime.now()
            return now.timestamp() - kv[1]["added"]


# parse entireity of a div section
def parse_div(html_str, div_class):
    divs = []
    while True:
        first = html_str.find(div_class)
        # no more left
        if first == -1:
            break
        start = html_str[:first].rfind("<div ")
        stack = 1
        iter_pos = first
        while stack > 0:
            open = cgu.us(html_str.find("<div", iter_pos))
            close = html_str.find("</div", iter_pos)
            if close != -1 and open < close:
                stack += 1
                iter_pos = open + 5
            elif close != -1:
                stack -= 1
                iter_pos = close + 5

        divs.append(html_str[start:iter_pos])

        # iterate
        html_str = html_str[iter_pos:]

    return divs


# parse entireity of a div section
def parse_class(html_str, html_class, ty):
    outputs = []
    while True:
        first = html_str.find(html_class)
        open_len = len("<{} ".format(ty))
        close_len = len("</{}>".format(ty))
        # no more left
        if first == -1:
            break
        start = html_str[:first].rfind("<{} ".format(ty))
        stack = 1
        iter_pos = first
        while stack > 0:
            open = cgu.us(html_str.find("<{}".format(ty), iter_pos))
            close = html_str.find("</{}".format(ty), iter_pos)
            if close != -1 and open < close:
                stack += 1
                iter_pos = open + open_len
            elif close != -1:
                stack -= 1
                iter_pos = close + close_len

        outputs.append(html_str[start:iter_pos])

        # iterate
        html_str = html_str[iter_pos:]

    return outputs


# parse a single class element
def parse_class_single(html_str, html_class, ty):
    while True:
        first = html_str.find(html_class)
        close_len = len("</{}>".format(ty))
        # no more left
        if first == -1:
            break
        start = html_str[:first].rfind(f"<{ty} ")
        end = html_str.find(f"</{ty}", first)
        if start != -1 and end != -1:
            return html_str[start:end+close_len]
    return None


# creates an authorised session to write entires to firebase
def auth_session():
    scopes = [
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/firebase.database"
    ]

    if auth_key:
        credentials = service_account.Credentials.from_service_account_info(
            auth_key,
            scopes=scopes
        )
    else:
        print("from file")
        credentials = service_account.Credentials.from_service_account_file(
            "diig-19d4c-firebase-adminsdk-jyja5-ebcf729661.json", scopes=scopes
        )

    return AuthorizedSession(credentials)


# write entire registry contents
def patch_releases(entries: str):
    authed_session = auth_session()
    response = authed_session.patch(
        "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/releases.json", entries)
    assert(response.status_code == 200)
    if response.status_code == 200:
        print("successfully patched releases")
    else:
        print("error: patching releases")


# update store config to firebase, basically copies the stores.json local file to firebase
def update_stores():
    authed_session = auth_session()
    # update stores
    store_config = open("stores.json", "r").read()
    response = authed_session.patch(
        "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/stores.json", store_config)
    assert(response.status_code == 200)
    if response.status_code == 200:
        print("successfully updated stores")
    else:
        print("error: updating stores")

    # fetch rules + add store indices
    rules = authed_session.get("https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/.settings/rules.json")
    rules = json.loads(rules.text)

    release_indexes = rules["rules"]["releases"][".indexOn"]
    store_config = json.loads(store_config)
    for store_name in store_config:
        store = store_config[store_name]
        for section in store["sections"]:
            for view in store["views"]:
                index = f"{store_name}-{section}-{view}"
                if index not in release_indexes:
                    release_indexes.append(index)
                    print(f"added new search index: {index}")

    # patch rules
    rules_str = json.dumps(rules, indent=4)
    response = authed_session.put(
        "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/.settings/rules.json", rules_str)
    print(response.status_code)
    assert(response.status_code == 200)
    if response.status_code == 200:
        print("successfully updated search indices")
    else:
        print("error: updating search indices")



# clears the chart position and section position tracker, that will be re-populated during the next scrape
# allows old items to fall out of a view
def clear_tracker_keys(store, view_tracker_keys):
    print(f"clear: {len(view_tracker_keys)} tracker flags for {store}")
    # open store registry and remove the keys
    reg_filepath = f"registry/{store}.json"
    if os.path.exists(reg_filepath):
        releases_dict = json.loads(open(reg_filepath, "r").read())
        for release in releases_dict:
            release = releases_dict[release]
            for key in view_tracker_keys:
                if key in release:
                    del release[key]
        # write the registry back
        release_registry = (json.dumps(releases_dict, indent=4))
        open(reg_filepath, "w+").write(release_registry)


# patch store releases
def patch_store(store):
    reg_filepath = f"registry/{store}.json"
    if os.path.exists(reg_filepath):
        releases_str = open(reg_filepath, "r").read()
        patch_releases(releases_str)


# scrape a store based on rules defined in stores.json config
def scrape_store(stores, store_name):
    page_function = getattr(__import__(store_name), "scrape_page")
    if store_name in stores:
        # collapse store
        store = stores[store_name]
        # validate
        if "sections" not in store:
            print('error: "sections" missing from store config')
            exit(1)
        if "views" not in store:
            print('error: "views" missing from store config')
            exit(1)
        # clear trackers
        if "-clear-trackers" in sys.argv:
            # clear view position trackers
            view_tracker_keys = []
            for section in store["sections"]:
                for view in store["views"]:
                    view_tracker_keys.append(f"{store_name}-{section}-{view}")
            clear_tracker_keys(store_name, view_tracker_keys)
        session_scraped_ids = list()
        # iterate per section, per view
        for section in store["sections"]:
            # allow commandline control of section
            if "-section" in sys.argv:
                if section not in sys.argv:
                    continue
            for view in store["views"]:
                # allow commandline control of views
                if "-view" in sys.argv:
                    if view not in sys.argv:
                        continue
                view_dict = store["views"][view]
                page_count = view_dict["page_count"]
                counter = 0
                print("scraping: {} / {}".format(section, view))
                for i in range(1, 1+page_count):
                    view_url = view_dict["url"]
                    page_url = view_url.replace("${{section}}", section).replace("${{page}}", str(i))
                    counter = page_function(
                        page_url,
                        store_name,
                        view,
                        section,
                        counter,
                        session_scraped_ids
                    )
                    if counter == -1:
                        break
    else:
        print("error: unknown store {}".format(store_name))
        exit(1)


# test
def test():
    authed_session = auth_session()
    response = authed_session.patch(
        "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/test.json", '{"test": false}')
    print(response)
    assert(response.status_code == 200)


# main
if __name__ == '__main__':
    # service key for firebase writes
    if "-key" in sys.argv:
        auth_key = json.loads(sys.argv[sys.argv.index("-key") + 1])
    else:
        auth_key = json.loads(open("diig-auth.json").read())

    if "-store" in sys.argv:
        # read store config
        stores = json.loads(open("stores.json", "r").read())
        # store name
        store = sys.argv[sys.argv.index("-store") + 1]
        if not "-patch-only" in sys.argv:
            # scrape
            scrape_store(stores, store)
        # patch
        patch_store(store)
    elif "-update-stores" in sys.argv:
        # updates the store config into firebase
        update_stores()
    else:
        # grab single flags
        get_urls = "-urls" in sys.argv
        test_single = "-test_single" in sys.argv
        verbose = "-verbose" in sys.argv
        # scrape legacy
        redeye.scrape_legacy(100, get_urls, test_single, verbose)