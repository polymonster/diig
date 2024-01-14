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
#include "imgui_ext.h"

#define STB_IMAGE_IMPLEMENTATION
#include "stb/stb_image.h"

#include <fstream>
#include <thread>

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
                db.data = nullptr;
            }

            curl_easy_cleanup(curl);
        }
        
        return db;
    }
}

// TODO: make more user data centric
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

void free_components(soa& s)
{
    size_t num = get_num_components(s);
    for (u32 i = 0; i < num; ++i)
    {
        generic_cmp_array& cmp = get_component_array(s, i);
        pen::memory_free(cmp.data);
    }
}

Str get_cache_path()
{
    Str dir = os_get_cache_data_directory();
    dir.appendf("/dig/cache/");
    return dir;
}

Str get_docs_path()
{
    Str dir = os_get_persistent_data_directory();
    dir.appendf("/dig/");
    return dir;
}

Str download_and_cache(const Str& url, Str releaseid)
{
    Str filepath = pen::str_replace_string(url, "https://", "");
    filepath = pen::str_replace_chars(filepath, '/', '_');
    
    Str dir = get_cache_path();
    dir.appendf("/%s", releaseid.c_str());
    
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
        auto db = new curl::DataBuffer;
        *db = curl::download(url.c_str());
        
        // stash
        if(db->data)
        {
            FILE* fp = fopen(filepath.c_str(), "wb");
            fwrite(db->data, db->size, 1, fp);
            fclose(fp);
            
            // free
            free(db->data);
        }
    }
    
    return filepath;
}

Str get_persistent_filepath(const Str& basename, bool create_dirs = false)
{
    Str dir = os_get_persistent_data_directory();
    dir.appendf("/dig");
    
    // filepath
    Str path = dir;
    path.appendf("/%s", basename.c_str());
    Str filepath = path;
    
    if(create_dirs)
    {
        // check if file already exists and create dirs if not
        u32 mtime = 0;
        pen::filesystem_getmtime(filepath.c_str(), mtime);
        if(mtime == 0)
        {
            // mkdirs
            pen::os_create_directory(dir.c_str());
        }
    }

    return filepath;
}

Str download_and_cache_named(const Str& url, const Str& filename)
{
    Str dir = os_get_persistent_data_directory();
    dir.appendf("/dig");
    
    // filepath
    Str path = dir;
    path.appendf("/%s", filename.c_str());
    Str filepath = path;
    
    // check if file already exists
    u32 mtime = 0;
    pen::filesystem_getmtime(filepath.c_str(), mtime);
    if(mtime == 0)
    {
        // mkdirs
        pen::os_create_directory(dir.c_str());
    }
        
    // download
    auto db = new curl::DataBuffer;
    *db = curl::download(url.c_str());
    
    // stash
    FILE* fp = fopen(filepath.c_str(), "wb");
    fwrite(db->data, db->size, 1, fp);
    fclose(fp);
    
    // free
    free(db->data);
    
    return filepath;
}

