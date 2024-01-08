# Dig

Dig is a record digging app that provides a high performance audio player and ergonomic user interface to make digging through record snippits rapid, responsive and enjoyable. It provides a record store agnostic audio player with a familiar social media infinite scrolling interface to allow users to dig for new releases and provide click through links to stores to buy. Feeds and snippits are cached which also enables offline browsing.

<div align=”center”>
<img src="https://github.com/polymonster/dig/raw/main/media/dig.gif"/>
</div>

## Schemas

The project provides schemas and a unified data respresentation so that other record stores and sources can be added to expand the database.

### Release Schema

A release schema defines a single release, specifying artist, track names, track urls of snippits and artworks amogst other information:

```json
{
    "id": "string - store specific id for the release",
    "link": "string - url link to the store specific page for the release",
    "artist": "string - the artist name",
    "title": "string - the releases title name",
    "label": "string - name of the label",
    "label_link": "string - url link to the store specific page for the label",
    "cat": "string - the catalog number for the label of the release",
    "artworks": [
        "string list - 3 artwork sizes: [small, medium, large]"
    ],
    "track_names": [
        "string list - track names"
    ],
    "track_urls": [
        "string list - url links to track mp3s"
    ],
    "store": "string - the specifc store this release is from",
    "store_tags": {
        "out_of_stock": true,
        "has_sold_out": true,
        "has_charted": true,
        "preorder": true
    },

    "<store>-<section>-<view>": "int - position in a view for particular store and section",
    "Example Genre": "Genre Tag"
}
```

### Store Schema

A store can specify parts of a record store website to track. Sections define genre groups, Views define charts and latest releases:

## Scrapers

Scrapers run nightly to update information, if you provide a store schema then you need to define a page scraper function. There are currently a few examples in the project.

## Firebase

Data is uploaded and synchronised to firebase with data publicly readable. For a dump of the entire releases database you can use:

```text
curl
```