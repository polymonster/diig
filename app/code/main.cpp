#include "renderer.h"
#include "timer.h"
#include "file_system.h"
#include "pen_string.h"
#include "loader.h"
#include "dev_ui.h"
#include "pen_json.h"
#include "hash.h"
#include "str_utilities.h"
#include "input.h"
#include "data_struct.h"
#include "main.h"
#include "audio/audio.h"

#define STB_IMAGE_IMPLEMENTATION
#include "stb/stb_image.h"

#include "json.hpp"

#include <fstream>

#include "maths/maths.h"

using namespace put;
using namespace pen;

namespace
{
    void*  user_setup(void* params);
    loop_t user_update();
    void   user_shutdown();
} // namespace

namespace pen
{
    pen_creation_params pen_entry(int argc, char** argv)
    {
        pen::pen_creation_params p;
        p.window_width = 1125 / 3;
        p.window_height = 2436 / 3;
        p.window_title = "dig";
        p.window_sample_count = 4;
        p.user_thread_function = user_setup;
        p.flags = pen::e_pen_create_flags::renderer;
        return p;
    }
} // namespace pen

// curl api

// curls include
#define CURL_STATICLIB
#include "curl/curl.h"

namespace curl
{
    constexpr size_t k_min_alloc = 1024;

    struct DataBuffer {
        u8*    data = nullptr;
        size_t size = 0;
        size_t alloc_size = 0;
    };

    void init()
    {
        curl_global_init(CURL_GLOBAL_ALL);
    }

    size_t write_function(void *ptr, size_t size, size_t nmemb, DataBuffer* db)
    {
        size_t required_size = db->size + size * nmemb;
        size_t prev_pos = db->size;
        
        // allocate. with a min alloc amount to avoid excessive small allocs
        if(required_size >= db->alloc_size)
        {
            size_t new_alloc_size = std::max(required_size+1, k_min_alloc+1); // alloc with +1 space for null term
            db->data = (u8*)realloc(db->data, new_alloc_size);
            db->size = required_size;
            db->alloc_size = new_alloc_size;
            PEN_ASSERT(db->data);
        }
        
        memcpy(db->data + prev_pos, ptr, size * nmemb);
        db->data[required_size] = '\0'; // null term
        return size * nmemb;
    }

    DataBuffer download(const c8* url)
    {
        CURL *curl;
        CURLcode res;
        DataBuffer db = {};
        
        curl = curl_easy_init();
        
        if(curl) {
            curl_easy_setopt(curl, CURLOPT_URL, url);
            curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
            curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, false);
            curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_function);
            curl_easy_setopt(curl, CURLOPT_WRITEDATA, &db);
        
            res = curl_easy_perform(curl);

            if(res != CURLE_OK)
            {
                PEN_LOG("curl_easy_perform() failed: %s\n", curl_easy_strerror(res));
            }

            curl_easy_cleanup(curl);
        }
        
        return db;
    }
}

u32 get_tags(nlohmann::json& tags)
{
    u32 t = 0;
    for(size_t i = 0; i < PEN_ARRAY_SIZE(Tags::names); ++i)
    {
        auto& name = Tags::names[i];
            
        if(tags.contains(name))
        {
            if(tags[name])
            {
                t |= (1<<i);
            }
        }
    }
    
    return t;
}

Str get_tags_str(u32 tags)
{
    Str tag_str = "";
    bool first = true;
    for(size_t i = 0; i < PEN_ARRAY_SIZE(Tags::names); ++i)
    {
        if(tags & 1<<i)
        {
            if(!first)
            {
                tag_str.append(" / ");
            }
            
            tag_str.append(Tags::names[i]);
            first = false;
        }
    }
    
    return tag_str;
}

u32 tag_menu(u32 tags)
{
    for(size_t i = 0; i < PEN_ARRAY_SIZE(Tags::names); ++i)
    {
        bool selected = tags & 1<<i;
        ImGui::Checkbox(Tags::names[i], &selected);
        
        if(selected)
        {
            tags |= (1<<i);
        }
        else
        {
            tags &= ~(1<<i);
        }
    }
    
    return tags;
}

static soa              s_releases;

// TODO: make
static nlohmann::json   s_likes;
static std::mutex       s_like_mutex;
static bool             s_likes_invalidated = false;

nlohmann::json get_likes()
{
    s_like_mutex.lock();
    auto cp = s_likes;
    s_like_mutex.unlock();
    return cp;
}

bool has_like(Str id)
{
    bool ret = false;
    s_like_mutex.lock();
    if(s_likes.contains(id.c_str()))
    {
        ret = s_likes[id.c_str()];
    }
    s_like_mutex.unlock();
    return ret;
}

void add_like(Str id)
{
    s_like_mutex.lock();
    s_likes[id.c_str()] = true;
    s_like_mutex.unlock();
    s_likes_invalidated = true;
}

void remove_like(Str id)
{
    s_like_mutex.lock();
    s_likes.erase(id.c_str());
    s_like_mutex.unlock();
    s_likes_invalidated = true;
}

generic_cmp_array& get_component_array(soa& s, size_t i)
{
    generic_cmp_array* begin = (generic_cmp_array*)&s;
    return begin[i];
}

size_t get_num_components(soa& s)
{
    generic_cmp_array* begin = (generic_cmp_array*)&s;
    generic_cmp_array* end = (generic_cmp_array*)&s.available_entries;
    return (size_t)(end - begin);
}

