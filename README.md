# Dig

Dig is a record digging app that provides a high performance audio player and ergonomic user interface to make digging through record snippets rapid, responsive and enjoyable.

It provides a record store agnostic audio player with a familiar social media infinite scrolling interface to allow users to dig for new releases and provide click through links to stores to buy. Feeds and snippets are cached which also enables offline browsing.

The aim is to be extensible so more record stores, sections and views can be added from different sources. The current scope of the sites and sections that are being monitored is opinionated and targeted to a small group of friends, but the overall goal is to allow community contribution and expand the project.

<p align="center">
    <img src="https://github.com/polymonster/dig/raw/main/media/dig.gif"/>
</p>

## Schemas

The project provides schemas and a unified data representation so that other record stores and sources can be added to expand the database.

### Release Schema

A release schema defines a single release, specifying artist, track names, track urls of snippits and artworks amongst other information. Releases are stored in a flat dictionary with the key being their id plus the store name prefix to avoid ID collisions, each release is treated uniquely per record store. In the future aggregating releases and cross checking them might be a feature worth looking into.

```json
{
    "id": "string - store specific id for the release",
    "link": "string - url link to the store specific page for the release",
    "artist": "string - the artist name",
    "title": "string - the releases title name",
    "label": "string - name of the label",
    "label_link": "string - url link to the store specific page for the label",
    "cat": "string - the catalogue number for the label of the release",
    "artworks": [
        "string list - 3 artwork sizes: [small, medium, large]"
    ],
    "track_names": [
        "string list - track names"
    ],
    "track_urls": [
        "string list - url links to track mp3s"
    ],
    "store": "string - the specific store this release is from",
    "store_tags": {
        "out_of_stock": true,
        "has_sold_out": true,
        "has_charted": true,
        "preorder": true
    },

    "<store>-<section>_<view>": "int - position in a view (page) for particular store and section (genre group)",
    "Example Genre": "Genre Tag"
}
```

### Store Schema

A store config can specify parts of a record store website to track. `store` is the record store itself, `sections` define genre groups and `views` define charts, latest releases, preorders and other criteria which may vary from site to site. You can supply the special variables `${{section}}` and `${{page}}` to record store urls to scrape multiple pages and sections.

```json
{
    "sections": [
        "string list - Sections names to parse from the website, these strings will appear in the website urls",
    ],
    "section_display_names": [
        "string list - Display names for the sections for rendering within the app"
    ],
    "views": {
        "weekly_chart": {
            "url": "https://www.recordstore.co.uk/${{section}}/weekly-chart",
            "page_count": "int - number of pages to parse for the url"
        },
        "monthly_chart": {
            "url": "https://www.recordstore.co.uk/${{section}}/monthly-chart",
            "page_count": 1
        },
        "new_releases": {
            "url": "https://www.recordstore.co.uk/${{section}}/new-releases/page-${{page}}",
            "page_count": 100
        }
    }
}
```

## Scrapers

Scrapers run [nightly](https://github.com/polymonster/dig/actions) to update information, if you provide a store schema then you need to define a page scraper function. There are currently a few examples in the project. It involves parsing the release schema information from the store's html pages.

## Firebase

Data is uploaded and synchronised to firebase with data publicly readable. For a dump of the entire releases database you can use:

```text
curl https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/releases.json
```

## App

The dig app currently runs natively on iOS, it is implemented using C++, Objective-C and ImGui via my cross platform game engine [pmtech](https://github.com/polymonster/pmtech). You can find more info in that repository on how to build, add pmbuild to your path then:

```text
git submodule update --init --recursive // fetch submodules pmtech, pmbuild
cd app
pmbuild ios
pmbuild make ios dig
```

The app will soon be available via `TestFlight` if you want to be invited to the Nightly build please open an issue.

## Contribution / Sponsorship

Contributions and requests are welcome. If you have requests for features and stores to scrape you can raise an issue. Better still if you can implement your own then go right ahead, make a fork and then a pull request we can start from there.

If you like this project and are interested in helping it expand further, sponsorship will help with the cost of developer fees and hosting fees for the cloud infrastructure. Currently the costs are low and the project is open source but expansion may require incur some costs.
