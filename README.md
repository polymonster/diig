# diig

[![scrape](https://github.com/polymonster/diig/actions/workflows/scrape.yml/badge.svg)](https://github.com/polymonster/diig/actions/workflows/scrape.yml)
[![release](https://github.com/polymonster/diig/actions/workflows/release.yml/badge.svg)](https://github.com/polymonster/diig/actions/workflows/release.yml)

A record digging app for people who collect records. Fast audio player, infinite scroll, offline caching. Swipe through new releases and charts from your favourite stores, tap through to buy.

<p align="center">
    <img src="https://github.com/polymonster/polymonster.github.io/blob/master/images/diig/diig.gif?raw=true" width="640" height="360"/>
</p>

## Get the Beta

Available now on iOS and Android. Email [polymonster@icloud.com](mailto:polymonster@icloud.com) to join:

- **iOS** - via TestFlight
- **Android** - via Google Play internal testing

Website coming soon. Get in touch to register interest.

## Contributing

Contributions welcome. Got a store you want scraped? Raise an issue or better yet, implement it yourself and open a PR.

If you're finding diig useful and want to help keep it running, sponsorship helps cover developer fees and hosting costs.

## Scrapers

Scrapers run [nightly](https://github.com/polymonster/diig/actions) to pull releases from record stores. Each store needs a schema defining its structure and a parser to extract release data from HTML.

### Running Locally

```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2
cd scrape
python3 dig.py -urls -store juno -verbose -key "{}"
```

Where `-key` is a valid Firebase auth token. Run `python3 dig.py -help` for full options.

### Schemas

#### Release Schema

```json
{
    "id": "store-specific release id",
    "link": "url to release page",
    "artist": "artist name",
    "title": "release title",
    "label": "label name",
    "label_link": "url to label page",
    "cat": "catalogue number",
    "artworks": ["small", "medium", "large"],
    "track_names": ["track 1", "track 2"],
    "track_urls": ["url to mp3 snippet", "..."],
    "store": "store name",
    "store_tags": {
        "out_of_stock": false,
        "preorder": false
    }
}
```

#### Store Schema

```json
{
    "sections": ["techno", "house", "electro"],
    "section_display_names": ["Techno", "House", "Electro"],
    "views": {
        "weekly_chart": {
            "url": "https://store.com/${{section}}/charts/weekly",
            "page_count": 1
        },
        "new_releases": {
            "url": "https://store.com/${{section}}/new/page/${{page}}",
            "page_count": 10
        }
    }
}
```

### Discogs

Discogs links are fetched or attempted to be fetched for all releases. This algrithm is work in progress and it is tricky to find the exact match in some cases. You can add items directly to you Discogs wantlist from in the app. In time deeper integration with discogs will be implemented.

## Building the App

Built with C++, Objective-C and [ImGui](https://github.com/ocornut/imgui) on top of [pmtech](https://github.com/polymonster/pmtech).

```bash
git submodule update --init --recursive
cd app
pmtech/pmbuild ios    # or: mac, android
```

Xcode/Android Studio project lands in `app/build/<platform>`. Build from IDE or command line:

```bash
pmtech/pmbuild make ios diig
```