void resize_components(soa& s, size_t size)
{
    size_t new_size = s.soa_size + size;

    size_t num = get_num_components(s);
    for (u32 i = 0; i < num; ++i)
    {
        generic_cmp_array& cmp = get_component_array(s, i);
        size_t alloc_size = cmp.size * new_size;

        if (cmp.data)
        {
            // realloc
            cmp.data = pen::memory_realloc(cmp.data, alloc_size);

            // zero new mem
            size_t prev_size = s.soa_size * cmp.size;
            u8* new_offset = (u8*)cmp.data + prev_size;
            size_t zero_size = alloc_size - prev_size;
            pen::memory_zero(new_offset, zero_size);

            continue;
        }

        // alloc and zero
        cmp.data = pen::memory_alloc(alloc_size);
        pen::memory_zero(cmp.data, alloc_size);
    }

    s.soa_size = new_size;
}

Str download_and_cache(const Str& url, Str releaseid)
{
    Str filepath = pen::str_replace_string(url, "https://", "");
    filepath = pen::str_replace_chars(filepath, '/', '_');
    
    Str dir = os_get_persistent_data_directory();
    dir.appendf("/dig/cache/%s", releaseid.c_str());
    
    // filepath
    Str path = dir;
    path.appendf("/%s", filepath.c_str());
    filepath = path;
    
    // check if file already exists
    u32 mtime = 0;
    pen::filesystem_getmtime(filepath.c_str(), mtime);
    if(mtime == 0)
    {
        // mkdirs
        pen::os_create_directory(dir.c_str());
        
        // download
        //PEN_LOG("downloading: %s\n", url.c_str());
        auto db = new curl::DataBuffer;
        *db = curl::download(url.c_str());
        
        // stash
        //PEN_LOG("caching: %s\n", filepath.c_str());
        FILE* fp = fopen(filepath.c_str(), "wb");
        fwrite(db->data, db->size, 1, fp);
        fclose(fp);
    }
    else
    {
        // PEN_LOG("cache hit: %s", filepath.c_str());
    }
    
    return filepath;
}

pen::texture_creation_params load_texture_from_disk(const Str& filepath)
{
    s32 w, h, c;
    stbi_uc* rgba = stbi_load(filepath.c_str(), &w, &h, &c, 4);
    
    if(c == 3)
    {
        u8* dst = (u8*)pen::memory_alloc(w * h * 4);
        u8* src = (u8*)rgba;
        
        u32 src_stride = w * c;
        u32 dst_stride = w * 4;
        
        for(u32 y = 0; y < h; ++y)
        {
            u8* row_pos_src = src + src_stride * y;
            u8* row_pos_dst = dst + dst_stride * y;
            
            for(u32 x = 0; x < h; x += 3)
            {
                row_pos_dst[x*4 + 0] = row_pos_src[x*c + 0];
                row_pos_dst[x*4 + 1] = row_pos_src[x*c + 1];
                row_pos_dst[x*4 + 2] = row_pos_src[x*c + 2];
                row_pos_dst[x*4 + 3] = 255;
            }
        }
        
        pen::memory_free(rgba);
        rgba = dst;
        c = 4;
    }
    
    pen::texture_creation_params tcp;
    tcp.width = w;
    tcp.height = h;
    tcp.format = PEN_TEX_FORMAT_RGBA8_UNORM;
    tcp.data = rgba;
    tcp.sample_count = 1;
    tcp.sample_quality = 0;
    tcp.num_arrays = 1;
    tcp.num_mips = 1;
    tcp.collection_type = 0;
    tcp.bind_flags = 0;
    tcp.usage = PEN_USAGE_DEFAULT;
    tcp.bind_flags = PEN_BIND_SHADER_RESOURCE;
    tcp.cpu_access_flags = 0;
    tcp.flags = 0;
    tcp.block_size = 4;
    tcp.pixels_per_block = 1;
    tcp.collection_type = pen::TEXTURE_COLLECTION_NONE;
    tcp.data = rgba;
    tcp.data_size = w * h * c;

    return tcp;
}

// TODO: remove
// TODO: serialise
static std::atomic<u32> s_request_mode = {0};
static std::atomic<u32> s_request_tags = {Tags::all};

