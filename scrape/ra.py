import sys
import os
import json
import time
import datetime
import requests

# fetches upcoming resident advisor event listings for an area into the
# registry. uses ra's own (unofficial) graphql endpoint, so a failure here must
# not break the weekly job: the previous file is kept and the exit code is 0
#   python3 ra.py [-area 13] [-days 42]

RA_GRAPHQL = "https://ra.co/graphql"
AREA_NAMES = {13: "london"}

QUERY = """query GET_EVENT_LISTINGS($filters: FilterInputDtoInput, $pageSize: Int, $page: Int) {
  eventListings(filters: $filters, pageSize: $pageSize, page: $page) {
    data {
      event {
        id title date startTime contentUrl attending
        images { filename type }
        venue { name contentUrl }
        artists { id name }
        genres { name }
      }
    }
    totalResults
  }
}"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://ra.co/events/uk/london",
}


def fetch_page(area, start, end, page, page_size=100):
    variables = {
        "filters": {"areas": {"eq": area}, "listingDate": {"gte": start, "lte": end}},
        "pageSize": page_size,
        "page": page,
    }
    r = requests.post(RA_GRAPHQL, json={"operationName": "GET_EVENT_LISTINGS", "query": QUERY, "variables": variables},
                      headers=HEADERS, timeout=30)
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]["eventListings"]


def to_event(e):
    flyer = next((i["filename"] for i in e.get("images") or [] if i.get("type") == "FLYERFRONT"), None)
    return {
        "id": e["id"],
        "title": e.get("title", ""),
        "date": (e.get("date") or "")[:10],
        "start": e.get("startTime"),
        "url": f"https://ra.co{e.get('contentUrl', '')}",
        "venue": (e.get("venue") or {}).get("name", ""),
        "flyer": flyer,
        "lineup": [a["name"] for a in e.get("artists") or []],
        "genres": [g["name"] for g in e.get("genres") or []],
        "attending": e.get("attending") or 0,
    }


def fetch_events(area, days):
    today = datetime.date.today()
    start, end = today.isoformat(), (today + datetime.timedelta(days=days)).isoformat()
    events = {}
    page = 1
    while True:
        listing = fetch_page(area, start, end, page)
        for item in listing["data"]:
            ev = to_event(item["event"])
            events[ev["id"]] = ev
        if page * 100 >= listing["totalResults"] or not listing["data"]:
            break
        page += 1
        time.sleep(1)
    return events


if __name__ == "__main__":
    area = int(sys.argv[sys.argv.index("-area") + 1]) if "-area" in sys.argv else 13
    days = int(sys.argv[sys.argv.index("-days") + 1]) if "-days" in sys.argv else 42
    out = f"diig-registry/ra/{AREA_NAMES.get(area, str(area))}.json"
    try:
        events = fetch_events(area, days)
    except Exception as err:
        print(f"warning: ra fetch failed, keeping previous {out}: {err}")
        sys.exit(0)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    payload = {
        "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "area": area,
        "events": sorted(events.values(), key=lambda e: (e["date"], -e["attending"])),
    }
    open(out, "w+").write(json.dumps(payload, indent=4))
    print(f"ra: wrote {len(events)} events to {out}")
