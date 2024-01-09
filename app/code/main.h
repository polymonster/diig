// TASKS
// - improve visuals for loading in progress items
// - improve lenient button
// - fix ratio / scaling of sizes for lenient button

// - placeholder artwork image
// - drag reload spinner

// - text, sizes and spacing tweaks
// - colour and accent tweaks

// - thread to free up space
// - function to delete files
// - img and audio file cache management
// - add clear cache and cache options

// - user store prev position, prev mode etc
// - serialise prev position and prev mode?
// - refactor user data into a single dict and move to context

// - side swipe still isnt perfect
// - vertical swipe still sometimes feel sticky

// - add a registry version field
// - implement label link?
// - store specific category selection. ie redeye ([techno / electro, house / disco])
// - store field to items

// - add reg validation
// - add store config and use to populate local registry
// - move away from legacy registry
// - reset chart positions in the new scrape jobs

// DONE
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

namespace Tags
{
    enum Tag
    {
        techno = 1<<0,
        electro = 1<<1,
        house = 1<<2,
        disco = 1<<3,
        all = 0xffffffff
    };

    const c8* names[] = {
        "techno",
        "electro",
        "house",
        "disco"
    };
}
typedef u32 Tags_t;

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

namespace View
{
    enum View
    {
        latest,
        weekly_chart,
        monthly_chart,
        likes,
        settings
    };

    const c8* display_names[] = {
        "Latest",
        "Weekly Chart",
        "Monthly Chart",
        "Likes"
        "Settings"
    };

    const c8* lookup_names[] = {
        "new_releases",
        "weekly_chart",
        "monthly_chart",
        "likes",
        "settings"
    };
}
typedef u32 View_t;

namespace DataStatus
{
    enum DataStatus
    {
        e_not_initialised,
        e_loading,
        e_ready
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

struct DataContext
{
    std::mutex          registry_mutex;
    nlohmann::json      registry;
    nlohmann::json      user_data;
    
    std::atomic<u32>    cache_registry_status = { 0 };
    std::atomic<u32>    latest_registry_status = { 0 };
    std::atomic<u32>    user_data_status = { 0 };
    
    std::atomic<u32>    cached_release_folders = { 0 };
    std::atomic<size_t> cached_release_bytes = { 0 };
};

struct ReleasesView
{
    soa                 releases = {};
    DataContext*        data_ctx = nullptr;
    View_t              view = View::latest;
    Tags_t              tags = Tags::all;
    std::atomic<u32>    terminate = { 0 };
    std::atomic<u32>    threads_terminated = { 0 };
    u32                 top_pos = 0;
    u32                 reg_timeout = 1000;
    vec2f               scroll = vec2f(0.0f, 0.0f);
};

struct ChartItem
{
    std::string index;
    u32         pos;
};

struct AppContext
{
    s32                     w, h;
    f32                     status_bar_height;
    f32                     releases_scroll_maxy = 0.0f;
    void*                   releases_window = nullptr;
    Str                     play_track_filepath = "";
    bool                    invalidate_track = false;
    bool                    mute = false;
    bool                    scroll_lock_y = false;
    bool                    scroll_lock_x = false;
    bool                    side_drag = false;
    vec2f                   scroll_delta = vec2f::zero();
    s32                     top = -1;
    Str                     open_url_request = "";
    u32                     open_url_counter = 0;
    ReleasesView*           view = nullptr;
    ReleasesView*           back_view = nullptr;
    ReleasesView*           reload_view = nullptr;
    DataContext             data_ctx = {};
    std::set<ReleasesView*> background_views = {};
};

// magic number constants
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