void* info_loader(void* userdata)
{
    // load registry
    auto registry_data = curl::download("https://raw.githubusercontent.com/polymonster/dig/main/registry/releases.json");
    
    nlohmann::json releases_registry = nlohmann::json::parse((const c8*)registry_data.data);
    releases_registry.size();
    
    // load likes
    Str likes_filepath = os_get_persistent_data_directory();
    likes_filepath.appendf("/dig/user_data/likes.json");
    
    u32 mtime = 0;
    pen::filesystem_getmtime(likes_filepath.c_str(), mtime);
    if(mtime)
    {
        std::ifstream f(likes_filepath.c_str());
        s_likes = nlohmann::json::parse(f);;
    }
    
    // find weekly chart
    struct ChartItem
    {
        std::string index;
        u32 pos;
    };
    
    std::vector<ChartItem> weekly_chart;
    std::vector<ChartItem> monthly_chart;
    std::vector<ChartItem> new_releases;
    std::vector<ChartItem> likes;
    
    new_releases.reserve(1024);
    weekly_chart.reserve(128);
    monthly_chart.reserve(128);
    
    for(auto& item : releases_registry)
    {
        if(item.contains("weekly_chart"))
        {
            weekly_chart.push_back({
                item["id"],
                item["weekly_chart"]
            });
        }
        
        if(item.contains("monthly_chart"))
        {
            monthly_chart.push_back({
                item["id"],
                item["monthly_chart"]
            });
        }
        
        if(item.contains("new_releases"))
        {
            new_releases.push_back({
                item["id"],
                item["new_releases"]
            });
        }
    }
    
    // sort
    std::sort(begin(new_releases),end(new_releases),[](ChartItem a, ChartItem b) {return a.pos < b.pos; });
    std::sort(begin(weekly_chart),end(weekly_chart),[](ChartItem a, ChartItem b) {return a.pos < b.pos; });
    std::sort(begin(monthly_chart),end(monthly_chart),[](ChartItem a, ChartItem b) {return a.pos < b.pos; });
    
    // allocate mem
    resize_components(s_releases, releases_registry.size());
    
    // load internal
    u32 internal_mode = -1;
    u32 internal_tags = Tags::all;
    std::vector<ChartItem>* modes[] = {
        &new_releases,
        &weekly_chart,
        &monthly_chart,
        &likes,
    };
    
    for(;;)
    {
        if(internal_mode != s_request_mode || internal_tags != s_request_tags) {
            internal_mode = s_request_mode;
            internal_tags = s_request_tags;
            s_releases.available_entries = 0;
            
            // populate likes
            if(internal_mode == 3)
            {
                likes.clear();
                for(auto& like : s_likes.items())
                {
                    if(releases_registry.contains(like.key()) && like.value())
                    {
                        likes.push_back({
                            like.key(),
                            0
                        });
                    }
                }
            }
            
            for(auto& entry : *modes[internal_mode])
            {
                u32 ri = (u32)s_releases.available_entries;
                auto release = releases_registry[entry.index];
                
                // grab tags
                if(release.contains("tags"))
                {
                    u32 tags = get_tags(release["tags"]);
                    if(!(tags & internal_tags))
                    {
                        continue;
                    }
                }
                
                // simple info
                s_releases.artist[ri] = release["artist"];
                s_releases.title[ri] = release["title"];
                s_releases.link[ri] = release["link"];
                s_releases.label[ri] = release["label"];
                s_releases.cat[ri] = release["cat"];
                
                std::string id = release["id"];
                s_releases.id[ri] = id.c_str();

                // assign artwork url
                if(release["artworks"].size() > 1)
                {
                   s_releases.artwork_url[ri] = release["artworks"][1];
                }
                else
                {
                   s_releases.artwork_url[ri] = "";
                }

                // clear
                s_releases.artwork_filepath[ri] = "";
                s_releases.artwork_texture[ri] = 0;
                s_releases.flags[ri] = 0;
                
                s_releases.track_name_count[ri] = 0;
                s_releases.track_names[ri] = nullptr;
                
                s_releases.track_url_count[ri] = 0;
                s_releases.track_urls[ri] = nullptr;
                
                s_releases.track_filepath_count[ri] = 0;
                s_releases.select_track[ri] = 0; // reset

                // track names
                u32 name_count = (u32)release["track_names"].size();
                if(name_count > 0)
                {
                    s_releases.track_names[ri] = new Str[name_count];
                    for(u32 t = 0; t < release["track_names"].size(); ++t)
                    {
                       s_releases.track_names[ri][t] = release["track_names"][t];
                    }
                    
                    std::atomic_thread_fence(std::memory_order_release);
                    s_releases.track_name_count[ri] = name_count;
                }

                // track urls
                u32 url_count = (u32)release["track_urls"].size();
                if(url_count > 0)
                {
                    s_releases.track_urls[ri] = new Str[url_count];
                    for(u32 t = 0; t < release["track_urls"].size(); ++t)
                    {
                       s_releases.track_urls[ri][t] = release["track_urls"][t];
                    }
                    
                    std::atomic_thread_fence(std::memory_order_release);
                    s_releases.track_url_count[ri] = url_count;
                }
                
                // check likes
                if(has_like(s_releases.id[ri]))
                {
                    s_releases.flags[ri] |= EntryFlags::liked;
                }

                pen::thread_sleep_ms(1);
                s_releases.available_entries++;
                
                if(s_releases.available_entries > 250)
                {
                    break;
                }
            }
        }
    }
    
    return nullptr;
}

void* user_data_save_thread(void* userdata)
{
    // get user data dir
    Str user_data_dir = os_get_persistent_data_directory();
    user_data_dir.append("/dig/user_data/");
    
    // create dir
    pen::os_create_directory(user_data_dir);
   
    // likes
    Str likes_filepath = user_data_dir;
    likes_filepath.appendf("likes.json");
    
    for(;;)
    {
        if(s_likes_invalidated)
        {
            auto likes = get_likes();
            auto likes_str = likes.dump();
            
            FILE* fp = fopen(likes_filepath.c_str(), "w");
            fwrite(likes_str.c_str(), likes_str.length(), 1, fp);
            fclose(fp);
        }
        
        pen::thread_sleep_ms(66);
    }
}