pen::texture_creation_params load_texture_from_disk(const Str& filepath)
{
    s32 w, h, c;
    stbi_uc* rgba = stbi_load(filepath.c_str(), &w, &h, &c, 4);
    
    c = 4;
    
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

// fetches json from a url and caches it to persistent_directory/cache_filename
// if the url fetch fails it will load data from a previously cached file if it exists
// if no cached file exists and the url fetch fails then false is returned and the async_dict.status is set to DataStatus::e_not_available
bool fetch_json_cache(const c8* url, const c8* cache_filename, AsyncDict& async_dict)
{
    pen::scope_timer(cache_filename, true);
    auto j = curl::download(url);
    if(j.data)
    {
        async_dict.mutex.lock();
        try {
            async_dict.dict = nlohmann::json::parse((const c8*)j.data);
            async_dict.status = DataStatus::e_ready;
            
            // check for firebase errors
            if(async_dict.dict.size() == 1) {
                for(auto& item : async_dict.dict.items()) {
                    if(item.key() == "error") {
                        PEN_LOG("error: %s", async_dict.dict.dump(4).c_str());
                        async_dict.status = DataStatus::e_not_initialised;
                    }
                }
            }
        }
        catch(...) {
            async_dict.status = DataStatus::e_not_initialised;
        }
        async_dict.mutex.unlock();
    }
    
    Str filepath = get_persistent_filepath(cache_filename, true);
    if(async_dict.status == DataStatus::e_ready)
    {
        // cache async
        std::thread cache_thread([j, filepath]() {
            FILE* fp = fopen(filepath.c_str(), "wb");
            fwrite(j.data, j.size, 1, fp);
            fclose(fp);
        });
        cache_thread.detach();
    }
    else
    {
        // check for a cached item
        u32 mtime = 0;
        pen::filesystem_getmtime(filepath.c_str(), mtime);
        if(mtime > 0)
        {
            // ensures it's valid
            async_dict.mutex.lock();
            try {
                async_dict.dict = nlohmann::json::parse(std::ifstream(filepath.c_str()));
                async_dict.status = DataStatus::e_ready;
                
                // check for firebase errors
                if(async_dict.dict.size() == 1) {
                    for(auto& item : async_dict.dict.items()) {
                        if(item.key() == "error") {
                            PEN_LOG("cached error: %s", async_dict.dict.dump(4).c_str());
                            async_dict.status = DataStatus::e_not_initialised;
                        }
                    }
                }
                
                async_dict.status = DataStatus::e_not_available;
            } catch (...) {
                async_dict.status = DataStatus::e_not_available;
            }
            async_dict.mutex.unlock();
        }
        else
        {
            async_dict.status = DataStatus::e_not_available;
        }
    }
    
    return async_dict.status == DataStatus::e_ready;
}

void* registry_loader(void* userdata)
{
    DataContext* ctx = (DataContext*)userdata;
    
    // fetch stores
    fetch_json_cache("https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/stores.json", "stores.json", ctx->stores);
    
    return nullptr;
};

void* user_data_thread(void* userdata)
{
    // get user data dir
    Str user_data_dir = os_get_persistent_data_directory();
    user_data_dir.append("/dig/user_data/");
    
    // create dir
    pen::os_create_directory(user_data_dir);
    
    // grab likes
    u32 mtime  = 0;
    Str likes_filepath = user_data_dir;
    likes_filepath.appendf("likes.json");
    pen::filesystem_getmtime(likes_filepath.c_str(), mtime);
    if(mtime)
    {
        std::ifstream f(likes_filepath.c_str());
        s_likes = nlohmann::json::parse(f);;
    }

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

void* info_loader(void* userdata)
{
    // get view from userdata
    ReleasesView* view = (ReleasesView*)userdata;
    auto& store_view = view->store_view;
    
    nlohmann::json releases_registry;
    std::vector<ChartItem> view_chart;
    
    for(auto& section : store_view.selected_sections) {
        // index is concantonated store-section-view.json
        Str index_on = "";
        index_on.appendf(
            "%s-%s-%s",
            store_view.store_name.c_str(),
            section.c_str(),
            store_view.selected_view.c_str()
        );
        
        // cache file is the index name saved as json
        Str cache_file = index_on;
        cache_file.append(".json");
        
        // ordered search
        Str search_url = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/releases.json";
        search_url.appendf("?orderBy=\"%s\"&startAt=0", index_on.c_str());
        
        AsyncDict async_registry;
        fetch_json_cache(
            search_url.c_str(),
            cache_file.c_str(),
            async_registry
        );
        
        // TODO: handle total failure case
        if(async_registry.status != DataStatus::e_ready)
        {
            PEN_LOG("error: fetching %s", index_on.c_str());
            return nullptr;
        }
        
        // add stored?
        for(auto& item : async_registry.dict.items())
        {
            auto val = item.value();
            view_chart.push_back({
                item.key(),
                val[index_on.c_str()]
            });
        }
        
        releases_registry.merge_patch(async_registry.dict);
    }
    
    if(view->page == Page::likes)
    {
        for(auto& like : s_likes.items())
        {
            std::string id = "redeye-" + like.key();
            if(releases_registry.contains(id) && like.value())
            {
                view_chart.push_back({
                    id,
                    0
                });
            }
        }
    }
    
    // sort the items
    std::sort(begin(view_chart),end(view_chart),[](ChartItem a, ChartItem b) {return a.pos < b.pos; });
    
    // make space
    resize_components(view->releases, view_chart.size());
    
    for(auto& entry : view_chart)
    {
        u32 ri = (u32)view->releases.available_entries;
        auto release = releases_registry[entry.index];
        
        // simple info
        view->releases.artist[ri] = release["artist"];
        view->releases.title[ri] = release["title"];
        view->releases.link[ri] = release["link"];
        view->releases.label[ri] = release["label"];
        view->releases.cat[ri] = release["cat"];
        
        // clear
        view->releases.artwork_filepath[ri] = "";
        view->releases.artwork_texture[ri] = 0;
        view->releases.flags[ri] = 0;
        view->releases.track_name_count[ri] = 0;
        view->releases.track_names[ri] = nullptr;
        view->releases.track_url_count[ri] = 0;
        view->releases.track_urls[ri] = nullptr;
        view->releases.track_filepath_count[ri] = 0;
        view->releases.select_track[ri] = 0; // reset
        memset(&view->releases.artwork_tcp[ri], 0x0, sizeof(pen::texture_creation_params));
        
        std::string id = release["id"];
        view->releases.id[ri] = id.c_str();

        // assign artwork url
        if(release["artworks"].size() > 1)
        {
            view->releases.artwork_url[ri] = release["artworks"][1];
        }
        else
        {
            view->releases.artwork_url[ri] = "";
        }

        // track names
        u32 name_count = (u32)release["track_names"].size();
        if(name_count > 0)
        {
            view->releases.track_names[ri] = new Str[name_count];
            for(u32 t = 0; t < release["track_names"].size(); ++t)
            {
                view->releases.track_names[ri][t] = release["track_names"][t];
            }
            
            std::atomic_thread_fence(std::memory_order_release);
            view->releases.track_name_count[ri] = name_count;
        }

        // track urls
        u32 url_count = (u32)release["track_urls"].size();
        if(url_count > 0)
        {
            view->releases.track_urls[ri] = new Str[url_count];
            for(u32 t = 0; t < release["track_urls"].size(); ++t)
            {
                view->releases.track_urls[ri][t] = release["track_urls"][t];
            }
            
            std::atomic_thread_fence(std::memory_order_release);
            view->releases.track_url_count[ri] = url_count;
        }
        
        // check likes
        if(has_like(view->releases.id[ri]))
        {
            view->releases.flags[ri] |= EntryFlags::liked;
        }
        
        // store tags
        if(release.contains("store_tags"))
        {
            for(u32 t = 0; t < PEN_ARRAY_SIZE(StoreTags::names); ++t) {
                if(release["store_tags"].contains(StoreTags::names[t]) && release["store_tags"][StoreTags::names[t]])
                {
                    view->releases.store_tags[ri] |= (1<<t);
                }
            }
        }

        pen::thread_sleep_ms(1);
        view->releases.available_entries++;
    }
    
    view->threads_terminated++;
    return nullptr;
}

size_t get_folder_size_recursive(const pen::fs_tree_node& dir, const c8* root)
{
    size_t size = 0;
    for(u32 i = 0; i < dir.num_children; ++i)
    {
        Str path = "";
        path.appendf("%s/%s", root, dir.children[i].name);
        
        if(dir.children[i].num_children > 0)
        {
            size += get_folder_size_recursive(dir.children[i], path.c_str());
        }
        else
        {
            size += filesystem_getsize(path.c_str());
        }
    }
    
    return size;
}

void* data_cacher(void* userdata)
{
    // get view from userdata
    ReleasesView* view = (ReleasesView*)userdata;
    
    Str cache_dir = get_cache_path();
    
    // enum cache stats
    pen::fs_tree_node dir;
    pen::filesystem_enum_directory(cache_dir.c_str(), dir, 1, "**/*.*");
    view->data_ctx->cached_release_folders = 0;
    view->data_ctx->cached_release_bytes = 0;
    for(u32 i = 0; i < dir.num_children; ++i)
    {
        Str path = cache_dir;
        path.append(dir.children[i].name);
        
        if(dir.children[i].num_children > 0)
        {
            view->data_ctx->cached_release_folders++;
            view->data_ctx->cached_release_bytes += get_folder_size_recursive(dir.children[i], cache_dir.c_str());
        }
        else
        {
            pen::fs_tree_node release_dir;
            pen::filesystem_enum_directory(path.c_str(), release_dir);
            view->data_ctx->cached_release_folders++;
            view->data_ctx->cached_release_bytes += get_folder_size_recursive(release_dir, path.c_str());
        }
    }
        
    for(;;)
    {
        if(view->terminate) {
            break;
        }
        
        // waits on info loader thread
        for(size_t i = 0; i < view->releases.available_entries; ++i)
        {
            if(!(view->releases.flags[i] & EntryFlags::cache_url_requested)) {
                continue;
            }
            
            // cache art
            if(!view->releases.artwork_url[i].empty())
            {
                if(view->releases.artwork_filepath[i].empty())
                {
                    view->releases.artwork_filepath[i] = download_and_cache(view->releases.artwork_url[i], view->releases.id[i]);
                    view->releases.flags[i] |= EntryFlags::artwork_cached;
                }
            }
            
            // cache tracks
            if(!(view->releases.flags[i] & EntryFlags::tracks_cached))
            {
                if(view->releases.track_url_count[i] > 0 && view->releases.track_filepaths[i] == nullptr)
                {
                    view->releases.track_filepaths[i] = new Str[view->releases.track_url_count[i]];
                    
                    for(u32 t = 0; t < view->releases.track_url_count[i]; ++t)
                    {
                        view->releases.track_filepaths[i][t] = "";
                        Str fp = download_and_cache(view->releases.track_urls[i][t], view->releases.id[i]);
                        view->releases.track_filepaths[i][t] = fp;
                    }
                    
                    std::atomic_thread_fence(std::memory_order_release);
                    view->releases.flags[i] |= EntryFlags::tracks_cached;
                    view->releases.track_filepath_count[i] = view->releases.track_url_count[i];
                }
            }
        }
        
        pen::thread_sleep_ms(16);
    }
    
    // flag terminated
    view->threads_terminated++;
    return nullptr;
}

void* data_loader(void* userdata)
{
    // get view from userdata
    ReleasesView* view = (ReleasesView*)userdata;
    
    for(;;)
    {
        if(view->terminate) {
            break;
        }
        
        for(size_t i = 0; i < view->releases.available_entries; ++i)
        {
            // load art if cached and not loaded
            std::atomic_thread_fence(std::memory_order_acquire);
            
            if((view->releases.flags[i] & EntryFlags::artwork_cached) &&
               !(view->releases.flags[i] & EntryFlags::artwork_loaded) &&
               (view->releases.flags[i] & EntryFlags::artwork_requested))
            {
                view->releases.artwork_tcp[i] = load_texture_from_disk(view->releases.artwork_filepath[i]);
                
                std::atomic_thread_fence(std::memory_order_release);
                view->releases.flags[i] |= EntryFlags::artwork_loaded;
            }
        }
        
        pen::thread_sleep_ms(16);
    }
    
    view->threads_terminated++;
    return nullptr;
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
    u32         clear_screen;
    AppContext  ctx;

    ReleasesView* new_view(Page_t page, StoreView store_view)
    {
        ReleasesView* view = new ReleasesView;
        view->data_ctx = &ctx.data_ctx;
        view->page = page;
        view->scroll = vec2f(0.0f, ctx.w);
        view->store_view = store_view;
        
        // workers per view
        pen::thread_create(info_loader, 10 * 1024 * 1024, view, pen::e_thread_start_flags::detached);
        pen::thread_create(data_cacher, 10 * 1024 * 1024, view, pen::e_thread_start_flags::detached);
        pen::thread_create(data_loader, 10 * 1024 * 1024, view, pen::e_thread_start_flags::detached);
        
        return view;
    }

    StoreView store_view_from_store(Page_t page, const Store& store)
    {
        StoreView view;
        
        view.store_name = store.name;
        
        // view
        if(store.selected_view_index < store.view_search_names.size()) {
            view.selected_view = store.view_search_names[store.selected_view_index];
        }

        // sections
        for(u32 i = 0; i < store.section_search_names.size(); ++i) {
            if(store.selected_sections_mask & (1<<i)) {
                view.selected_sections.push_back(store.section_search_names[i]);
            }
        }
        
        return view;
    }

    ReleasesView* reload_view()
    {
        if(ctx.view)
        {
            auto store_view = store_view_from_store(ctx.view->page, ctx.store);
            return new_view(ctx.view->page, store_view);
        }
        
        return nullptr;
    }

    void change_store_view(Page_t page, const Store& store)
    {
        StoreView view = store_view_from_store(page, store);

        if(!view.store_name.empty() && !view.selected_view.empty() && view.selected_sections.size() > 0) {
            // first we add the current view into background views
            if(ctx.view && ctx.view->page == Page::feed)
            {
                ctx.back_view = ctx.view;
                ctx.background_views.insert(ctx.view);
            }
                
            // kick off a new view
            ctx.view = new_view(page, view);
        }
    }

    Store change_store(const Str& store_name)
    {
        Store output = {};
        if(ctx.stores.contains(store_name.c_str()))
        {
            auto& store = ctx.stores[store_name.c_str()];
            auto& views = store["views"];
            auto& section_search_names = store["sections"];
            auto& section_display_names = store["section_display_names"];
            
            for(auto& view : views.items())
            {
                output.view_search_names.push_back(view.key());
                
                std::string dn = view.value()["display_name"];
                output.view_display_names.push_back(dn.c_str());
            }
            
            for(auto& section : section_display_names)
            {
                std::string n = section;
                output.sections_display_names.push_back(n.c_str());
            }
            
            for(auto& section : section_search_names)
            {
                std::string n = section;
                output.section_search_names.push_back(n.c_str());
            }
            
            output.name = store_name;
            
            // now change the store feed
            change_store_view(Page::feed, output);
        }
        
        return output;
    }

    void cleanup_views()
    {
        std::vector<ReleasesView*> to_remove;
        
        for(auto& view : ctx.background_views)
        {
            if(view != ctx.back_view && view != ctx.view)
            {
                view->terminate = 1;
                if(view->threads_terminated == 3)
                {
                    auto& releases = view->releases;
                    for(size_t i = 0; i < releases.available_entries; ++i) {
                        // unload textures
                        if (releases.flags[i] & EntryFlags::artwork_loaded) {
                            if(releases.artwork_texture[i] != 0) {
                                // textures themseleves
                                pen::renderer_release_texture(releases.artwork_texture[i]);
                                releases.artwork_texture[i] = 0;
                            }
                            else
                            {
                                // texture preloaded from disk
                                free(releases.artwork_tcp[i].data);
                            }
                            memset(&releases.artwork_tcp, 0x0, sizeof(texture_creation_params));
                            releases.flags[i] &= ~EntryFlags::artwork_loaded;
                            releases.flags[i] &= ~EntryFlags::artwork_requested;
                        }
                        
                        // unload strings
                        if(view->releases.track_filepaths[i]) {
                            delete[] view->releases.track_filepaths[i];
                        }
                        
                        if(view->releases.track_names.data && view->releases.track_names[i]) {
                            delete[] view->releases.track_names[i];
                        }
                        
                        if(view->releases.track_urls[i]) {
                            delete[] view->releases.track_urls[i];
                        }
                    }
                    
                    // cleanup memory from the soa itself
                    free_components(view->releases);
                    
                    // add to remove list to preserve the set iterator
                    to_remove.push_back(view);
                }
            }
        }
        
        // erase view
        for(auto& rm : to_remove) {
            PEN_LOG("erasing view");
            ctx.background_views.erase(ctx.background_views.find(rm));
        }
    }

    void view_reload()
    {
        f32 reloady = (f32)ctx.w / k_top_pull_reload;
        
        // reload on drag
        static bool debounce = false;
        if(debounce)
        {
            if(!pen::input_is_mouse_down(PEN_MOUSE_L))
            {
                debounce = false;
            }
        }
        else
        {
            if(pen::input_is_mouse_down(PEN_MOUSE_L))
            {
                // check threshold
                if(ctx.view->scroll.y < reloady)
                {
                    if(ctx.reload_view == nullptr && ctx.view->page != Page::likes)
                    {
                        ctx.reload_view = reload_view();
                        debounce = true; // wait for debounce;
                    }
                }
            }
        }

        // reload anim if we have an empty view or are relaoding
        if(ctx.reload_view || ctx.view->releases.available_entries == 0)
        {
            ImGui::SetWindowFontScale(2.0f);
            
            // small padding
            f32 ss = ImGui::GetFontSize() * 2.0f;
            ImGui::Dummy(ImVec2(0.0f, ss));
            
            // spinner
            static f32 rot = 0.0f;
            auto x = ImGui::GetWindowSize().x * 0.5f;
            auto y = ImGui::GetCursorPos().y;
            ImGui::ImageRotated(IMG(ctx.spinner_texture), ImVec2(x, y), ImVec2(ss, ss), rot);
            rot += 1.0f/60.0f;
            
            ImGui::Dummy(ImVec2(0.0f, ss));
            ImGui::SetWindowFontScale(1.0f);
        }
        
        // if reloading wait until the new view has entries and then swap
        if(ctx.reload_view)
        {
            if(ctx.reload_view->releases.available_entries > 0)
            {
                // swap existing view with the new one and reset
                ctx.background_views.insert(ctx.view);
                ctx.view = ctx.reload_view;
                ctx.reload_view = nullptr;
            }
        }
    }

    void store_menu()
    {
        // early out until stores are loaded
        if(ctx.store.name.empty()) {
            return;
        }
        
        Page_t cur_page = ctx.view->page;
        if(cur_page != Page::likes)
        {
            // store page
            ImGui::SetWindowFontScale(k_text_size_h2);
            ImGui::Dummy(ImVec2(k_indent1, 0.0f));
            
            // store select
            ImGui::SameLine();
            ImGui::Text("%s:", ctx.store.name.c_str());
            ImVec2 store_menu_pos = ImGui::GetItemRectMin();
            store_menu_pos.y = ImGui::GetItemRectMax().y;
            
            if(ImGui::IsItemClicked()) {
                ImGui::OpenPopup("Store Select");
            }
            ImGui::SetNextWindowPos(store_menu_pos);
            
            if(ImGui::BeginPopup("Store Select")) {
                for(auto& item : ctx.stores.items()) {
                    const c8* store_name = item.key().c_str();
                    if(ImGui::MenuItem(item.key().c_str())) {
                        ctx.store = change_store(store_name);
                    }
                }
                ImGui::EndPopup();
            }
        }
    }

    void view_menu()
    {
        // view info
        Page_t cur_page = ctx.view->page;
        if(cur_page == Page::feed)
        {
            auto& store = ctx.store;
            if(!store.name.empty()) {
                // view name
                ImGui::SetWindowFontScale(k_text_size_h2);
                ImGui::SameLine();
                ImGui::Text("%s", store.view_display_names[store.selected_view_index].c_str());
                ImVec2 view_menu_pos = ImGui::GetItemRectMin();
                view_menu_pos.y = ImGui::GetItemRectMax().y;
                if(ImGui::IsItemClicked()) {
                    ImGui::OpenPopup("View Select");
                }
                
                // view menu
                ImGui::SetNextWindowPos(view_menu_pos);
                if(ImGui::BeginPopup("View Select")) {
                    for(u32 v = 0; v < store.view_display_names.size(); ++v) {
                        if(ImGui::MenuItem(store.view_display_names[v].c_str())) {
                            store.selected_view_index = v;
                            store.store_view.selected_view = store.view_search_names[v];
                            
                            change_store_view(Page::feed, store);
                        }
                    }
                    ImGui::EndPopup();
                }
                
                // create a string by concatonating sections
                Str sections_string = "";
                for(u32 section = 0; section < store.sections_display_names.size(); ++section) {
                    if(!sections_string.empty()) {
                        sections_string.append(" / ");
                    }
                    sections_string.append(store.sections_display_names[section].c_str());
                }
                
                // section name
                ImGui::Dummy(ImVec2(k_indent1, 0.0f));
                ImGui::SameLine();
                
                ImGui::SetWindowFontScale(k_text_size_body);
                ImGui::Text("%s", sections_string.c_str());
                ImVec2 section_menu_pos = ImGui::GetItemRectMin();
                section_menu_pos.y = ImGui::GetItemRectMax().y;
                if(ImGui::IsItemClicked()) {
                    ImGui::OpenPopup("Section Select");
                }
                
                // section menu
                ImGui::SetNextWindowPos(section_menu_pos);
                if(ImGui::BeginPopup("Section Select")) {
                    ImGui::SetWindowFontScale(k_text_size_h2);
                    for(u32 v = 0; v < store.sections_display_names.size(); ++v) {
                        Str menu_item_str = "";
                        u32 store_bit = (1<<v);
                        
                        // check mark
                        if(store.selected_sections_mask & store_bit) {
                            menu_item_str.append(ICON_FA_CHECK_SQUARE);
                            menu_item_str.append(" ");
                        }
                        
                        // menu item
                        menu_item_str.append(store.sections_display_names[v].c_str());
                        if(ImGui::MenuItem(menu_item_str.c_str())) {
                            if(store.selected_sections_mask & store_bit) {
                                store.selected_sections_mask &= ~store_bit;
                            }
                            else {
                                store.selected_sections_mask |= store_bit;
                            }
                            
                            change_store_view(Page::feed, store);
                        }
                    }
                    ImGui::EndPopup();
                }
                
                ImGui::SetWindowFontScale(k_text_size_body);
            }
        }
        else
        {
            // likes page
            ImGui::SetWindowFontScale(k_text_size_body);
        }
        
        // cleanup memory on old views
        cleanup_views();
    }

    bool lenient_button_tap(f32 padding)
    {
        ImVec2 bbmin = ImGui::GetItemRectMin();
        ImVec2 bbmax = ImGui::GetItemRectMax();
        
        vec2f vbmin = vec2f(bbmin.x, bbmin.y);
        vec2f vbmax = vec2f(bbmax.x, bbmax.y);
        vec2f mid = vbmin + ((vbmax - vbmin) * 0.5f);
        
        f32 d = dist(vec2f(ctx.tap_pos.x, ctx.tap_pos.y), mid);
        if(d < padding)
        {
            return true;
        }
        
        return false;
    }
    
    bool lenient_button_click(f32 padding, bool& debounce, bool debug = false)
    {
        auto& ms = pen::input_get_mouse_state();
        ImVec2 bbmin = ImGui::GetItemRectMin();
        ImVec2 bbmax = ImGui::GetItemRectMax();
        
        // debug
        vec2f vbmin = vec2f(bbmin.x, bbmin.y);
        vec2f vbmax = vec2f(bbmax.x, bbmax.y);
        vec2f mid = vbmin + ((vbmax - vbmin) * 0.5f);
        
        if(false)
        {
            ImGui::GetForegroundDrawList()->AddCircle(ImVec2(mid.x, mid.y), padding, 0xffff00ff);
            
            u32 col = 0xffff0000;
            
            f32 d = dist(vec2f(ms.x, ms.y), mid);
            if(d < padding)
            {
                col = 0xff0000ff;
                PEN_LOG("clicked 0");
            }
            
            ImGui::GetForegroundDrawList()->AddCircleFilled(ImVec2(ms.x, ms.y), 32.0f, col);
        }
        
        // need to wait on debounce
        if(debounce)
        {
            if(!ctx.touch_down)
            {
                debounce = false;
            }
            
            return false;
        }
        else
        {
            if(ctx.touch_down)
            {
                f32 d = dist(vec2f(ms.x, ms.y), mid);
                if(d < padding)
                {
                    debounce = true;
                    return true;
                }
            }
        }
        
        return false;
    }

    void header_menu()
    {
        ImGui::SetWindowFontScale(k_text_size_h1);
        ImGui::Dummy(ImVec2(k_indent1, 0.0f));
        ImGui::SameLine();
        
        if(ctx.view->page == Page::likes || ctx.view->page == Page::settings)
        {
            ImGui::Text("%s %s", ICON_FA_CHEVRON_LEFT, ctx.view->page == Page::likes ? "Likes" : "Settings");
            if(ImGui::IsItemClicked())
            {
                ctx.view = ctx.back_view;
            }
        }
        else
        {
            ImGui::Text("Dig");
        }
        
        // likes button on same line
        ImGui::SameLine();
        f32 offset = ImGui::CalcTextSize("%s", ICON_FA_HEART_O).y;
        ImGui::SetCursorPosX(ctx.w - offset * 3.0f);
        ImGui::Text("%s", ctx.view->page == Page::likes ? ICON_FA_HEART : ICON_FA_HEART_O);
        
        f32 rad = ctx.w * k_page_button_press_radius_ratio;
        
        static bool heart_debounce = false;
        if(lenient_button_click(rad, heart_debounce, true))
        {
            //change_view(Page::likes);
        }
        
        ImGui::SameLine();
        ImGui::Spacing();
        
        ImGui::SameLine();
        ImGui::Text("%s", ICON_FA_ELLIPSIS_H);
        
        static bool ellipsis_debounce = false;
        if(lenient_button_click(rad, ellipsis_debounce, true))
        {
            //change_view(Page::settings);
        }
        
        ImGui::SetWindowFontScale(k_text_size_body);
    }

    void release_feed()
    {
        f32 w = ctx.w;
        f32 h = ctx.h;
        
        // get latest releases
        auto& releases = ctx.view->releases;
        
        // releases
        ImGui::BeginChildEx("releases", 1, ImVec2(0, 0), false, ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse);
        auto current_window = ImGui::GetCurrentWindow();
        ctx.releases_window = current_window;
        
        // Add an empty dummy at the top
        ImGui::Dummy(ImVec2(w, w));
        
        ctx.top = -1;
        for(u32 r = 0; r < releases.available_entries; ++r)
        {
            auto title = releases.title[r];
            auto artist = releases.artist[r];
            
            // apply loads
            std::atomic_thread_fence(std::memory_order_acquire);
            if(releases.flags[r] & EntryFlags::artwork_loaded)
            {
                if(releases.artwork_texture[r] == 0)
                {
                    if(releases.artwork_tcp[r].data)
                    {
                        releases.artwork_texture[r] = pen::renderer_create_texture(releases.artwork_tcp[r]);
                        pen::memory_free(releases.artwork_tcp[r].data); // data is copied for the render thread. safe to delete
                        releases.artwork_tcp[r].data = nullptr;
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
                    if(ctx.top == -1)
                    {
                        ctx.top = r;
                    }
                }
            }
            
            // label and catalogue
            ImGui::SetWindowFontScale(k_text_size_h3);
            
            ImGui::Dummy(ImVec2(k_indent1, 0.0f));
            ImGui::SameLine();
            ImGui::TextWrapped("%s: %s", releases.label[r].c_str(), releases.cat[r].c_str());
            
            ImGui::SetWindowFontScale(k_text_size_body);
            
            // ..
            f32 scaled_vel = ctx.scroll_delta.x;
            
            // images
            if(releases.artwork_texture[r])
            {
                f32 h = (f32)w * ((f32)releases.artwork_tcp[r].height / (f32)releases.artwork_tcp[r].width);
                f32 spacing = 20.0f;
                                
                ImGui::BeginChildEx("rel", r+1, ImVec2((f32)w, h + 10.0f), false, 0);
                ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(spacing, 0.0));
                
                u32 num_images = std::max<u32>(1, releases.track_url_count[r]);
                f32 imgw = w + spacing;
                
                f32 max_scroll = (num_images * imgw) - imgw;
                for(u32 i = 0; i < num_images; ++i)
                {
                    if(i > 0)
                    {
                        ImGui::SameLine();
                    }
                    
                    ImGui::Image(IMG(releases.artwork_texture[r]), ImVec2((f32)w, h));
                    
                    if(ImGui::IsItemHovered() && pen::input_is_mouse_down(PEN_MOUSE_L))
                    {
                        if(!ctx.scroll_lock_y)
                        {
                            if(abs(ctx.scroll_delta.x) > k_drag_threshold && ctx.side_drag)
                            {
                                releases.flags[r] |= EntryFlags::dragging;
                                ctx.scroll_lock_x = true;
                            }
                            
                            releases.flags[r] |= EntryFlags::hovered;
                        }
                    }
                }
                
                if(!pen::input_is_mouse_down(PEN_MOUSE_L))
                {
                    releases.flags[r] &= ~EntryFlags::hovered;
                    if(abs(scaled_vel) < 1.0)
                    {
                        releases.flags[r] &= ~EntryFlags::dragging;
                    }
                }
                
                // stop drags if we no longer hover
                if(!(releases.flags[r] & EntryFlags::hovered))
                {
                    if(releases.flags[r] & EntryFlags::dragging)
                    {
                        ctx.scroll_delta.y = 0.0f;
                        releases.scrollx[r] -= scaled_vel;
                    }
                    
                    f32 target = releases.select_track[r] * imgw;
                    f32 ssx = releases.scrollx[r];
                    
                    if(!(releases.flags[r] & EntryFlags::transitioning))
                    {
                        if(ssx > target + (imgw/2) && releases.select_track[r]+1 < num_images)
                        {
                            ctx.scroll_delta.x = 0.0;
                            releases.select_track[r] += 1;
                            releases.flags[r] |= EntryFlags::transitioning;
                        }
                        else if(ssx < target - (imgw/2) && (ssize_t)releases.select_track[r]-1 >= 0)
                        {
                            ctx.scroll_delta.x = 0.0;
                            releases.select_track[r] -= 1;
                            releases.flags[r] |= EntryFlags::transitioning;
                        }
                        else
                        {
                            if(abs(scaled_vel) < 5.0)
                            {
                                releases.flags[r] |= EntryFlags::transitioning;
                            }
                        }
                    }
                    else
                    {
                        if(abs(ssx - target) < k_inertia_cutoff)
                        {
                            releases.scrollx[r] = target;
                            releases.flags[r] &= ~EntryFlags::transitioning;
                        }
                        else
                        {
                            if(abs(scaled_vel) < 5.0)
                            {
                                releases.scrollx[r] = lerp(ssx, target, k_snap_lerp);
                            }
                        }
                    }
                }
                else if (releases.flags[r] & EntryFlags::dragging)
                {
                    releases.scrollx[r] -= ctx.scroll_delta.x;
                    releases.scrollx[r] = std::max(releases.scrollx[r], 0.0f);
                    releases.scrollx[r] = std::min(releases.scrollx[r], max_scroll);
                    releases.flags[r] &= ~EntryFlags::transitioning;
                }
                
                ImGui::SetScrollX(releases.scrollx[r]);
                
                ImGui::PopStyleVar();
                ImGui::EndChild();
            }
            else
            {
                // TODO: this is not scrollable
                ImGui::Dummy(ImVec2(w, w));
            }
            
            // tracks
            ImGui::SetWindowFontScale(k_text_size_dots);
            s32 tc = releases.track_filepath_count[r];
            if(tc != 0)
            {
                auto ww = ImGui::GetWindowSize().x;
                auto tw = ImGui::CalcTextSize(ICON_FA_STOP_CIRCLE).x * releases.track_url_count[r] * 1.5f;
                ImGui::SetCursorPosX((ww - tw) * 0.5f);
                
                // dots
                for(u32 i = 0; i < releases.track_url_count[r]; ++i)
                {
                    if(i > 0)
                    {
                        ImGui::SameLine();
                    }
                    
                    u32 sel = releases.select_track[r];
                    if(i == sel)
                    {
                        if(ctx.top == r)
                        {
                            ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.8f, 0.3f, 0.0f, 1.0f));
                            ImGui::Text("%s", ICON_FA_PLAY);
                            ImGui::PopStyleColor();
                            
                            // load up the track
                            if(!(ctx.play_track_filepath == releases.track_filepaths[r][sel]))
                            {
                                ctx.play_track_filepath = releases.track_filepaths[r][sel];
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
            
            // likes / buy
            ImGui::SetWindowFontScale(k_text_size_body);
            
            ImGui::Spacing();
            ImGui::Indent();
            
            ImGui::SetWindowFontScale(k_text_size_h2);
                    
            f32 rad = ctx.w * k_release_button_tap_radius_ratio;
            
            ImGui::PushID("like");
            if(releases.flags[r] & EntryFlags::liked)
            {
                ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(225.0f/255.0f, 48.0f/255.0f, 108.0f/255.0f, 1.0f));
                ImGui::Text("%s", ICON_FA_HEART);
                if(lenient_button_tap(rad))
                {
                    pen::os_haptic_selection_feedback();
                    remove_like(releases.id[r]);
                    releases.flags[r] &= ~EntryFlags::liked;
                }
                ImGui::PopStyleColor();
            }
            else
            {
                ImGui::Text("%s", ICON_FA_HEART_O);
                if(lenient_button_tap(rad))
                {
                    pen::os_haptic_selection_feedback();
                    add_like(releases.id[r]);
                    releases.flags[r] |= EntryFlags::liked;
                }
            }
            f32 indent_x = ImGui::GetItemRectMin().x;
            ImGui::PopID();
            
            ImGui::SameLine();
            ImGui::Spacing();
            
            ImGui::SameLine();
            ImGui::PushID("buy");
            if(releases.store_tags[r] & StoreTags::preorder) {
                ImGui::Text("%s", ICON_FA_CALENDAR_PLUS_O);
            }
            else {
                ImGui::Text("%s", ICON_FA_CART_PLUS);
            }
            
            if(lenient_button_tap(rad)) {
                ctx.open_url_request = releases.link[r];
            }
            ImGui::PopID();
            
            if(releases.store_tags[r] & StoreTags::out_of_stock) {
                ImGui::SameLine();
                ImGui::Text("%s", ICON_FA_EXCLAMATION);
            }
            
            // mini hype icons
            ImGui::SetWindowFontScale(k_text_size_body);
        
            Str hype_icons = "";
            if(releases.store_tags[r] & StoreTags::has_charted) {
                hype_icons.append(ICON_FA_FIRE);
            }
            
            if(!(releases.store_tags[r] & StoreTags::out_of_stock)) {
                if(releases.store_tags[r] & StoreTags::has_been_out_of_stock) {
                    if(!hype_icons.empty()) {
                        hype_icons.append(" ");
                    }
                    hype_icons.append(ICON_FA_EXCLAMATION);
                }
            }
            
            ImGui::SameLine();
            f32 tw = ImGui::CalcTextSize(hype_icons.c_str()).x;
            auto ww = ImGui::GetWindowSize().x;
            ImGui::SetCursorPosX(ww - tw - indent_x);
            
            ImGui::Text("%s", hype_icons.c_str());
            
            // release info
            ImGui::TextWrapped("%s", artist.c_str());
            ImGui::TextWrapped("%s", title.c_str());
            
            // track name
            ImGui::SetWindowFontScale(k_text_size_track);
            u32 sel = releases.select_track[r];
            if(releases.track_name_count[r] > releases.select_track[r])
            {
                ImGui::TextWrapped("%s", releases.track_names[r][sel].c_str());
            }
            ImGui::SetWindowFontScale(k_text_size_body);
            
            ImGui::Unindent();
            
            ImGui::Spacing();
        }
        
        // couple of empty ones so we can reach the end of the feed
        ImGui::Dummy(ImVec2(w, w));
        ImGui::Dummy(ImVec2(w, w));
        
        // get scroll limit
        ctx.releases_scroll_maxy = ImGui::GetScrollMaxY() - w;
        
        ImGui::EndChild();
    }

    void audio_player()
    {
        auto& releases = ctx.view->releases;
        
        // audio player
        if(!ctx.mute)
        {
            static u32 si = -1;
            static u32 ci = -1;
            static u32 gi = -1;
            static bool started = false;
            
            if(ctx.top == -1)
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
                    ctx.play_track_filepath = "";
                }
            }
            
            if(ctx.play_track_filepath.length() > 0 && ctx.invalidate_track)
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
                    u32 next = releases.select_track[ctx.top] + 1;
                    if(next < releases.track_filepath_count[ctx.top])
                    {
                        ctx.scroll_delta.x = 0.0;
                        releases.select_track[ctx.top] += 1;
                        releases.flags[ctx.top] |= EntryFlags::transitioning;
                    }
                }
                else if(gstate.play_state == put::e_audio_play_state::playing)
                {
                    started = true;
                }
            }
        }
    }

    void issue_data_requests()
    {
        auto& releases = ctx.view->releases;
        
        // TODO: make the ranges data driven
        // make requests for data
        if(ctx.top != -1)
        {
            s32 range_start = max(ctx.top - 10, 0);
            s32 range_end = min<s32>(ctx.top + 10, (s32)releases.available_entries);
            
            for(size_t i = 0; i < releases.available_entries; ++i)
            {
                if(i >= range_start && i <= range_end) {
                    if(releases.artwork_texture[i] == 0) {
                        releases.flags[i] |= EntryFlags::artwork_requested;
                    }
                }
                else if (releases.flags[i] & EntryFlags::artwork_loaded){
                    if(releases.artwork_texture[i] != 0) {
                        // proper release
                        pen::renderer_release_texture(releases.artwork_texture[i]);
                        releases.artwork_texture[i] = 0;
                        releases.flags[i] &= ~EntryFlags::artwork_loaded;
                        releases.flags[i] &= ~EntryFlags::artwork_requested;
                    }
                }
            }
            std::atomic_thread_fence(std::memory_order_release);
        }
        
        // make requests for cache
        if(ctx.top != -1)
        {
            s32 range_start = max(ctx.top - 100, 0);
            s32 range_end = min<s32>(ctx.top + 100, (s32)releases.available_entries);
            
            for(size_t i = 0; i < releases.available_entries; ++i)
            {
                if(i >= range_start && i <= range_end) {
                    releases.flags[i] |= EntryFlags::cache_url_requested;
                }
                else {
                    releases.flags[i] &= ~EntryFlags::cache_url_requested;
                }
            }
        }
    }

    void issue_open_url_requests()
    {
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
    }

    void apply_taps()
    {
        constexpr u32 k_tap_threshold_ms = 500;
        static u32 s_tap_timer = k_tap_threshold_ms;
        
        // rest tap pos
        ctx.tap_pos = vec2f(FLT_MAX);
        
        if(pen::input_is_mouse_down(PEN_MOUSE_L))
        {
            s_tap_timer -= 16;
        }
        else
        {
            if(s_tap_timer < k_tap_threshold_ms)
            {
                auto ms = pen::input_get_mouse_state();
                ctx.tap_pos = vec2f(ms.x, ms.y);
            }
            
            s_tap_timer = k_tap_threshold_ms;
        }
    }

    void apply_drags()
    {
        f32 w = ctx.w;
        
        f32 miny = (f32)w / k_top_pull_pad;
                
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
            if(ctx.view->scroll.y < w) {
                ctx.view->scroll.y = lerp(ctx.view->scroll.y, (f32)w, 0.5f);
            }
            
            // release locks
            ctx.scroll_lock_x = false;
            ctx.scroll_lock_y = false;
        }
        
        // clamp to top
        if(ctx.view->scroll.y <= miny) {
            ctx.view->scroll.y = miny;
            ctx.scroll_delta = vec2f::zero();
        }
        
        f32 dx = abs(dot(ctx.scroll_delta, vec2f::unit_x()));
        f32 dy = abs(dot(ctx.scroll_delta, vec2f::unit_y()));
        
        ctx.side_drag = false;
        if(dx > dy)
        {
            ctx.side_drag = true;
        }
        
        if(!ctx.side_drag && abs(ctx.scroll_delta.y) > k_drag_threshold)
        {
            ctx.scroll_lock_y = true;
        }
        
        // only not if already scrolling x
        if(!ctx.scroll_lock_x)
        {
            ctx.view->scroll.y -= ctx.scroll_delta.y;
            ImGui::SetScrollY((ImGuiWindow*)ctx.releases_window, ctx.view->scroll.y);
        }
        
        // clamp to bottom
        if(ctx.view->scroll.y > ctx.releases_scroll_maxy) {
            ctx.view->scroll.y = std::min(ctx.view->scroll.y, ctx.releases_scroll_maxy);
        }
    }

    void settings_menu()
    {
        ImGui::SetWindowFontScale(k_text_size_h2);
        
        if(ImGui::CollapsingHeader("Help"))
        {
            ImGui::Text("%s - Released / Buy Link", ICON_FA_CART_PLUS);
            ImGui::Text("%s - Preorder / Buy Link", ICON_FA_CALENDAR_PLUS_O);
            ImGui::Text("%s - Sold Out", ICON_FA_EXCLAMATION);
            ImGui::Text("%s - Has Charted", ICON_FA_FIRE);
            ImGui::Text("%s - Has Previously Sold Out", ICON_FA_EXCLAMATION);
        }
        
        if(ImGui::CollapsingHeader("Cache"))
        {
            float mb = (((float)ctx.data_ctx.cached_release_bytes.load()) / 1024.0 / 1024.0);
            ImGui::Text("Cached Releases: %i", ctx.data_ctx.cached_release_folders.load());
            ImGui::Text("Cached Data: %f(mb)", mb);
        }
        
        ImGui::SetWindowFontScale(k_text_size_body);
    }

    void main_window()
    {
        s32 w, h;
        pen::window_get_size(w, h);
        ImGui::SetNextWindowPos(ImVec2(0.0f, 0.0f));
        ImGui::SetNextWindowSize(ImVec2((f32)w, (f32)h));
        
        ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(0.0f, 0.0f));
        
        ImGui::Begin("Main", nullptr, ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoScrollbar);
        
        ImGui::Dummy(ImVec2(0.0f, ctx.status_bar_height));
        
        // ui menus
        header_menu();
        
        // pages
        if(ctx.view->page == Page::settings)
        {
            settings_menu();
        }
        else
        {
            store_menu();
            view_menu();
            view_reload();
            release_feed();
        }
        
        ImGui::PopStyleVar(4);
        ImGui::End();
    }

    void apply_clicks()
    {
        if(pen::input_is_mouse_down(PEN_MOUSE_L))
        {
            ctx.touch_down = true;
        }
        else
        {
            ctx.touch_down = false;
        }
    }

    void main_update()
    {
        apply_taps();
        apply_drags();
        apply_clicks();
        audio_player();
        issue_data_requests();
        issue_open_url_requests();
    }

    void setup_stores()
    {
        // grab stores
        if(ctx.stores.empty())
        {
            ctx.data_ctx.stores.mutex.lock();
            ctx.stores = ctx.data_ctx.stores.dict;
            ctx.data_ctx.stores.mutex.unlock();
        }
        
        // initialise store
        if(ctx.stores.size() > 0) {
            if(ctx.store.name.empty()) {
                ctx.store = change_store("redeye");
            }
        }
    }

    loop_t user_update()
    {
        pen::timer_start(frame_timer);
        pen::renderer_new_frame();
        
        // clear backbuffer
        pen::renderer_set_targets(PEN_BACK_BUFFER_COLOUR, PEN_BACK_BUFFER_DEPTH);
        pen::renderer_clear(clear_screen);

        put::dev_ui::new_frame();
        
        // after boot, we might need to wait for a small time until stores have downloaded and synced
        setup_stores();
        
        // main code entry
        if(ctx.view)
        {
            main_window();
            main_update();
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

    void* user_setup(void* params)
    {
        // unpack the params passed to the thread and signal to the engine it ok to proceed
        pen::job_thread_params* job_params = (pen::job_thread_params*)params;
        s_thread_info = job_params->job_info;
        pen::semaphore_post(s_thread_info->p_sem_continue, 1);

        // force audio in silent mode
        pen::os_ignore_slient();
        
        // get window size
        pen::window_get_size(ctx.w, ctx.h);
        
        // base ratio taken from iphone11 max dimension
        f32 font_ratio = 42.0f / 1125.0f;
        f32 font_pixel_size = ctx.w * font_ratio;
        
        // intialise pmtech systems
        pen::jobs_create_job(put::audio_thread_function, 1024 * 10, nullptr, pen::e_thread_start_flags::detached);
        dev_ui::init(dev_ui::default_pmtech_style(), font_pixel_size);
        
        curl::init();
                
        // init context
        ctx.status_bar_height = pen::os_get_status_bar_portrait_height();

        // permanent workers
        pen::thread_create(registry_loader, 10 * 1024 * 1024, &ctx.data_ctx, pen::e_thread_start_flags::detached);
        pen::thread_create(user_data_thread, 10 * 1024 * 1024, ctx.view, pen::e_thread_start_flags::detached);

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
        
        // imgui style
        ImGui::StyleColorsLight(); // white
        
        // screen ratio based spacing and indents
        ImGui::GetStyle().IndentSpacing = ctx.w * (ImGui::GetStyle().IndentSpacing / k_promax_11_w);
        ImGui::GetStyle().ItemSpacing = ImVec2(
                ctx.w * (ImGui::GetStyle().ItemSpacing.x / k_promax_11_w),
                ctx.h * (ImGui::GetStyle().ItemSpacing.y / k_promax_11_h)
        );
        ImGui::GetStyle().ItemInnerSpacing = ImVec2(
                ctx.w * (ImGui::GetStyle().ItemInnerSpacing.x / k_promax_11_w),
                ctx.h * (ImGui::GetStyle().ItemInnerSpacing.y / k_promax_11_h)
        );
        
        // spinner
        ctx.spinner_texture = put::load_texture("data/images/spinner.dds");

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
} // namespace

void* pen::user_entry( void* params )
{
    return PEN_THREAD_OK;
}
