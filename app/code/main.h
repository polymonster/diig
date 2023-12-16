// TASKS
// - side swipe still isnt perfect

// UI / Text
// - add missing glyphs (or at least some)
// x - track names are sometimes not split correctly
// - track names can sometimes have trailing commas

// - should have multiple soas, switch on request and clean up the old
// - memory warnings
// - cache the registry,
// - img and audio file cache management
// - selected track is not reset when changing mode

// - user store prev position, prev mode etc
// - make back work properly (from likes menu) ^^
// - test and implement on iphone7

// - app icon
// - fix / automate ability to set personal team
// - add support for setting bundle identifier from config

#include "types.h"
#include "ecs/ecs_scene.h"

#include "json.hpp"

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
        hovered = 1<<9
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

namespace View
{
    enum View
    {
        latest,
        weekly_chart,
        monthly_chart,
        likes
    };

    const c8* names[] = {
        "Latest",
        "Weekly Chart",
        "Monthly Chart",
        "Likes"
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
    std::atomic<size_t>                     available_entries = {0};
    std::atomic<size_t>                     soa_size = {0};
};

struct DataContext
{
    nlohmann::json      cached_registry;
    nlohmann::json      latest_registry;
    nlohmann::json      user_data;
    
    std::atomic<u32>    cache_status = { 0 };
    std::atomic<u32>    latest_status = { 0 };
    std::atomic<u32>    user_data_status = { 0 };
};

struct ReleasesView
{
    soa                 releases;
    View_t              view;
    Tags_t              tags;
    std::atomic<u32>    terminate;
    DataContext*        data_ctx;
};

struct AppContext
{
    s32             w, h;
    f32             status_bar_height;
    vec2f           scroll = vec2f(0.0f, 0.0f);
    Str             play_track_filepath = "";
    bool            invalidate_track = false;
    bool            mute = false;
    bool            scroll_lock_y = false;
    bool            scroll_lock_x = false;
    bool            side_drag = false;
    vec2f           scroll_delta = vec2f::zero();
    s32             top = -1;
    Str             open_url_request = "";
    u32             open_url_counter = 0;
    ReleasesView*   view = nullptr;
    DataContext     data_ctx;
};