void* data_cacher(void* userdata)
{
    for(;;)
    {
        // waits on info loader thread
        for(size_t i = 0; i < s_releases.available_entries; ++i)
        {
            // cache art
            if(!s_releases.artwork_url[i].empty())
            {
                if(s_releases.artwork_filepath[i].empty())
                {
                    s_releases.artwork_filepath[i] = download_and_cache(s_releases.artwork_url[i], s_releases.id[i]);
                    
                    s_releases.flags[i] |= EntryFlags::artwork_cached;
                }
            }
            
            // cache tracks
            if(!(s_releases.flags[i] & EntryFlags::tracks_cached))
            {
                if(s_releases.track_filepaths[i] != nullptr)
                {
                    delete[] s_releases.track_filepaths[i];
                    s_releases.track_filepaths[i] = nullptr;
                }
                
                if(s_releases.track_url_count[i] > 0 && s_releases.track_filepaths[i] == nullptr)
                {
                    s_releases.track_filepaths[i] = new Str[s_releases.track_url_count[i]];
                    
                    for(u32 t = 0; t < s_releases.track_url_count[i]; ++t)
                    {
                        s_releases.track_filepaths[i][t] = "";
                        Str fp = download_and_cache(s_releases.track_urls[i][t], s_releases.id[i]);
                        s_releases.track_filepaths[i][t] = fp;
                    }
                    
                    std::atomic_thread_fence(std::memory_order_release);
                    s_releases.flags[i] |= EntryFlags::tracks_cached;
                    s_releases.track_filepath_count[i] = s_releases.track_url_count[i];
                }
            }
        }
        
        pen::thread_sleep_ms(16);
    }
    
    return nullptr;
}

void* data_loader(void* userdata)
{
    for(;;)
    {
        for(size_t i = 0; i < s_releases.available_entries; ++i)
        {
            // load art if cached and not loaded
            std::atomic_thread_fence(std::memory_order_acquire);
            
            if((s_releases.flags[i] & EntryFlags::artwork_cached) &&
               !(s_releases.flags[i] & EntryFlags::artwork_loaded) &&
               (s_releases.flags[i] & EntryFlags::artwork_requested))
            {
                s_releases.artwork_tcp[i] = load_texture_from_disk(s_releases.artwork_filepath[i]);
                
                std::atomic_thread_fence(std::memory_order_release);
                s_releases.flags[i] |= EntryFlags::artwork_loaded;
            }
            
        }
        
        pen::thread_sleep_ms(16);
    }
}

vec2f touch_screen_mouse_wheel()
{
    const pen::mouse_state& ms = pen::input_get_mouse_state();
    vec2f cur = vec2f((f32)ms.x, (f32)ms.y);
    static vec2f prev = cur;
    
    static bool prevdown = false;
    if(!prevdown) {
        prev = cur;
    }
    
    vec2f delta = (cur - prev);
    prev = cur;
    
    if(ms.buttons[PEN_MOUSE_L])
    {
        prevdown = true;
        return delta;
    }
    
    prevdown = false;
    return 0.0f;
}

namespace
{
    pen::job*   s_thread_info = nullptr;
    pen::timer* frame_timer;
    pen::json   releases_registry;
    u32         clear_screen;
    AppContext  ctx;

    void* user_setup(void* params)
    {
        //unpack the params passed to the thread and signal to the engine it ok to proceed
        pen::job_thread_params* job_params = (pen::job_thread_params*)params;
        s_thread_info = job_params->job_info;
        pen::semaphore_post(s_thread_info->p_sem_continue, 1);

        // force audio in silet mode
        pen::os_ignore_slient();
        
        // intialise pmtech systems
        pen::jobs_create_job(put::audio_thread_function, 1024 * 10, nullptr, pen::e_thread_start_flags::detached);
        dev_ui::init();
        curl::init();
        
        // workers
        pen::thread_create(info_loader, 10 * 1024 * 1024, nullptr, pen::e_thread_start_flags::detached);
        pen::thread_create(data_cacher, 10 * 1024 * 1024, nullptr, pen::e_thread_start_flags::detached);
        pen::thread_create(data_loader, 10 * 1024 * 1024, nullptr, pen::e_thread_start_flags::detached);
        pen::thread_create(user_data_save_thread, 10 * 1024 * 1024, nullptr, pen::e_thread_start_flags::detached);
        
        // init context
        pen::window_get_size(ctx.w, ctx.h);
        ctx.scroll = vec2f(0.0, ctx.h);
        ctx.releases = &s_releases;
        ctx.status_bar_height = pen::os_get_status_bar_portrait_height();

        // timer
        frame_timer = pen::timer_create();
        pen::timer_start(frame_timer);
        
        // for clearing the backbuffer
        clear_state cs;
        cs.r = 1.0f;
        cs.g = 1.0f;
        cs.b = 1.0f;
        cs.a = 1.0f;
        cs.depth = 0.0f;
        cs.num_colour_targets = 1;
        clear_screen = pen::renderer_create_clear_state(cs);
        
        // white
        ImGui::StyleColorsLight();

        pen_main_loop(user_update);
        return PEN_THREAD_OK;
    }

    void user_shutdown()
    {
        pen::renderer_new_frame();

        pen::renderer_present();
        pen::renderer_consume_cmd_buffer();

        // signal to the engine the thread has finished
        pen::semaphore_post(s_thread_info->p_sem_terminated, 1);
    }

