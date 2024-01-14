// TASKS

// - placeholder artwork image
// - improve visuals for loading in progress items
// - improve feedback for loading failures (not spinning endlessly)
// - relay info if there are no results

// - colour and accent tweaks
// - implement label link (on tap)

// - add support for background audio sesion
// - add info to MPNowPlacyingCenter
// - add support for prev / next on backgrounded app
// - add autoplay support

// - refactor user data into a single dict and move to context
// - user store prev position, prev mode etc
// - serialise prev position and prev mode?
// - user fav store
// - user fav genres

// - thread to free up space
// - function to delete files
// - img and audio file cache management
// - add clear cache and cache options

// - side swipe still isnt perfect
// - vertical swipe still sometimes feel sticky

// - move scrapers to sub folder
// - add reg validation

// REGRESS

// DONE
// x - haptic click on like
// x - add support to update rules from scraper
// x - store specific category selection. ie redeye ([techno / electro, house / disco])
// x - update store scpedific section display
// x - store specific feed population
// x - drag reload spinner
// x - fix ci
// x - ensure scaling of lenient button is correct on other devices
// x - buttons should be activated on tap
// x - switch service account file
// x - fix ratio for lenient button
// x - text, sizes and spacing tweaks
// x - improve lenient button
// x - move away from legacy registry
// x - add store config and use to populate local registry
// x - add store field to items
// x - add a registry version field
// x - reset chart positions in the new scrape jobs
// x - move red eye to new scrape job
// x - sync store config to cloud
// x - move reg to firebase
// x - parse juno store info
// x - set min ios version on pen and put
// x - in app store prev position in a back view, or move scroll into view
// x - move item cache to cached/tmp
// x - settings menu / page
// o - registry seems to have trouble updating
// x - poll registry for updates periodically
// x - align position of view and tags popup menu
// x - lenient button click code
// x - add has sold out tag
// x - move has charted tag
// x - text, sizes and spacing tweaks 1
// x - bug where a track stops but another isnt playing and the prev track cannot restart (iphone 7) + now repro on 11
// x - track names can sometimes have trailing commas
// x - add missing glyphs (or at least some)
// x - cleanup soa
// x - memory warnings
// x - spinner and drag to reload
// x - test and implement on iphone7
// x - store info pre-order badge
// x - store info out of stock badge
// x - store info has charted
// x - cache the registry
// x - make back work properly (from likes menu)
// x - track names are sometimes not split correctly
// x - should have multiple soas, switch on request and clean up the old
// x - selected track is not reset when changing mode
// x - add support for setting bundle identifier from config
// x - fix / automate ability to set personal team
// x - app icon
// x - enum cache

#include "types.h"
#include "ecs/ecs_scene.h"

#include "json.hpp"
#include <set>

using namespace put::ecs;

namespace EntryFlags
{
    enum EntryFlags
    {
        allocated = 1<<0,
        artwork_cached = 1<<1,
        tracks_cached = 1<<2,
        artwork_loaded = 1<<3,
        tracks_loaded = 1<<4,
        transitioning = 1<<5,
        dragging = 1<<6,
        artwork_requested = 1<<7,
        liked = 1<<8,
        hovered = 1<<9,
        cache_url_requested = 1<<10
    };
};

namespace StoreTags
{
    enum StoreTags
    {
        preorder = 1<<0,
        out_of_stock = 1<<1,
        has_charted = 1<<2,
        has_been_out_of_stock = 1<<3
    };

    const c8* names[] = {
        "preorder",
        "out_of_stock",
        "has_charted",
        "has_been_out_of_stock"
    };

    const c8* icons[] = {
        ICON_FA_CALENDAR_TIMES_O,
        ICON_FA_EXCLAMATION_TRIANGLE,
        ICON_FA_FIRE,
        ICON_FA_EXCLAMATION
    };
}
typedef u32 StoreTags_t;

namespace Page
{
    enum Page
    {
        feed,
        likes,
        settings
    };

    const c8* display_names[] = {
        "Feed"
        "Likes"
        "Settings"
    };
}
typedef u32 Page_t;

namespace DataStatus
{
    enum DataStatus
    {
        e_not_initialised,
        e_loading,
        e_ready,
        e_not_available
    };
}
typedef u32 DataStatus_t;