    loop_t user_update()
    {
        //
        s32 w, h;
        pen::window_get_size(w, h);
        
        constexpr f32   k_drag_threshold = 0.1f;
        constexpr f32   k_inertia = 0.96f;
        constexpr f32   k_inertia_cutoff = 3.33f;
        constexpr f32   k_snap_lerp = 0.3f;
        constexpr f32   k_indent1 = 2.0f;
                
        // state
        /*
        static vec2f    scroll = vec2f(0.0f, w); // start scroll so the dummy is off
        static Str      play_track_filepath = "";
        static bool     invalidate_track = false;
        static bool     mute = false;
        static bool     scroll_lock_y = false;
        static bool     scroll_lock_x = false;
        static vec2f    scroll_delta = vec2f::zero();
        static Str      open_url_request = "";
        static u32      open_url_counter = 0;
        */
        
        pen::timer_start(frame_timer);
        pen::renderer_new_frame();
        
        // clear backbuffer
        pen::renderer_set_targets(PEN_BACK_BUFFER_COLOUR, PEN_BACK_BUFFER_DEPTH);
        pen::renderer_clear(clear_screen);

        put::dev_ui::new_frame();
                
        ImGui::SetNextWindowPos(ImVec2(0.0f, 0.0f));
        ImGui::SetNextWindowSize(ImVec2((f32)w, (f32)h));
        
        ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(0.0f, 0.0f));
        
        ImGui::Begin("Main", nullptr, ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoScrollbar);
        
        static f32 k_status_bar_height = pen::os_get_status_bar_portrait_height();
        ImGui::Dummy(ImVec2(0.0f, k_status_bar_height));
        
        // dragging and scrolling
        vec2f cur_scroll_delta = touch_screen_mouse_wheel();
        if(pen::input_is_mouse_down(PEN_MOUSE_L))
        {
            ctx.scroll_delta = cur_scroll_delta;
        }
        else
        {
            // apply inertia
            ctx.scroll_delta *= k_inertia;
            if(mag(ctx.scroll_delta) < k_inertia_cutoff) {
                ctx.scroll_delta = vec2f::zero();
            }
            
            // snap back to min top
            if(ctx.scroll.y < w) {
                ctx.scroll.y = lerp(ctx.scroll.y, (f32)w, 0.5f);
            }
            
            // release locks
            ctx.scroll_lock_x = false;
            ctx.scroll_lock_y = false;
        }
        
        // clamp to top
        if(ctx.scroll.y < w) {
            f32 miny = (f32)w / 1.5f; // TODO: constant
            if(ctx.scroll.y < miny) {
                ctx.scroll.y = miny;
            }
        }
        
        f32 dx = abs(dot(ctx.scroll_delta, vec2f::unit_x()));
        f32 dy = abs(dot(ctx.scroll_delta, vec2f::unit_y()));
        
        bool side_drag = false; // TODO: move to ctx
        if(dx > dy)
        {
            side_drag = true;
        }
        
        bool release_textures = false;
        
        // header
        ImGui::SetWindowFontScale(3.0f);
        ImGui::Dummy(ImVec2(k_indent1, 0.0f));
        ImGui::SameLine();
        
        if(s_request_mode == 3)
        {
            ImGui::Text("%s", ICON_FA_CHEVRON_LEFT);
            if(ImGui::IsItemClicked())
            {
                s_request_mode = 0;
                s_releases.available_entries = 0;
                release_textures = true;
            }
        }
        else
        {
            ImGui::Text("Dig");
        }
        
        // mode

        // likes button on same line
        ImGui::SameLine();
        f32 offset = ImGui::CalcTextSize("%s", ICON_FA_HEART_O).y;
        ImGui::SetCursorPosX(w - offset * 1.5f);
        ImGui::Text("%s", s_request_mode == 3 ? ICON_FA_HEART : ICON_FA_HEART_O);
        if(ImGui::IsItemClicked())
        {
            s_releases.available_entries = 0;
            s_request_mode = 3;
            release_textures = true;
        }
        ImGui::SetWindowFontScale(1.0f);
        
        if(s_request_mode != 3)
        {
            // store page
            ImGui::SetWindowFontScale(2.0f);
            
            constexpr const char* k_modes[] = {
                "Latest",
                "Weekly Chart",
                "Monthly Chart",
                "Likes"
            };
            
            ImGui::Dummy(ImVec2(k_indent1, 0.0f));
            ImGui::SameLine();
            ImGui::Text("%s", k_modes[s_request_mode]);
            if(ImGui::IsItemClicked()) {
                ImGui::OpenPopup("Mode Select");
            }
            
            if(ImGui::BeginPopup("Mode Select"))
            {
                if(ImGui::MenuItem("Latest"))
                {
                    s_releases.available_entries = 0;
                    s_request_mode = 0;
                    release_textures = true;
                }
                if(ImGui::MenuItem("Weekly Chart"))
                {
                    s_releases.available_entries = 0;
                    s_request_mode = 1;
                    release_textures = true;
                }
                if(ImGui::MenuItem("Monthly Chart"))
                {
                    s_releases.available_entries = 0;
                    s_request_mode = 2;
                    release_textures = true;
                }
                ImGui::EndPopup();
            }
            
            ImGui::SetWindowFontScale(1.0f);
            
            // tags
            ImGui::Dummy(ImVec2(k_indent1, 0.0f));
            ImGui::SameLine();
                    
            ImGui::Text("%s", get_tags_str(s_request_tags).c_str());
            if(ImGui::IsItemClicked()) {
                ImGui::OpenPopup("Tag Select");
            }
            
            if(ImGui::BeginPopup("Tag Select"))
            {
                u32 new_tags = tag_menu(s_request_tags);
                if(new_tags != s_request_tags)
                {
                    s_releases.available_entries = 0;
                    s_request_tags = new_tags;
                    release_textures = true;
                }
                ImGui::EndPopup();
            }
        }
        else
        {
            // likes page
            ImGui::SetWindowFontScale(2.0f);
            ImGui::Dummy(ImVec2(k_indent1, 0.0f));
            ImGui::SameLine();
            ImGui::Text("%s", "Likes");
            ImGui::SetWindowFontScale(1.0f);
        }
        
        //
        if(release_textures)
        {
            for(size_t i = 0; i < s_releases.available_entries; ++i)
            {
                if (s_releases.flags[i] & EntryFlags::artwork_loaded){
                    if(s_releases.artwork_texture[i] != 0) {
                        pen::renderer_release_texture(s_releases.artwork_texture[i]);
                        s_releases.artwork_texture[i] = 0;
                    }
                    memset(&s_releases.artwork_tcp, 0x0, sizeof(texture_creation_params));
                    s_releases.flags[i] &= ~EntryFlags::artwork_loaded;
                    s_releases.flags[i] &= ~EntryFlags::artwork_requested;
                }
            }
        }
        
        // mouse
        auto ms = pen::input_get_mouse_state();
        
        // releases
        f32 releases_pos = ImGui::GetCursorPosY();
        ImGui::BeginChildEx("releases", 1, ImVec2(0, 0), false, ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse);
        auto current_window = ImGui::GetCurrentWindow();

        // Add an empty dummy at the top
        ImGui::Dummy(ImVec2(w, w));
        
        s32 top = -1;
        for(u32 r = 0; r < s_releases.available_entries; ++r)
        {
            auto title = s_releases.title[r];
            auto artist = s_releases.artist[r];
            
            // apply loads
            std::atomic_thread_fence(std::memory_order_acquire);
            if(s_releases.flags[r] & EntryFlags::artwork_loaded)
            {
                if(s_releases.artwork_texture[r] == 0)
                {
                    if(s_releases.artwork_tcp[r].data)
                    {
                        s_releases.artwork_texture[r] = pen::renderer_create_texture(s_releases.artwork_tcp[r]);
                        pen::memory_free(s_releases.artwork_tcp[r].data); // data is copied for the render thread. safe to delete
                        s_releases.artwork_tcp[r].data = nullptr;
                    }
                }
            }
            
            // select primary
            ImGui::Spacing();
            f32 y = ImGui::GetCursorPos().y - ImGui::GetScrollY();
            if(y < (f32)h - ((f32)w * 1.1f))
            {
                if(y > -w * 0.33f)
                {
                    if(top == -1)
                    {
                        top = r;
                    }
                }
            }
            
            ImGui::SetWindowFontScale(1.5f);
            
            ImGui::Dummy(ImVec2(k_indent1, 0.0f));
            ImGui::SameLine();
            ImGui::TextWrapped("%s: %s", s_releases.label[r].c_str(), s_releases.cat[r].c_str());
            
            ImGui::SetWindowFontScale(1.0f);
            
            // ..
            f32 scaled_vel = ctx.scroll_delta.x;
            
            // images
            if(s_releases.artwork_texture[r])
            {
                f32 h = (f32)w * ((f32)s_releases.artwork_tcp[r].height / (f32)s_releases.artwork_tcp[r].width);
                f32 spacing = 20.0f;
                
                ImGui::BeginChildEx("rel", r+1, ImVec2((f32)w, h + 50), false, 0);
                ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(spacing, 0.0));
                
                u32 num_images = std::max<u32>(1, s_releases.track_url_count[r]);
                f32 imgw = w + spacing;
                
                f32 max_scroll = (num_images * imgw) - imgw;
                for(u32 i = 0; i < num_images; ++i)
                {
                    if(i > 0)
                    {
                        ImGui::SameLine();
                    }
                    
                    ImGui::Image(IMG(s_releases.artwork_texture[r]), ImVec2((f32)w, h));

                    if(ImGui::IsItemHovered() && pen::input_is_mouse_down(PEN_MOUSE_L))
                    {
                        if(!ctx.scroll_lock_y)
                        {
                            if(abs(ctx.scroll_delta.x) > k_drag_threshold && side_drag)
                            {
                                s_releases.flags[r] |= EntryFlags::dragging;
                                ctx.scroll_lock_x = true;
                            }
                            
                            s_releases.flags[r] |= EntryFlags::hovered;
                        }
                    }
                }
                
                if(!pen::input_is_mouse_down(PEN_MOUSE_L))
                {
                    s_releases.flags[r] &= ~EntryFlags::hovered;
                    if(abs(scaled_vel) < 1.0)
                    {
                        s_releases.flags[r] &= ~EntryFlags::dragging;
                    }
                }
           
                // stop drags if we no longer hover
                if(!(s_releases.flags[r] & EntryFlags::hovered))
                {
                    if(s_releases.flags[r] & EntryFlags::dragging)
                    {
                        ctx.scroll_delta.y = 0.0f;
                        s_releases.scrollx[r] -= scaled_vel;
                    }
                    
                    f32 target = s_releases.select_track[r] * imgw;
                    f32 ssx = s_releases.scrollx[r];
                    
                    if(!(s_releases.flags[r] & EntryFlags::transitioning))
                    {
                        if(ssx > target + (imgw/2) && s_releases.select_track[r]+1 < num_images)
                        {
                            ctx.scroll_delta.x = 0.0;
                            s_releases.select_track[r] += 1;
                            s_releases.flags[r] |= EntryFlags::transitioning;
                        }
                        else if(ssx < target - (imgw/2) && (ssize_t)s_releases.select_track[r]-1 >= 0)
                        {
                            ctx.scroll_delta.x = 0.0;
                            s_releases.select_track[r] -= 1;
                            s_releases.flags[r] |= EntryFlags::transitioning;
                        }
                        else
                        {
                            if(abs(scaled_vel) < 5.0)
                            {
                                s_releases.flags[r] |= EntryFlags::transitioning;
                            }
                        }
                    }
                    else
                    {
                        if(abs(ssx - target) < k_inertia_cutoff)
                        {
                            s_releases.scrollx[r] = target;
                            s_releases.flags[r] &= ~EntryFlags::transitioning;
                        }
                        else
                        {
                            if(abs(scaled_vel) < 5.0)
                            {
                                s_releases.scrollx[r] = lerp(ssx, target, k_snap_lerp);
                            }
                        }
                    }
                }
                else if (s_releases.flags[r] & EntryFlags::dragging)
                {
                    s_releases.scrollx[r] -= ctx.scroll_delta.x;
                    s_releases.scrollx[r] = std::max(s_releases.scrollx[r], 0.0f);
                    s_releases.scrollx[r] = std::min(s_releases.scrollx[r], max_scroll);
                    s_releases.flags[r] &= ~EntryFlags::transitioning;
                }
                
                ImGui::SetScrollX(s_releases.scrollx[r]);
                
                ImGui::PopStyleVar();
                ImGui::EndChild();
            }
            else
            {
                ImGui::Dummy(ImVec2(w, w));
            }
            