struct soa
{
    cmp_array<Str>                          id;
    cmp_array<u64>                          flags;
    cmp_array<Str>                          artist;
    cmp_array<Str>                          title;
    cmp_array<Str>                          label;
    cmp_array<Str>                          cat;
    cmp_array<Str>                          link;
    cmp_array<Str>                          artwork_url;
    cmp_array<Str>                          artwork_filepath;
    cmp_array<u32>                          artwork_texture;
    cmp_array<pen::texture_creation_params> artwork_tcp;
    cmp_array<u32>                          track_name_count;
    cmp_array<Str*>                         track_names;
    cmp_array<u32>                          track_url_count;
    cmp_array<Str*>                         track_urls;
    cmp_array<u32>                          track_filepath_count;
    cmp_array<Str*>                         track_filepaths;
    cmp_array<u32>                          select_track;
    cmp_array<f32>                          scrollx;
    cmp_array<StoreTags_t>                  store_tags;
    std::atomic<size_t>                     available_entries = {0};
    std::atomic<size_t>                     soa_size = {0};
};

struct AsyncDict
{
    std::mutex                  mutex;
    nlohmann::json              dict;
    std::atomic<DataStatus_t>   status = { DataStatus::e_not_initialised };
};

struct DataContext
{
    // TODO: legacy
    nlohmann::json      user_data;
    std::atomic<u32>    user_data_status = { 0 };
    
    //
    AsyncDict           stores;
    std::atomic<u32>    cached_release_folders = { 0 };
    std::atomic<size_t> cached_release_bytes = { 0 };
};

struct StoreView
{
    Str                 store_name = "";
    Str                 selected_view = "";
    std::vector<Str>    selected_sections = {};
};

struct ReleasesView
{
    soa                 releases = {};
    DataContext*        data_ctx = nullptr;
    Page_t              page = Page::feed;
    StoreView           store_view = {};
    std::atomic<u32>    terminate = { 0 };
    std::atomic<u32>    threads_terminated = { 0 };
    u32                 top_pos = 0;
    vec2f               scroll = vec2f(0.0f, 0.0f);
};

struct ChartItem
{
    std::string index;
    u32         pos;
};

struct Store
{
    Str              name;
    std::vector<Str> view_search_names;
    std::vector<Str> view_display_names;
    std::vector<Str> section_search_names;
    std::vector<Str> sections_display_names;
    u32              selected_view_index = 1;
    u32              selected_sections_mask = 0xff;
    StoreView        store_view = {};
};

struct AppContext
{
    s32                     w, h = 0;
    f32                     status_bar_height = 0.0f;
    f32                     releases_scroll_maxy = 0.0f;
    void*                   releases_window = nullptr;
    Str                     play_track_filepath = "";
    bool                    invalidate_track = false;
    bool                    mute = false;
    bool                    scroll_lock_y = false;
    bool                    scroll_lock_x = false;
    bool                    side_drag = false;
    vec2f                   scroll_delta = vec2f::zero();
    bool                    touch_down = false;
    vec2f                   tap_pos = vec2f(FLT_MAX, FLT_MAX);
    s32                     top = -1;
    Str                     open_url_request = "";
    u32                     open_url_counter = 0;
    nlohmann::json          stores = {};
    Store                   store = {};
    Store                   store_view = {};
    ReleasesView*           view = nullptr;
    ReleasesView*           back_view = nullptr;
    ReleasesView*           reload_view = nullptr;
    DataContext             data_ctx = {};
    std::set<ReleasesView*> background_views = {};
    u32                     spinner_texture = 0;
};

// magic number constants
constexpr f32 k_promax_11_w = 1125.0f; // ratios were tuned from pixels sizes on iphone11 pro max
constexpr f32 k_promax_11_h = 2436.0f;
constexpr f32 k_drag_threshold = 0.1f;
constexpr f32 k_inertia = 0.96f;
constexpr f32 k_inertia_cutoff = 3.33f;
constexpr f32 k_snap_lerp = 0.3f;
constexpr f32 k_indent1 = 2.0f;
constexpr f32 k_top_pull_pad = 1.5f;
constexpr f32 k_top_pull_reload = 1.25f;
constexpr f32 k_text_size_h1 = 2.25f;
constexpr f32 k_text_size_h2 = 1.5f;
constexpr f32 k_text_size_h3 = 1.25f;
constexpr f32 k_text_size_body = 1.0f;
constexpr f32 k_text_size_track = 0.75f;
constexpr f32 k_text_size_dots = 0.8f;
constexpr f32 k_release_button_tap_radius_ratio = 64.0f / k_promax_11_w;
constexpr f32 k_page_button_press_radius_ratio = 86.0f / k_promax_11_w;