            // tracks
            s32 tc = s_releases.track_filepath_count[r];
            if(tc != 0)
            {
                // offset to centre
                auto ww = ImGui::GetWindowSize().x;
                auto tw = ImGui::CalcTextSize(ICON_FA_STOP_CIRCLE).x * s_releases.track_url_count[r] * 1.5f;
                ImGui::SetCursorPosX((ww - tw) * 0.5f);
                
                // dots
                for(u32 i = 0; i < s_releases.track_url_count[r]; ++i)
                {
                    if(i > 0)
                    {
                        ImGui::SameLine();
                    }
                    
                    u32 sel = s_releases.select_track[r];
                    if(i == sel)
                    {
                        if(top == r)
                        {
                            ImGui::Text("%s", ICON_FA_PLAY);
                            
                            // load up the track
                            if(!(ctx.play_track_filepath == s_releases.track_filepaths[r][sel]))
                            {
                                ctx.play_track_filepath = s_releases.track_filepaths[r][sel];
                                ctx.invalidate_track = true;
                            }
                        }
                        else
                        {
                            ImGui::Text("%s", ICON_FA_STOP_CIRCLE);
                        }
                    }
                    else
                    {
                        ImGui::Text("%s", ICON_FA_STOP_CIRCLE);
                    }
                }
            }
            else
            {
                // no audio
                auto ww = ImGui::GetWindowSize().x;
                ImGui::SetCursorPosX(ww * 0.5f);
                ImGui::Text("%s", ICON_FA_TIMES_CIRCLE);
            }
            
            ImGui::Spacing();
            ImGui::Indent();
            
            // buttons
            auto cp = ImGui::GetCursorPos();
            auto offset = ImGui::GetScrollY();
            
            ImGui::SetWindowFontScale(2.0f);
            
            auto button_size = ImGui::CalcTextSize("%s", ICON_FA_HEART);
            
            bool pressed = false;
            if(!ctx.scroll_lock_x && !ctx.scroll_lock_y)
            {
                static bool debounce = false;
                if(pen::input_is_mouse_down(PEN_MOUSE_L) && !debounce)
                {
                    if(ms.x < cp.x + button_size.y)
                    {
                        float by = cp.y - offset + releases_pos;
                        float pad = 50.0;
                        if(ms.y >= by - pad && ms.y <= by + button_size.y + pad)
                        {
                            pressed = true;
                            debounce = true;
                        }
                    }
                }
                else if(!pen::input_is_mouse_down(PEN_MOUSE_L))
                {
                    debounce = false;
                }
            }
            
            ImGui::PushID("like");
            if(s_releases.flags[r] & EntryFlags::liked)
            {
                ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(225.0f/255.0f, 48.0f/255.0f, 108.0f/255.0f, 1.0f));
                ImGui::Text("%s", ICON_FA_HEART);
                if(pressed)
                {
                    remove_like(s_releases.id[r]);
                    s_releases.flags[r] &= ~EntryFlags::liked;
                }
                ImGui::PopStyleColor();
            }
            else
            {
                ImGui::Text("%s", ICON_FA_HEART_O);
                if(pressed)
                {
                    add_like(s_releases.id[r]);
                    s_releases.flags[r] |= EntryFlags::liked;
                }
            }
            ImGui::PopID();
        
            ImGui::SameLine();
            ImGui::PushID("buy");
            ImGui::Text("%s", ICON_FA_SHOPPING_BASKET);
            if(ImGui::IsItemClicked() && !ctx.scroll_lock_x && !ctx.scroll_lock_y)
            {
                ctx.open_url_request = s_releases.link[r];
            }
            ImGui::PopID();
            
            ImGui::SetWindowFontScale(1.0f);
            
            // release info
            ImGui::TextWrapped("%s", artist.c_str());
            ImGui::TextWrapped("%s", title.c_str());
            
            // track name
            u32 sel = s_releases.select_track[r];
            if(s_releases.track_name_count[r] > s_releases.select_track[r])
            {
                ImGui::TextWrapped("%s", s_releases.track_names[r][sel].c_str());
            }
            
            ImGui::Unindent();
            
            ImGui::Spacing();
        }
        
        // couple of empty ones so we can reach the end
        ImGui::Dummy(ImVec2(w, w));
        ImGui::Dummy(ImVec2(w, w));
        
        f32 maxy = ImGui::GetScrollMaxY() - w;
        ImGui::EndChild();
        
        ImGui::PopStyleVar(4);
        ImGui::End();
        
        if(!side_drag && abs(ctx.scroll_delta.y) > k_drag_threshold)
        {
            ctx.scroll_lock_y = true;
        }
        
        // only not if already scrolling x
        if(!ctx.scroll_lock_x)
        {
            ctx.scroll.y -= ctx.scroll_delta.y;
            ImGui::SetScrollY(current_window, ctx.scroll.y);
        }
        
        // clamp to bottom
        if(ctx.scroll.y > maxy) {
            ctx.scroll.y = std::min(ctx.scroll.y, maxy);
        }
        
        // audio player
        if(!ctx.mute)
        {
            static u32 si = -1;
            static u32 ci = -1;
            static u32 gi = -1;
            static bool started = false;
            
            if(top == -1)
            {
                // stop existing
                if(is_valid(si))
                {
                    // release existing
                    put::audio_channel_stop(ci);
                    put::audio_release_resource(si);
                    put::audio_release_resource(ci);
                    put::audio_release_resource(gi);
                    si = -1;
                    ci = -1;
                    gi = -1;
                    started = false;
                }
            }
            
            if(ctx.play_track_filepath.length() > 0 && ctx.invalidate_track)
            {
                //u32 sel = s_releases.select_track[top];
                //PEN_LOG("%s", s_releases.track_names[top][sel].c_str());
                
                // stop existing
                if(is_valid(si))
                {
                    // release existing
                    put::audio_channel_stop(ci);
                    put::audio_release_resource(si);
                    put::audio_release_resource(ci);
                    put::audio_release_resource(gi);
                    si = -1;
                    ci = -1;
                    gi = -1;
                    started = false;
                }
                
                si = put::audio_create_stream(ctx.play_track_filepath.c_str());
                ci = put::audio_create_channel_for_sound(si);
                gi = put::audio_create_channel_group();
                
                put::audio_add_channel_to_group(ci, gi);
                put::audio_group_set_volume(gi, 1.0f);

                ctx.invalidate_track = false;
                started = false;
            }
            
            // playing
            if(is_valid(ci))
            {
                put::audio_group_state gstate;
                memset(&gstate, 0x0, sizeof(put::audio_group_state));
                put::audio_group_get_state(gi, &gstate);
                
                if(started && gstate.play_state == put::e_audio_play_state::not_playing)
                {
                    //
                    put::audio_channel_stop(ci);
                    put::audio_release_resource(si);
                    put::audio_release_resource(ci);
                    put::audio_release_resource(gi);
                    si = -1;
                    ci = -1;
                    gi = -1;
                    
                    // move to next
                    u32 next = s_releases.select_track[top] + 1;
                    if(next < s_releases.track_filepath_count[top])
                    {
                        ctx.scroll_delta.x = 0.0;
                        s_releases.select_track[top] += 1;
                        s_releases.flags[top] |= EntryFlags::transitioning;
                    }
                }
                else if(gstate.play_state == put::e_audio_play_state::playing)
                {
                    started = true;
                }
            }
        }
        
        // make requests for data
        if(top != -1)
        {
            s32 range_start = max(top - 10, 0);
            s32 range_end = min<s32>(top + 10, (s32)s_releases.available_entries);
            
            for(size_t i = 0; i < s_releases.available_entries; ++i)
            {
                if(i >= range_start && i <= range_end) {
                    if(s_releases.artwork_texture[i] == 0) {
                        s_releases.flags[i] |= EntryFlags::artwork_requested;
                    }
                }
                else if (s_releases.flags[i] & EntryFlags::artwork_loaded){
                    if(s_releases.artwork_texture[i] != 0) {
                        // proper release
                        pen::renderer_release_texture(s_releases.artwork_texture[i]);
                        s_releases.artwork_texture[i] = 0;
                        s_releases.flags[i] &= ~EntryFlags::artwork_loaded;
                        s_releases.flags[i] &= ~EntryFlags::artwork_requested;
                    }
                }
            }
            std::atomic_thread_fence(std::memory_order_release);
        }
        
        // apply request for open url and handle it to ignore clicks that became drags
        if(!ctx.open_url_request.empty())
        {
            // open url if we hacent scrolled within 5 frames
            if(ctx.open_url_counter > 5)
            {
                pen::os_open_url(ctx.open_url_request);
                ctx.open_url_request = "";
                ctx.open_url_counter = 0;
            }
            else
            {
                ctx.open_url_counter++;
            }
                        
            // disable url opening if we began a scroll
            if(ctx.scroll_lock_x || ctx.scroll_lock_y)
            {
                ctx.open_url_request = "";
                ctx.open_url_counter = 0;
            }
        }
        // present
        put::dev_ui::render();
        pen::renderer_present();
        pen::renderer_consume_cmd_buffer();
        put::audio_consume_command_buffer();

        if (pen::semaphore_try_wait(s_thread_info->p_sem_exit))
        {
            user_shutdown();
            pen_main_loop_exit();
        }

        pen_main_loop_continue();
    }
} // namespace

void* pen::user_entry( void* params )
{
    return PEN_THREAD_OK;
}
