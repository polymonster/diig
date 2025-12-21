#include "api_key.h"

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
#include "maths/maths.h"

#define SIMPLEWEBP_IMPLEMENTATION
#include "simplewebp.h"

#define STB_IMAGE_IMPLEMENTATION
#include "stb/stb_image.h"

#include <fstream>
#include <thread>
#include <chrono>

constexpr bool k_force_login = false;
constexpr bool k_force_streamed_audio = false;

using namespace put;
using namespace pen;

void settings_menu();
void* data_cache_enumerate(void* userdata);

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

// yes hacky
static Str s_tokenid = "";
Str append_auth(Str url) {
    url.appendf("&auth=%s", s_tokenid.c_str());
    return url;
}

namespace curl
{
    constexpr size_t k_min_alloc = 1024;

    struct DataBuffer {
        u8*         data = nullptr;
        size_t      size = 0;
        size_t      alloc_size = 0;
        CURLcode    code = CURLE_OK;
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
            struct curl_slist *headers = NULL;
            
            headers = curl_slist_append(headers, "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36");

            curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
            curl_easy_setopt(curl, CURLOPT_URL, url);
            curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
            curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, false);
            curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_function);
            curl_easy_setopt(curl, CURLOPT_WRITEDATA, &db);

            res = curl_easy_perform(curl);
            db.code = res;

            if(res != CURLE_OK)
            {
                PEN_LOG("curl_easy_perform() failed: %s\n", curl_easy_strerror(res));
                db.data = nullptr;
            }

            curl_easy_cleanup(curl);
        }

        return db;
    }

    nlohmann::json request(const c8* url, const c8* data, CURLcode& res) {

        CURL *curl;
        DataBuffer db = {};

        curl = curl_easy_init();

        if(curl) {
            curl_easy_setopt(curl, CURLOPT_URL, url);
            curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
            curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, false);
            curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_function);
            curl_easy_setopt(curl, CURLOPT_WRITEDATA, &db);

            if(data) {
                curl_easy_setopt(curl, CURLOPT_POSTFIELDS, data);
            }

            struct curl_slist* headers = nullptr;
            headers = curl_slist_append(headers, "Content-Type: application/json");
            curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

            res = curl_easy_perform(curl);

            if(res != CURLE_OK)
            {
                PEN_LOG("curl_easy_perform() failed: %s\n", curl_easy_strerror(res));
                db.data = nullptr;
            }

            curl_easy_cleanup(curl);
        }

        if(db.data)
        {
            try {
                return nlohmann::json::parse((const c8*)db.data);
            }
            catch(...) {
                return {};
            }
        }

        return {};
    }

    nlohmann::json patch(const c8* url, const c8* data, CURLcode& res) {
        CURL *curl;
        DataBuffer db = {};

        curl = curl_easy_init();

        if(curl) {
            curl_easy_setopt(curl, CURLOPT_URL, url);
            curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
            curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, false);
            curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_function);
            curl_easy_setopt(curl, CURLOPT_WRITEDATA, &db);
            curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PATCH");
            curl_easy_setopt(curl, CURLOPT_POSTFIELDS, data);

            struct curl_slist* headers = nullptr;
            headers = curl_slist_append(headers, "Content-Type: application/json");
            curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

            res = curl_easy_perform(curl);

            if(res != CURLE_OK)
            {
                PEN_LOG("curl_easy_perform() failed: %s\n", curl_easy_strerror(res));
                db.data = nullptr;
            }

            curl_easy_cleanup(curl);
        }

        if(db.data)
        {
            try {
                return nlohmann::json::parse((const c8*)db.data);
            }
            catch(...) {
                return {};
            }
        }

        return {};
    }

    Str url_with_key(const c8* url) {
        Str urlk = url;
        urlk.appendf("?key=%s", k_api_key);
        return urlk;
    }
}

f64 get_like_timestamp_time()
{
    // this offset fixes an issue where the original timestamp code was based on mach absolute time
    // it means any new additions after this release will appear in timestamp order, but older likes will be
    // ordered in groups but not full consecutive
    constexpr f64 offset = 1696155367;
    return offset + (f64)(std::chrono::system_clock::now().time_since_epoch() / std::chrono::milliseconds(1));
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

bool check_cache_hit(const Str& url, Str releaseid)
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
        return false;
    }

    return true;
}

bool check_audio_file(const Str& path)
{
    FILE* f = fopen(path.c_str(), "rb");
    if(f)
    {
        fseek(f, 0, SEEK_END);
        size_t size = ftell(f);
        rewind(f);
        
        if(size >= 4)
        {
            char buf[4];
            fread(&buf[0], 1, 4, f);
            if(buf[0] == '<' && buf[1] == '!') //html
            {
                return false;
            }
            if(buf[0] == '<' && buf[1] == '?') //xml
            {
                return false;
            }
        }
        
        fclose(f);
    }
    
    return true;
}

Str download_and_cache(const Str& url, Str releaseid, bool validate = false)
{
    Str url2 = pen::str_replace_string(url, "MED-MED", "MED");
    url2 = pen::str_replace_string(url2, "MED-BIG", "BIG");

    Str filepath = pen::str_replace_string(url, "https://", "");
    filepath = pen::str_replace_chars(filepath, '/', '_');

    Str dir = get_cache_path();
    dir.appendf("/%s", releaseid.c_str());

    // filepath
    Str path = dir;
    path.appendf("/%s", filepath.c_str());
    filepath = path;

    // force remove mp3
    filepath = pen::str_replace_string(filepath, ".mp3", "");

    // check if file already exists
    u32 mtime = 0;
    pen::filesystem_getmtime(filepath.c_str(), mtime);
    if(mtime == 0)
    {
        // mkdirs
        pen::os_create_directory(dir.c_str());

        // download
        auto db = new curl::DataBuffer;
        *db = curl::download(url2.c_str());

        // try parse json to validate
        bool error_response = false;
        if(validate) {
            if(db->data) {
                if(strncmp((const c8*)db->data, "error code", 10) == 0) {
                    PEN_LOG("error with url: %s\n", url2.c_str());
                    error_response = true;
                }
                if(strncmp((const c8*)db->data, "<!DOCTYPE html>", 15) == 0) {
                    PEN_LOG("error with url: %s\n", url2.c_str());
                }
            }
        }

        // stash
        if(db->data)
        {
            if(!error_response)
            {
                FILE* fp = fopen(filepath.c_str(), "wb");
                if(fp)
                {
                    fwrite(db->data, db->size, 1, fp);
                    fclose(fp);
                }
            }

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
    // check file exists
    FILE* ff = fopen(filepath.c_str(), "rb");
    if(!ff)
    {
        PEN_LOG("failed to load texture file at: %s", filepath.c_str());
        pen::texture_creation_params tcp = {};
        tcp.data = nullptr;
        return tcp;
    }
    
    // check file size
    fseek(ff, 0, SEEK_END);
    size_t size = ftell(ff);
    rewind(ff);
    
    if(size < 4)
    {
        PEN_LOG("texture has unexpected size: %s %zu", filepath.c_str(), size);
        pen::texture_creation_params tcp = {};
        tcp.data = nullptr;
        return tcp;
    }
    
    // check cc for webp
    char cc[4];
    fread(&cc[0], 1, 4, ff);
    fclose(ff);
    
    s32 w, h, c;
    stbi_uc* rgba = nullptr;
    
    if(cc[0] == 'R' && cc[1] == 'I' && cc[2] == 'F' && cc[3] == 'F')
    {
        // webp
        size_t width, height;
        simplewebp *swebp;
        simplewebp_load_from_filename(filepath.c_str(), NULL, &swebp);
        simplewebp_get_dimensions(swebp, &width, &height);
        
        rgba = (stbi_uc*)malloc(width * height * 4);
        simplewebp_decode(swebp, rgba, NULL);
        simplewebp_unload(swebp);
        
        w = (s32)width;
        h = (s32)height;
        c = 4;
    }
    else
    {
        // oldschool image
        rgba = stbi_load(filepath.c_str(), &w, &h, &c, 4);
        c = 4;
    }
        
    pen::texture_creation_params tcp;
    tcp.width = w;
    tcp.height = h;
    tcp.format = PEN_TEX_FORMAT_RGBA8_UNORM;
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
            async_dict.status = Status::e_ready;

            // check for firebase errors
            if(async_dict.dict.size() == 1) {
                for(auto& item : async_dict.dict.items()) {
                    if(item.key() == "error") {
                        PEN_LOG("error: %s", async_dict.dict.dump(4).c_str());
                        async_dict.status = Status::e_not_initialised;
                    }
                }
            }
        }
        catch(...) {
            async_dict.status = Status::e_not_initialised;
        }
        async_dict.mutex.unlock();
    }

    Str filepath = get_persistent_filepath(cache_filename, true);
    if(async_dict.status == Status::e_ready)
    {
        // cache async
        std::thread cache_thread([j, filepath]() {
            FILE* fp = fopen(filepath.c_str(), "wb");
            if(fp)
            {
                fwrite(j.data, j.size, 1, fp);
                fclose(fp);
                free(j.data); // cleanup
            }
            else
            {
                PEN_LOG("failed to write: %s", filepath.c_str());
            }
        });
        cache_thread.detach();
    }
    else
    {
        // check for a cached item
        u32 mtime = 0;
        pen::filesystem_getmtime(filepath.c_str(), mtime);
        if(mtime > 0) {
            PEN_LOG("fallback to cache: %s", filepath.c_str());

            // ensures it's valid
            async_dict.mutex.lock();
            try {
                async_dict.dict = nlohmann::json::parse(std::ifstream(filepath.c_str()));
                async_dict.status = Status::e_ready;

                // check for firebase errors
                if(async_dict.dict.size() == 1) {
                    for(auto& item : async_dict.dict.items()) {
                        if(item.key() == "error") {
                            PEN_LOG("cached error: %s", async_dict.dict.dump(4).c_str());
                            async_dict.status = Status::e_not_initialised;
                        }
                    }
                }
            } catch (...) {
                async_dict.status = Status::e_not_available;
            }
            async_dict.mutex.unlock();
        }
        else
        {
            PEN_LOG("no cache for: %s", filepath.c_str());
            async_dict.status = Status::e_not_available;
        }

        // cleanup
        free(j.data);
    }

    return async_dict.status == Status::e_ready;
}

void* registry_loader(void* userdata)
{
    DataContext* ctx = (DataContext*)userdata;
    
    Str store_url = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/stores.json?&timeout=5s";
    store_url = append_auth(store_url);

    // fetch stores
    fetch_json_cache(
        store_url.c_str(),
        "stores.json",
        ctx->stores
    );

    return nullptr;
};

void* user_data_thread(void* userdata)
{
    DataContext* ctx = (DataContext*)userdata;

    // grab user data from disk
    Str dig_dir = os_get_persistent_data_directory();
    dig_dir.append("/dig");

    Str user_data_filepath = dig_dir;
    user_data_filepath.append("/user_data.json");

    u32 mtime = 0;
    pen::filesystem_getmtime(user_data_filepath.c_str(), mtime);
    nlohmann::json user_data_cache = {};
    if(mtime > 0)
    {
        std::ifstream f(user_data_filepath.c_str());
        user_data_cache = nlohmann::json::parse(f);
    }

    bool auth_cloud = false;
    bool fetch_cloud = true;
    bool update_cloud = false;

    Str userid = "";
    Str tokenid = "";
    Str user_url = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/users/";
    Str likes_url = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/likes/";

    nlohmann::json update_payload = {};

    // merge cache into the user_data
    ctx->user_data.mutex.lock();
    ctx->user_data.dict.merge_patch(user_data_cache);
    ctx->user_data.mutex.unlock();

    ctx->user_data.status = Status::e_initialised;

    for(;;)
    {
        // authenticate
        if(!auth_cloud) {
            if(ctx->auth.status == Status::e_ready) {
                if(ctx->auth.dict.contains("localId") && ctx->auth.dict.contains("idToken")) {
                    // set tokens
                    userid = ((std::string)ctx->auth.dict["localId"]).c_str();
                    tokenid = ((std::string)ctx->auth.dict["idToken"]).c_str();
                    auth_cloud = true;
                }
            }
        }

        // if authenticated
        if(auth_cloud) {

            // sync lost likes from global likes
            static bool sync_likes = false;
            if(sync_likes)
            {
                // get all likes
                CURLcode code;

                Str url = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/likes.json";
                url.appendf("?auth=%s", tokenid.c_str());

                auto global_likes = curl::request(
                    url.c_str(),
                    nullptr,
                    code
                );

                for(auto& like : global_likes.items()) {
                    for(auto& user : like.value().items()) {
                        if(user.key() == std::string(userid.c_str()))
                        {
                            if(user.value() > 0) {
                                add_like(like.key());
                            }
                        }
                    }
                }

                sync_likes = false;
            }

            if(fetch_cloud) {
                Str url = user_url;
                url.appendf("%s.json", userid.c_str());
                url.appendf("?auth=%s", tokenid.c_str());

                curl::DataBuffer fetch = curl::download(url.c_str());
                if(fetch.data)
                {
                    try {
                        auto cloud_user_data = nlohmann::json::parse(fetch.data);
                        if(cloud_user_data.contains("timestamp")) {
                            ctx->user_data.dict.merge_patch(cloud_user_data);

                        }
                    }
                    catch(...) {
                        // pass
                    }
                }

                fetch_cloud = false;
            }

            // or update
            if(update_cloud) {
                Str url = user_url;
                url.appendf("%s.json", userid.c_str());
                url.appendf("?auth=%s", tokenid.c_str());

                std::string payload_str = update_payload.dump(4).c_str();

                CURLcode code;
                auto response = curl::patch(url.c_str(), payload_str.c_str(), code);

                // sync likes
                for(auto& like : update_payload["likes"].items()) {
                    // construct url for the release in likes section
                    Str like_release_url = likes_url;
                    like_release_url.appendf("%s.json", like.key().c_str());
                    like_release_url.appendf("?auth=%s", tokenid.c_str());

                    // unpack bool or numerical like
                    bool like_val = false;
                    if(like.value().is_boolean()) {
                        like_val = like.value();
                    }
                    else if(like.value().is_number()) {
                        like_val = like.value() > 0.0f;
                    }

                    // patch payload for user specific like
                    Str like_payload = "";
                    like_payload.appendf("{\"%s\": %i }", userid.c_str(), (s32)like_val);

                    CURLcode code;
                    auto response = curl::patch(like_release_url.c_str(), like_payload.c_str(), code);
                }

                update_cloud = false;
            }
        }

        // if we have changes from the main thread, we can write to disk
        ctx->user_data.mutex.lock();
        if(ctx->user_data.status == Status::e_invalidated) {
            // timestamp for merges
            ctx->user_data.dict["timestamp"] = get_like_timestamp_time();

            std::string user_data_str = ctx->user_data.dict.dump(4);
            FILE* fp = fopen(user_data_filepath.c_str(), "w");
            fwrite(user_data_str.c_str(), user_data_str.length(), 1, fp);
            fclose(fp);

            // and also update the cloud
            update_payload = ctx->user_data.dict;
            update_cloud = true;

            ctx->user_data.status = Status::e_ready;
        }
        ctx->user_data.mutex.unlock();

        pen::thread_sleep_ms(66);
    }

    return nullptr;
}

inline Str safe_str(nlohmann::json& j, const c8* key, const Str& default_value)
{
    if(j.contains(key))
    {
        if(j[key].is_string())
        {
            return ((std::string)j[key]).c_str();
        }
    }

    return default_value;
}

void update_likes_registry() {
    // kick off a job to update the likes cache, (get up-to-date out of stock info etc)
    std::thread cache_thread([]() {
        auto update_likes_registry = nlohmann::json();
        auto likes = get_likes();
        for(auto& like : likes.items()) {
            // like value might be bool or number
            bool like_true = false;
            f32 timestamp = 0.0f;
            if(like.value().is_boolean()) {
                like_true = like.value();
            }
            else if(like.value().is_number()) {
                like_true = true;
                timestamp = like.value();
            }

            if(like_true) {
                Str search_url = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/releases.json";
                search_url.appendf("?orderBy=\"$key\"&equalTo=\"%s\"&timeout=1s", like.key().c_str());
                search_url = append_auth(search_url);

                auto db = curl::download(search_url.c_str());
                if(db.data)
                {
                    nlohmann::json release;
                    try {
                        release = nlohmann::json::parse(db.data);
                        update_likes_registry[like.key()] = release[like.key()];
                    }
                    catch(...) {
                        //
                    }
                    free(db.data);
                }
                else {
                }
            }
        }

        // write to disk
        PEN_LOG("updated likes registry");
        Str filepath = get_persistent_filepath("likes_feed.json", true);
        FILE* fp = fopen(filepath.c_str(), "wb");
        std::string j = update_likes_registry.dump();
        fwrite(j.c_str(), j.length(), 1, fp);
        fclose(fp);
    });
    cache_thread.detach();
}

void* releases_view_loader(void* userdata)
{
    // get view from userdata
    ReleasesView* view = (ReleasesView*)userdata;
    auto& store_view = view->store_view;

    nlohmann::json releases_registry;
    std::vector<ChartItem> view_chart;

    // track added items to avoid duplicates that appear in multiple genre sections
    std::map<std::string, size_t> added_map;

    if(view->page == Page::feed) {
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
            search_url.appendf("?orderBy=\"%s\"&startAt=0&timeout=10s", index_on.c_str());
            search_url = append_auth(search_url);

            AsyncDict async_registry;
            fetch_json_cache(
                search_url.c_str(),
                cache_file.c_str(),
                async_registry
            );

            // TODO: handle total failure case
            if(async_registry.status != Status::e_ready)
            {
                PEN_LOG("error: fetching %s", index_on.c_str());
                view->status = Status::e_not_available;
                view->threads_terminated++;
                return nullptr;
            }

            // add stored?
            for(auto& item : async_registry.dict.items())
            {
                auto val = item.value();

                if(added_map.find(item.key()) != added_map.end()) {
                    // if already in map, update using the min chart pos
                    auto vp = added_map[item.key()];
                    view_chart[vp].pos = std::min<u32>((u32)val[index_on.c_str()], (u32)view_chart[vp].pos);

                    // update map pos
                    u32 hh = PEN_HASH(item.key().c_str());
                    view->release_pos[hh] = view_chart[vp].pos;
                }
                else {
                    // add new entry to view_chart
                    added_map.insert({
                        item.key(),
                        view_chart.size()
                    });

                    view_chart.push_back({
                        item.key(),
                        val[index_on.c_str()]
                    });

                    // insert hashed
                    u32 hh = PEN_HASH(item.key().c_str());
                    view->release_pos.insert({
                        hh,
                        val[index_on.c_str()]
                    });
                }
            }

            releases_registry.merge_patch(async_registry.dict);
        }
    }
    else {

        // look in cache
        Str filepath = get_persistent_filepath("likes_feed.json", true);
        auto likes_registry = nlohmann::json();
        try {
            likes_registry = nlohmann::json::parse(std::ifstream(filepath.c_str()));

        } catch (...) {
            // ..
        }
        
        auto likes = get_likes();
        if(!likes.empty() && likes.size() != likes_registry.size()) {
            PEN_LOG("populate likes from feed");

            // populate likes feed from the db
            for(auto& like : likes.items()) {

                // like value might be bool or number
                bool like_true = false;
                f64 timestamp = 0.0f;
                if(like.value().is_boolean()) {
                    like_true = like.value();
                }
                else if(like.value().is_number()) {
                    like_true = true;
                    timestamp = like.value();
                }

                if(like_true) {
                    Str search_url = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/releases.json";
                    search_url.appendf("?orderBy=\"$key\"&equalTo=\"%s\"&timeout=1s", like.key().c_str());
                    search_url = append_auth(search_url);

                    auto db = curl::download(search_url.c_str());
                    if(db.data)
                    {
                        nlohmann::json release;
                        try {
                            release = nlohmann::json::parse(db.data);
                            releases_registry[like.key()] = release[like.key()];

                            view_chart.push_back({
                                like.key(),
                                timestamp
                            });
                        }
                        catch(...) {
                            //
                        }

                        free(db.data);
                    }
                    else {
                    }
                }
            }

            // write to cache
            if(view_chart.size() == likes.size())
            {
                PEN_LOG("caching likes registry");

                // cache async
                std::thread cache_thread([releases_registry, filepath]() {
                    FILE* fp = fopen(filepath.c_str(), "wb");
                    std::string j = releases_registry.dump();
                    fwrite(j.c_str(), j.length(), 1, fp);
                    fclose(fp);
                });
                cache_thread.detach();
            }
        }
        else {
            // populate likes feed from cache
            PEN_LOG("populate likes from cache");

            // use likes registry
            releases_registry = likes_registry;

            for(auto& like : likes.items()) {

                // like value might be bool or number
                bool like_true = false;
                f64 timestamp = 0.0f;
                if(like.value().is_boolean()) {
                    like_true = like.value();
                }
                else if(like.value().is_number()) {
                    like_true = true;
                    timestamp = like.value();
                }

                // add to view chart
                view_chart.push_back({
                    like.key(),
                    timestamp
                });
            }

            // trigger an update
            update_likes_registry();
        }

        // fallback to cache even if it mismatches with like count
        if(view_chart.size() == 0)
        {
            // look in cache
            try {
                releases_registry = nlohmann::json::parse(std::ifstream(filepath.c_str()));

                // add to view chart
                for(auto& item : releases_registry.items()) {
                    view_chart.push_back({
                        item.key(),
                        0
                    });
                }

            }
            catch (...) {
                view->status = Status::e_not_available;
            }
        }
    }

    if(view_chart.empty())
    {
        view->status = Status::e_not_available;
        view->threads_terminated++;
        return nullptr;
    }

    // view is ready to cleanup
    view->release_pos_status = Status::e_ready;

    // sort the items
    if(view->page == Page::likes) {
        // likes are sorted descending by timestamp
        std::sort(begin(view_chart),end(view_chart),[](ChartItem a, ChartItem b) {return a.pos > b.pos; });
    }
    else {
        // feed is sorted ascending by position
        std::sort(begin(view_chart),end(view_chart),[](ChartItem a, ChartItem b) {return a.pos < b.pos; });
    }

    // make space
    resize_components(view->releases, view_chart.size());

    Str likes_url = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/likes/";

    for(auto& entry : view_chart)
    {
        u32 ri = (u32)view->releases.available_entries;
        auto release = releases_registry[entry.index];

        // simple info
        view->releases.artist[ri] = safe_str(release, "artist", "");
        view->releases.title[ri] = safe_str(release, "title", "");
        view->releases.link[ri] = safe_str(release, "link", "");
        view->releases.label[ri] = safe_str(release, "label", "");
        view->releases.cat[ri] = safe_str(release, "cat", "");
        view->releases.store[ri] = safe_str(release, "store", "");
        view->releases.label_link[ri] = safe_str(release, "label_link", "");

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

        view->releases.id[ri] = safe_str(release, "id", "");
        view->releases.key[ri] = entry.index;
        
        // assign artwork url
        if(release["artworks"].size() > 0)
        {
            size_t art_index = 0;
            if(view->releases.store[ri] == "yoyaku")
            {
                art_index = 1; // 400x400
            }
            else if(view->releases.store[ri] == "redeye")
            {
                // this is required to fixup the fact -0.jpg may not exist
                // redeye <guid>-1.jpg is preferable
                size_t i = 0;
                for(auto& art : release["artworks"])
                {
                    std::string url = art;
                    if(url.find("-1.jpg") != -1)
                    {
                        art_index = i;
                        break;
                    }
                    ++i;
                }
            }
            
            if(art_index < release["artworks"].size()) {
                view->releases.artwork_url[ri] = release["artworks"][art_index];
            }
            else
            {
                view->releases.artwork_url[ri] = "";
            }
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

        // check local likes
        if(has_like(view->releases.key[ri]))
        {
            view->releases.flags[ri] |= EntityFlags::liked;
        }

        // count cloud likes... removing feature, needs improving
        /*
        Str like_release_url = likes_url;
        like_release_url.appendf("%s.json?timeout=25ms", view->releases.key[ri].c_str());
        CURLcode code;
        auto likes = curl::request(like_release_url.c_str(), nullptr, code);
        view->releases.like_count[ri] = 0;
        for(auto& like : likes) {
            if(like > 0) {
                view->releases.like_count[ri]++;
            }
        }
        */

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

struct DirInfo {
    Str    path = "";
    size_t size = 0;
    u32    mtime = -1;
};

DirInfo get_folder_info_recursive(const pen::fs_tree_node& dir, const c8* root) {
    DirInfo output = {};
    for(u32 i = 0; i < dir.num_children; ++i)
    {
        Str path = "";
        path.appendf("%s/%s", root, dir.children[i].name);

        if(dir.children[i].num_children > 0)
        {
            DirInfo ii = get_folder_info_recursive(dir.children[i], path.c_str());
            output.size += ii.size;
            output.mtime = min(ii.mtime, output.mtime);
        }
        else
        {
            output.size = filesystem_getsize(path.c_str());

            u32 mtime = 0;
            filesystem_getmtime(path.c_str(), mtime);
            output.mtime = min(mtime, output.mtime);
        }
    }

    output.path = root;
    return output;
}

void* data_cache_fetch(void* userdata) {

    // get view from userdata
    ReleasesView* view = (ReleasesView*)userdata;

    Str cache_dir = get_cache_path();

    for(;;) {
        if(view->terminate) {
            break;
        }

        // waits on info loader thread
        for(size_t i = 0; i < view->releases.available_entries; ++i) {
            if(!(view->releases.flags[i] & EntityFlags::cache_url_requested)) {
                continue;
            }

            // cache art
            if(!view->releases.artwork_url[i].empty()) {
                if(view->releases.artwork_filepath[i].empty()) {
                    view->releases.artwork_filepath[i] = download_and_cache(view->releases.artwork_url[i], view->releases.key[i], true);
                    view->releases.flags[i] |= EntityFlags::artwork_cached;
                }
            }

            // cache tracks
            if(!(view->releases.flags[i] & EntityFlags::tracks_cached)) {
                if(view->releases.track_url_count[i] > 0 && view->releases.track_filepaths[i] == nullptr) {
                    view->releases.track_filepaths[i] = new Str[view->releases.track_url_count[i]];
                    for(u32 t = 0; t < view->releases.track_url_count[i]; ++t) {
                        view->releases.track_filepaths[i][t] = "";
                        if(!k_force_streamed_audio)
                        {
                            Str fp = download_and_cache(view->releases.track_urls[i][t], view->releases.key[i], true);
                            
                            if(check_audio_file(fp))
                            {
                                view->releases.track_filepaths[i][t] = fp;
                            }
                            else
                            {
                                remove(fp.c_str());
                            }
                        }
                        else
                        {
                            //
                            view->releases.track_filepaths[i][t] = view->releases.track_urls[i][t];
                        }
                    }
                    std::atomic_thread_fence(std::memory_order_release);
                    view->releases.flags[i] |= EntityFlags::tracks_cached;
                    view->releases.track_filepath_count[i] = view->releases.track_url_count[i];
                }
            }


            // early out
            if(view->terminate) {
                break;
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

    for(;;) {
        if(view->terminate) {
            break;
        }

        for(size_t i = 0; i < view->releases.available_entries; ++i) {
            // load art if cached and not loaded
            std::atomic_thread_fence(std::memory_order_acquire);
            if((view->releases.flags[i] & EntityFlags::artwork_cached) &&
               !(view->releases.flags[i] & EntityFlags::artwork_loaded) &&
               (view->releases.flags[i] & EntityFlags::artwork_requested)) {
                view->releases.artwork_tcp[i] = load_texture_from_disk(view->releases.artwork_filepath[i]);
                
                if(view->releases.artwork_tcp[i].data)
                {
                    std::atomic_thread_fence(std::memory_order_release);
                    view->releases.flags[i] |= EntityFlags::artwork_loaded;
                }
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

    template<typename T>
    T get_user_setting(const c8* key, T default_value) {
        T return_value = default_value;
        ctx.data_ctx.user_data.mutex.lock();
        if(ctx.data_ctx.user_data.dict.contains(key)) {
            return_value = ctx.data_ctx.user_data.dict[key];
        }
        ctx.data_ctx.user_data.mutex.unlock();
        return return_value;
    }

    template<typename T>
    void set_user_setting(const c8* key, T value) {
        ctx.data_ctx.user_data.mutex.lock();
        ctx.data_ctx.user_data.dict[key] = value;
        ctx.data_ctx.user_data.mutex.unlock();
        ctx.data_ctx.user_data.status = Status::e_invalidated;
    }

    ReleasesView* new_view(Page_t page, StoreView store_view) {
        ReleasesView* view = new ReleasesView;
        view->data_ctx = &ctx.data_ctx;
        view->page = page;
        view->scroll = vec2f(0.0f, ctx.w);
        view->store_view = store_view;

        // workers per view
        view->thread_mem[0] = pen::thread_create(releases_view_loader, 10 * 1024 * 1024, view, pen::e_thread_start_flags::detached);
        view->thread_mem[1] = pen::thread_create(data_cache_enumerate, 10 * 1024 * 1024, view, pen::e_thread_start_flags::detached);
        view->thread_mem[2] = pen::thread_create(data_cache_fetch, 10 * 1024 * 1024, view, pen::e_thread_start_flags::detached);
        view->thread_mem[3] = pen::thread_create(data_loader, 10 * 1024 * 1024, view, pen::e_thread_start_flags::detached);

        return view;
    }

    StoreView store_view_from_store(Page_t page, const Store& store) {
        StoreView view;

        view.store_name = store.name;

        // view
        if(store.selected_view_index < store.view_search_names.size()) {
            view.selected_view = store.view_search_names[store.selected_view_index];
        }

        // sections or sectionless
        if(store.view_sectionless[store.selected_view_index])
        {
            view.selected_sections.push_back("sectionless");
        }
        else
        {
            // sections
            for(u32 i = 0; i < store.section_search_names.size(); ++i) {
                if(store.selected_sections_mask & (1<<i)) {
                    view.selected_sections.push_back(store.section_search_names[i]);
                }
            }
        }

        return view;
    }

    ReleasesView* reload_view() {
        if(ctx.view)
        {
            auto store_view = store_view_from_store(ctx.view->page, ctx.store);
            return new_view(ctx.view->page, store_view);
        }

        return nullptr;
    }

    void change_page(Page_t page) {
        // first we add the current view into background views
        if(ctx.view && ctx.view->page == Page::feed) {
            ctx.back_view = ctx.view;
            ctx.background_views.insert(ctx.view);
        }

        // kick off a new view
        ctx.view = new_view(page, {});
        ctx.reload_view = nullptr;
    }

    void change_store_view(Page_t page, const Store& store) {
        StoreView view = store_view_from_store(page, store);

        if(!view.store_name.empty() && !view.selected_view.empty()) {
            // first we add the current view into background views
            if(ctx.view && ctx.view->page == Page::feed) {
                ctx.back_view = ctx.view;
                ctx.background_views.insert(ctx.view);
            }

            // kick off a new view
            ctx.view = new_view(page, view);
            ctx.reload_view = nullptr;

            // update store prefs
            update_store_prefs(store.name, view.selected_view, view.selected_sections);
        }
    }

    void apply_user_store_prefs(const Str& store_name, Store& store) {
        // prev prefs
        auto user_data = ctx.data_ctx.user_data.dict;
        ctx.data_ctx.user_data.mutex.lock();

        if (ctx.data_ctx.user_data.dict.contains("stores") &&
            ctx.data_ctx.user_data.dict["stores"].contains(store_name.c_str()))
        {
            // grab user store prefs
            auto& store_prefs = ctx.data_ctx.user_data.dict["stores"][store_name.c_str()];

            // sections
            std::vector<std::string> section_preference;
            if (store_prefs.contains("sections")) {
                section_preference = ctx.data_ctx.user_data.dict["stores"][store_name.c_str()]["sections"];
            }

            // view
            std::string view_preference;
            if (store_prefs.contains("view")) {
                view_preference = ctx.data_ctx.user_data.dict["stores"][store_name.c_str()]["view"];
            }
            
            // check sections are valid and still exist
            for(ssize_t i = section_preference.size() - 1; i >= 0; --i)
            {
                bool found = false;
                for(auto& sec : store.section_search_names)
                {
                    if(sec == section_preference[i])
                    {
                        found = true;
                        break;
                    }
                }
                
                if(!found)
                {
                    section_preference.erase(section_preference.begin() + i);
                }
            }
            
            // add all sections
            if(section_preference.size() == 0)
            {
                for(auto& sec : store.section_search_names)
                {
                    section_preference.push_back(sec.c_str());
                }
            }

            // set section mask
            if(section_preference.size() > 0)
            {
                store.selected_sections_mask = 0;
                for(u32 i = 0; i < store.section_search_names.size(); ++i)
                {
                    auto pos = std::find(
                        begin(section_preference),
                        end(section_preference),
                        store.section_search_names[i].c_str()
                    );

                    if(pos != end(section_preference))
                    {
                        u32 x = (u32)(pos - begin(section_preference));
                        store.selected_sections_mask |= (1<<x);
                    }
                }
            }

            // find view index
            auto pos = std::find(
                begin(store.view_search_names),
                end(store.view_search_names),
                view_preference.c_str()
            );

            if(pos != end(store.view_search_names)) {
                store.selected_view_index = (u32)(pos - begin(store.view_search_names));
            }
        }

        ctx.data_ctx.user_data.mutex.unlock();
    }

    Store change_store(const Str& store_name) {
        Store output = {};
        if(ctx.stores.contains(store_name.c_str()))
        {
            auto& store = ctx.stores[store_name.c_str()];
            auto& views = store["views"];
            auto& section_search_names = store["sections"];
            auto& section_display_names = store["section_display_names"];

            // hardcoded priority order
            static const c8* k_view_order[] = {
                "new_releases",
                "weekly_chart",
                "monthly_chart"
            };
            
            std::vector<std::string> store_view_order;
            if(store.contains("view_order"))
            {
                store_view_order = store["view_order"];
            }
            else
            {
                for(auto v : k_view_order)
                    store_view_order.push_back(v);
            }

            // add view priority order
            for(auto v : store_view_order) {
                if(views.contains(v)) {
                    output.view_search_names.push_back(v);
                    std::string dn = views[v]["display_name"];
                    output.view_display_names.push_back(dn.c_str());
                    
                    views[v].contains("sectionless") ?
                        output.view_sectionless.push_back(1):
                        output.view_sectionless.push_back(0);
                }
            }

            // add remaining views
            for(auto& view : views.items())
            {
                // skip prioritised
                bool exists = false;
                for(auto& v : store_view_order) {
                    if(std::string(v) == view.key()) {
                        exists = true;
                    }
                }
                if(exists) {
                    continue;
                }

                // add view
                output.view_search_names.push_back(view.key());
                std::string dn = view.value()["display_name"];
                output.view_display_names.push_back(dn.c_str());
                
                view.value().contains("sectionless") ?
                    output.view_sectionless.push_back(1):
                    output.view_sectionless.push_back(0);
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

            apply_user_store_prefs(store_name, output);

            // now change the store feed
            update_last_store(store_name);
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
                if(view->threads_terminated == k_num_threads_per_view)
                {
                    auto& releases = view->releases;

                    for(size_t i = 0; i < releases.available_entries; ++i) {
                        // unload textures
                        if (releases.flags[i] & EntityFlags::artwork_loaded) {
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
                            memset(&releases.artwork_tcp[i], 0x0, sizeof(texture_creation_params));
                            releases.flags[i] &= ~EntityFlags::artwork_loaded;
                            releases.flags[i] &= ~EntityFlags::artwork_requested;
                        }

                        // unload strings
                        if(view->releases.track_filepaths[i]) {
                            for(u32 t = 0; t < view->releases.track_filepath_count[i]; ++t) {
                                view->releases.track_filepaths[i][t].clear();
                            }
                            delete[] view->releases.track_filepaths[i];
                        }

                        if(view->releases.track_names.data && view->releases.track_names[i]) {
                            for(u32 t = 0; t < view->releases.track_name_count[i]; ++t) {
                                view->releases.track_names[i][t].clear();
                            }
                            delete[] view->releases.track_names[i];
                        }

                        if(view->releases.track_urls[i]) {
                            for(u32 t = 0; t < view->releases.track_url_count[i]; ++t) {
                                view->releases.track_urls[i][t].clear();
                            }
                            delete[] view->releases.track_urls[i];
                        }

                        // unload strings
                        releases.id[i].clear();
                        releases.artist[i].clear();
                        releases.title[i].clear();
                        releases.link[i].clear();
                        releases.label[i].clear();
                        releases.cat[i].clear();
                        releases.store[i].clear();
                        releases.artwork_url[i].clear();
                        releases.label_link[i].clear();
                    }

                    // cleanup memory from the soa itself
                    free_components(view->releases);

                    // freeup the thread mem
                    for(u32 t = 0; t < k_num_threads_per_view; ++t) {
                        free(view->thread_mem[t]);
                    }

                    // add to remove list to preserve the set iterator
                    to_remove.push_back(view);
                }
            }
        }

        // erase view
        for(auto& rm : to_remove) {
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
        if(ctx.view->status == Status::e_not_available) {
            // small padding
            f32 ss = ImGui::GetFontSize() * 2.0f;
            ImGui::Dummy(ImVec2(0.0f, ss));

            ImGui::TextCentred("No items...");
        }
        else if(ctx.reload_view || ctx.view->releases.available_entries == 0) {
            ImGui::SetWindowFontScale(2.0f);

            // small padding
            f32 ss = ImGui::GetFontSize() * 2.0f;
            ImGui::Dummy(ImVec2(0.0f, ss));

            // spinner
            auto x = ImGui::GetWindowSize().x * 0.5f;
            auto y = ImGui::GetCursorPos().y;
            ImGui::ImageRotated(IMG(ctx.spinner_texture), ImVec2(x, y), ImVec2(ss, ss), ctx.loading_rot);

            ImGui::Dummy(ImVec2(0.0f, ss));
            ImGui::SetWindowFontScale(1.0f);
        }

        // if reloading wait until the new view has entries and then swap
        if(ctx.reload_view)
        {
            if(ctx.reload_view->releases.available_entries > 0)
            {
                PEN_LOG("triggered a reload view");

                // swap existing view with the new one and reset
                ctx.background_views.insert(ctx.view);
                ctx.view = ctx.reload_view;
                ctx.reload_view = nullptr;
            }

            // TODO: handle failure
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

                // sections
                if(!store.view_sectionless[store.selected_view_index])
                {
                    // create a string by concatonating sections
                    Str sections_string = "";
                    u32 concatonated = 0;
                    for(u32 section = 0; section < store.sections_display_names.size(); ++section) {
                        if(store.selected_sections_mask & (1<<section))
                        {
                            if(++concatonated > 2)
                            {
                                sections_string.append(" + More...");
                                break;
                            }

                            if(!sections_string.empty()) {
                                sections_string.append(" / ");
                            }
                            sections_string.append(store.sections_display_names[section].c_str());
                        }
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
                            bool selected = store.selected_sections_mask & store_bit;

                            // menu item
                            menu_item_str.append(store.sections_display_names[v].c_str());
                            if(ImGui::Checkbox(menu_item_str.c_str(), &selected)) {
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

        if(ctx.view->page == Page::likes || ctx.view->page == Page::settings)
        {
            ImGui::Dummy(ImVec2(k_indent2, 0.0f));
            ImGui::SameLine();
            
            ImGui::Text("%s %s", ICON_FA_CHEVRON_LEFT, ctx.view->page == Page::likes ? "Likes" : "Settings");
            if(ImGui::IsItemClicked())
            {
                ctx.view = ctx.back_view;
            }
        }
        else
        {
            ImGui::Dummy(ImVec2(k_indent1, 0.0f));
            ImGui::SameLine();
            ImGui::Text("diig");
        }

        // likes button on same line
        ImGui::SameLine();

        f32 spacing = ImGui::GetStyle().ItemSpacing.x;
        f32 text_size = ImGui::CalcTextSize(ICON_FA_HEART).x;
        f32 offset = ((text_size + spacing) * 2.0) + k_indent2;

        ImGui::SetCursorPosX(ctx.w - offset);
        ImGui::Text("%s", ctx.view->page == Page::likes ? ICON_FA_HEART : ICON_FA_HEART_O);

        f32 rad = ctx.w * k_page_button_press_radius_ratio;

        if(lenient_button_tap(rad) && !ctx.scroll_lock_x && ! ctx.scroll_lock_y)
        {
            change_page(Page::likes);
        }

        ImGui::SameLine();
        ImGui::Spacing();

        ImGui::SameLine();
        ImGui::Text("%s", ICON_FA_BARS);

        // options menu button
        static bool s_debounce_menu = false;
        if(!s_debounce_menu) {
            if(lenient_button_tap(rad) && !ctx.scroll_lock_x && ! ctx.scroll_lock_y) {
                if(ImGui::IsPopupOpen("Options Menu")) {
                    ImGui::CloseCurrentPopup();
                    s_debounce_menu = true;
                }
                else {
                    ImGui::OpenPopup("Options Menu");
                }
            }
        }

        if(!pen::input_is_mouse_down(PEN_MOUSE_L)) {
            s_debounce_menu = false;
        }

        // options menu popup
        ImGui::SetWindowFontScale(k_text_size_h2);

        f32 s = ctx.w - offset * 2.0f;
        ImVec2 options_menu_pos = ImVec2(s, ImGui::GetCursorPosY());
        ImGui::SetNextWindowPos(options_menu_pos);
        ImGui::SetNextWindowSize(ImVec2(s, 0.0f));
        if(ImGui::BeginPopup("Options Menu")) {

            // user name
            if(!ctx.username.empty())
            {
                ImGui::SetWindowFontScale(k_text_size_body);
                ImGui::Text("%s", ctx.username.c_str());
                ImGui::Separator();
            }

            ImGui::SetWindowFontScale(k_text_size_body);

            if(ImGui::MenuItem("Settings")) {
                change_page(Page::settings);
            }

            if(ctx.show_debug) {
                if(ImGui::MenuItem("Hide Debug")) {
                    ctx.show_debug = false;
                }
            }
            else {
                if(ImGui::MenuItem("Show Debug")) {
                    ctx.show_debug = true;
                }
            }

            // log out
            if(!ctx.auth_response.empty()) {
                ImGui::Separator();
                if(ImGui::MenuItem("Log Out")) {
                    ctx.view->page = Page::login_or_signup;
                    audio_player_stop_existing();
                }
            }

            ImGui::EndPopup();
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

            // track the start y pos of the item
            f32 starty = ImGui::GetCursorPos().y;
            f32 scrolly = ImGui::GetScrollY();

            // skip items off the bottom
            if(starty - scrolly > h * 10.0f) {
                break;
            }

            // assign release pos
            releases.posy[r] = starty;

            // skip items we have passed with a dummy
            if(releases.sizey[r] > 0.0f)
            {
                if(starty + releases.sizey[r] - scrolly < 0.0f) {
                    ImGui::Dummy(ImVec2(0.0f, releases.sizey[r]));
                    continue;
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

            // debug display ID
            if(ctx.show_debug) {
                ImGui::SetWindowFontScale(k_text_size_nerds);
                ImGui::Dummy(ImVec2(k_indent1, 0.0f));
                ImGui::SameLine();
                ImGui::Text("(%s)", releases.key[r].c_str());
            }

            // display store for likes
            if(ctx.view->page == Page::likes) {
                ImGui::SetWindowFontScale(k_text_size_body);
                ImGui::Dummy(ImVec2(k_indent1, 0.0f));
                ImGui::SameLine();
                ImGui::Text("%s", releases.store[r].c_str());
            }

            // label and catalogue
            ImGui::SetWindowFontScale(k_text_size_h3);

            ImGui::Dummy(ImVec2(k_indent1, 0.0f));
            ImGui::SameLine();
            
            if(releases.cat[r].empty())
            {
                ImGui::TextWrapped("%s", releases.label[r].c_str());
            }
            else
            {
                ImGui::TextWrapped("%s: %s", releases.label[r].c_str(), releases.cat[r].c_str());
            }

            // TODO: open label link on tap
            /*
            if(ImGui::IsItemClicked()) {
                ctx.open_url_request = releases.label_link[r];
            }
            */

            ImGui::SetWindowFontScale(k_text_size_body);

            // ..
            f32 scaled_vel = ctx.scroll_delta.x;

            // images or placeholder
            u32 tex = ctx.white_label_texture;
            f32 texh = w;

            if(releases.artwork_texture[r])
            {
                tex = releases.artwork_texture[r];
                texh = (f32)w * ((f32)releases.artwork_tcp[r].height / (f32)releases.artwork_tcp[r].width);
            }

            if(tex)
            {
                f32 spacing = 20.0f;

                ImGui::BeginChildEx("rel", r+1, ImVec2((f32)w, texh + 10.0f), false, 0);
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

                    ImGui::Image(IMG(tex), ImVec2((f32)w, texh));

                    if(ImGui::IsItemHovered() && pen::input_is_mouse_down(PEN_MOUSE_L))
                    {
                        if(!ctx.scroll_lock_y)
                        {
                            if(abs(ctx.scroll_delta.x) > k_drag_threshold && ctx.side_drag)
                            {
                                releases.flags[r] |= EntityFlags::dragging;
                                ctx.scroll_lock_x = true;
                            }

                            releases.flags[r] |= EntityFlags::hovered;
                        }
                    }
                }

                if(!pen::input_is_mouse_down(PEN_MOUSE_L))
                {
                    releases.flags[r] &= ~EntityFlags::hovered;
                    if(abs(scaled_vel) < 1.0)
                    {
                        releases.flags[r] &= ~EntityFlags::dragging;
                    }
                }

                // stop drags if we no longer hover
                if(!(releases.flags[r] & EntityFlags::hovered))
                {
                    if(releases.flags[r] & EntityFlags::dragging)
                    {
                        ctx.scroll_delta.y = 0.0f;
                        releases.scrollx[r] -= scaled_vel;
                    }

                    f32 target = releases.select_track[r] * imgw;
                    f32 ssx = releases.scrollx[r];

                    if(!(releases.flags[r] & EntityFlags::transitioning))
                    {
                        if(ssx > target + (imgw/2) && releases.select_track[r]+1 < num_images)
                        {
                            ctx.scroll_delta.x = 0.0;
                            releases.select_track[r] += 1;
                            releases.flags[r] |= EntityFlags::transitioning;
                        }
                        else if(ssx < target - (imgw/2) && (ssize_t)releases.select_track[r]-1 >= 0)
                        {
                            ctx.scroll_delta.x = 0.0;
                            releases.select_track[r] -= 1;
                            releases.flags[r] |= EntityFlags::transitioning;
                        }
                        else
                        {
                            if(abs(scaled_vel) < 5.0)
                            {
                                releases.flags[r] |= EntityFlags::transitioning;
                            }
                        }
                    }
                    else
                    {
                        if(abs(ssx - target) < k_inertia_cutoff)
                        {
                            releases.scrollx[r] = target;
                            releases.flags[r] &= ~EntityFlags::transitioning;
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
                else if (releases.flags[r] & EntityFlags::dragging)
                {
                    releases.scrollx[r] -= ctx.scroll_delta.x;
                    releases.scrollx[r] = std::max(releases.scrollx[r], 0.0f);
                    releases.scrollx[r] = std::min(releases.scrollx[r], max_scroll);
                    releases.flags[r] &= ~EntityFlags::transitioning;
                }

                ImGui::SetScrollX(releases.scrollx[r]);

                ImGui::PopStyleVar();
                ImGui::EndChild();
            }
            else
            {
                // should never reach this case
                ImGui::Dummy(ImVec2(w, w));
            }

            // tracks
            ImGui::SetWindowFontScale(k_text_size_dots);
            s32 tc = releases.track_filepath_count[r];

            s32 valid_audio = 0;
            if(tc > 0)
            {
                for(u32 i = 0; i < releases.track_url_count[r]; ++i)
                {
                    if(!releases.track_filepaths[r][i].empty())
                    {
                        valid_audio++;
                    }
                }
            }
            
            if(tc != 0 && valid_audio > 0)
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
                    
                    // handle missing individual tracks
                    auto icon = ICON_FA_STOP_CIRCLE;
                    if(releases.track_filepaths[r][i].empty())
                    {
                        icon = ICON_FA_TIMES_CIRCLE;
                    }
                    
                    // auto move to next track if one is empty or invalid
                    if(ctx.top == r)
                    {
                        if(releases.track_filepaths[r][sel].empty())
                        {
                            sel++;
                            ctx.audio_ctx.invalidate_track = true;

                            if(sel >= releases.track_url_count[r])
                            {
                                sel = 0;
                            }

                            releases.select_track[r] = sel;
                        }
                    }

                    if(i == sel)
                    {
                        if(ctx.top == r)
                        {
                            ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.8f, 0.3f, 0.0f, 1.0f));
                            ImGui::Text("%s", ICON_FA_PLAY);
                            ImGui::PopStyleColor();

                            // load up the track
                            if(!(ctx.audio_ctx.play_track_filepath == releases.track_filepaths[r][sel]))
                            {
                                ctx.audio_ctx.play_track_filepath = releases.track_filepaths[r][sel];
                                ctx.audio_ctx.invalidate_track = true;
                            }
                        }
                        else
                        {
                            ImGui::Text("%s", icon);
                        }
                    }
                    else
                    {
                        ImGui::Text("%s", icon);
                    }
                }
            }
            else
            {
                auto ww = ImGui::GetWindowSize().x;

                if(releases.track_url_count[r] == 0 || valid_audio == 0)
                {
                    // no audio
                    ImGui::SetCursorPosX(ww * 0.5f);
                    ImGui::Text("%s", ICON_FA_TIMES_CIRCLE);
                }
                else
                {
                    f32 tw = ImGui::CalcTextSize("....").x;
                    ImGui::SetCursorPosX((ww - tw) * 0.5f);

                    Str dd = ".";
                    for(u32 d = 0; d < ctx.loading_dots; ++d) {
                        dd.append(".");
                    }
                    ImGui::Text("%s", dd.c_str());
                }
            }

            // likes / buy
            ImGui::SetWindowFontScale(k_text_size_body);

            ImGui::Spacing();
            ImGui::Indent();

            ImGui::SetWindowFontScale(k_text_size_h2);

            f32 rad = ctx.w * k_release_button_tap_radius_ratio;

            ImGui::PushID("like");
            bool scrolling = ctx.scroll_lock_x || ctx.scroll_lock_y;
            if(releases.flags[r] & EntityFlags::liked)
            {
                ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(225.0f/255.0f, 48.0f/255.0f, 108.0f/255.0f, 1.0f));
                ImGui::Text("%s", ICON_FA_HEART);
                if(!scrolling && lenient_button_tap(rad))
                {
                    pen::os_haptic_selection_feedback();
                    remove_like(releases.key[r]);
                    releases.flags[r] &= ~EntityFlags::liked;
                }
                ImGui::PopStyleColor();
            }
            else
            {
                ImGui::Text("%s", ICON_FA_HEART_O);
                if(!scrolling && lenient_button_tap(rad))
                {
                    pen::os_haptic_selection_feedback();
                    add_like(releases.key[r]);
                    releases.flags[r] |= EntityFlags::liked;
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

            if(!scrolling && lenient_button_tap(rad)) {
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

            if(releases.store_tags[r] & StoreTags::low_stock) {
                hype_icons.append(ICON_FA_THERMOMETER_QUARTER);
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

            // like count
            if(releases.like_count[r] > 0) {
                ImGui::SetWindowFontScale(k_text_size_nerds);
                if(releases.like_count[r] > 1) {
                    ImGui::Text("%i likes", releases.like_count[r]);
                }
                else if(!(releases.flags[r] & EntityFlags::liked)) {
                    ImGui::Text("%i like", releases.like_count[r]);
                }
                ImGui::SetWindowFontScale(k_text_size_body);
            }

            // release info
            if(!artist.empty()) {
                ImGui::TextWrapped("%s", artist.c_str());
            }

            if(!title.empty()) {
                ImGui::TextWrapped("%s", title.c_str());
            }

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

            f32 endy = ImGui::GetCursorPos().y;

            releases.sizey[r] = endy - starty;
        }

        // couple of empty ones so we can reach the end of the feed
        ImGui::Dummy(ImVec2(w, w));
        ImGui::Dummy(ImVec2(w, w));

        // get scroll limit
        ctx.releases_scroll_maxy = ImGui::GetScrollMaxY() - w;
        ctx.scroll_pos_y = ImGui::GetScrollY();

        ImGui::EndChild();
    }

    void set_now_playing_artwork(void* data, u32 row_pitch, u32 depth_pitch, u32 block_size)
    {
        pen::music_set_now_playing_artwork(data, row_pitch / block_size, depth_pitch / row_pitch, 8, row_pitch);
    }

    void issue_data_requests()
    {
        auto& releases = ctx.view->releases;

        // make requests for data
        if(ctx.top != -1) {
            s32 range_start = max<s32>(ctx.top - k_ram_cache_range, 0);
            s32 range_end = min<s32>(ctx.top + k_ram_cache_range, (s32)releases.available_entries);

            for(size_t i = 0; i < releases.available_entries; ++i)
            {
                if(i >= range_start && i <= range_end) {
                    if(releases.artwork_texture[i] == 0) {
                        releases.flags[i] |= EntityFlags::artwork_requested;
                    }
                }
                else if (releases.flags[i] & EntityFlags::artwork_loaded){
                    if(releases.artwork_texture[i] != 0) {
                        // proper release
                        pen::renderer_release_texture(releases.artwork_texture[i]);
                        releases.artwork_texture[i] = 0;
                        releases.flags[i] &= ~EntityFlags::artwork_loaded;
                        releases.flags[i] &= ~EntityFlags::artwork_requested;
                    }
                }
            }
            std::atomic_thread_fence(std::memory_order_release);
        }

        // make requests for cache
        if(ctx.top != -1) {
            s32 range_start = max<s32>(ctx.top - k_disk_cache_min_range, 0);
            s32 range_end = min<s32>(ctx.top + k_disk_cache_min_range, (s32)releases.available_entries);

            for(size_t i = 0; i < releases.available_entries; ++i) {
                if(i >= range_start && i <= range_end) {
                    releases.flags[i] |= EntityFlags::cache_url_requested;
                }
                else {
                    releases.flags[i] &= ~EntityFlags::cache_url_requested;
                }
            }
        }

        // apply loads
        std::atomic_thread_fence(std::memory_order_acquire);
        for(size_t r = 0; r < releases.available_entries; ++r) {
            if(releases.flags[r] & EntityFlags::artwork_loaded) {
                if(releases.artwork_texture[r] == 0) {
                    if(releases.artwork_tcp[r].data) {
                        releases.artwork_texture[r] = pen::renderer_create_texture(releases.artwork_tcp[r]);
                        pen::memory_free(releases.artwork_tcp[r].data); // data is copied for the render thread. safe to delete
                        releases.artwork_tcp[r].data = nullptr;
                    }
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
            ctx.view->target_scroll_y = 0; // disable next release auto lerp
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

        // apply lerp to next release target
        if(ctx.view->target_scroll_y) {
            ctx.view->scroll.y = lerp(ctx.view->scroll.y, (f32)ctx.view->target_scroll_y, 0.5f);
            if(ctx.view->target_scroll_y < 1.0f) {
                ctx.view->scroll.y = ctx.view->target_scroll_y;
                ctx.view->target_scroll_y = 0.0f;
            }
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

    void debug_menu()
    {
        ImGui::SetWindowFontScale(k_text_size_nerds);

        ImGui::Indent();
        
        ImGui::Text("frame time %f (ms)", 1.0 / ctx.dt);

        if(ctx.view)
        {
            ImGui::Text("feed: %zu / %zu\t pos: %i",
                ctx.view->releases.available_entries.load(),
                ctx.view->releases.soa_size.load(),
                ctx.top
            );
        }

        ImGui::Text("cache: %i (%imb)",
            ctx.data_ctx.cached_release_folders.load(),
            (u32)(ctx.data_ctx.cached_release_bytes.load() / 1024 / 1024)
        );

        //
        ImGui::Text("scroll: %f", ctx.scroll_pos_y);

        ImGui::Unindent();
    }

    void login_or_singup_menu() {

        ImGui::SetWindowFontScale(k_text_size_h1);

        f32 ypos = ImGui::GetWindowHeight() * 0.5f - ImGui::GetTextLineHeight() * 3.0f;
        ImGui::SetCursorPosY(ypos);

        ImGui::TextCentred("Log In");
        if(ImGui::IsItemClicked()) {
            ctx.view->page = Page::login;
        }
        ImGui::Spacing();

        ImGui::SetWindowFontScale(k_text_size_body);
        ImGui::TextCentred("or");
        ImGui::Spacing();

        ImGui::SetWindowFontScale(k_text_size_h1);
        ImGui::TextCentred("Sign Up");
        if(ImGui::IsItemClicked()) {
            ctx.view->page = Page::signup;
        }

        ImGui::Spacing();

        // error relay
        ImGui::Indent();
        ImGui::SetWindowFontScale(k_text_size_body);
        if(!ctx.last_response_message.empty()) {
            ImGui::TextWrapped("%s", ctx.last_response_message.c_str());
        }
        ImGui::Unindent();
    }

    Str unpack_error_response(CURLcode code, nlohmann::json response) {
        if(code == CURLE_OK) {
            // unpack error message
            if(response.contains("error")) {
                if(response["error"].contains("message")) {
                    std::string err = response["error"]["message"];
                    return Str(err.c_str());
                }
            }
        }
        else {
            return "Cannot Connect To Server";
        }

        return "";
    }

    void get_input_box_sizes(ImVec2& boxsize, f32& padding)
    {
        ImGui::SetWindowFontScale(k_text_size_body);
        
        f32 textheight = ImGui::CalcTextSize("Ag").y;

        f32 ypos = ImGui::GetWindowHeight() * 0.175f;
        f32 width = ImGui::GetWindowWidth();

        ImGui::SetCursorPosY(ypos);

        ImGui::Indent();
        
        ImGui::SetWindowFontScale(k_text_size_box);
        
        f32 cursorx = ImGui::GetCursorPosX();
        f32 boxwidth = width - (cursorx * 2.0f);
        f32 boxheight = ImGui::CalcTextSize("Ag").y;
        
        ImGui::SetWindowFontScale(k_text_size_body);
        
        padding = (boxheight - textheight) / 2.0f;
        boxsize = ImVec2(boxwidth, boxheight);
    }

    void forgotten_password_menu() {
        static c8  email_buf[k_login_buf_size] = {0};
        static Str error_message = "";
        static Str success_message = "";

        // title
        ImGui::SetWindowFontScale(k_text_size_h2);
        ImGui::Spacing();
        ImGui::TextCentred("Forgotten Password");

        ImGui::SetWindowFontScale(k_text_size_body);

        f32 ypos = ImGui::GetWindowHeight() * 0.5f - ImGui::GetTextLineHeight() * 5.0f;
        ImGui::SetCursorPosY(ypos);

        bool return_pressed = pen::input_is_key_down(PK_RETURN);
        bool any_active = false;

        f32 padding = 0.0;
        ImVec2 boxsize = {};
        get_input_box_sizes(boxsize, padding);

        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding, padding));
                  
        if(ImGui::InputTextEx("##Email", "Email", &email_buf[0], k_login_buf_size, boxsize, 0, nullptr, nullptr)) {
            error_message.clear();
        }
        if(ImGui::IsItemActive()) {
            any_active = true;
        }
        if(return_pressed) {
            ImGui::SetWindowFocus(nullptr);
        }
        
        ImGui::PopStyleVar();

        ImGui::Dummy(ImVec2(0.0, padding));
        ImGui::SetWindowFontScale(k_text_size_h2);
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding * 0.5, padding * 0.5));

        if(ImGui::Button("Back")) {
            ctx.view->page = Page::login_or_signup;
            pen::os_haptic_selection_feedback();
            memset(&email_buf[0], 0x0, k_login_buf_size);
            error_message = "";
        }

        // validate
        bool valid = strlen(email_buf);

        if(valid) {
            ImGui::SameLine();
            if(ImGui::Button("Reset")) {
                pen::os_haptic_selection_feedback();

                Str jstr;
                jstr.appendf("{email: \"%s\", requestType:\"PASSWORD_RESET\"}", email_buf);

                CURLcode code;
                auto response = curl::request(
                    curl::url_with_key("https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode").c_str(),
                    jstr.c_str(),
                    code
                );

                error_message = unpack_error_response(code, response);

                if(error_message.empty()) {
                    success_message = "";
                    success_message.appendf("Password Reset Email Sent To: %s", email_buf);
                }
            }
        }

        ImGui::PopStyleVar();

        // error
        ImGui::Dummy(ImVec2(0.0, padding));
        ImGui::SetWindowFontScale(k_text_size_body);
        ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.5f, 0.0f, 0.0f, 1.0f));
        ImGui::TextWrapped("%s", error_message.c_str());
        ImGui::PopStyleColor();
        ImGui::TextWrapped("%s", success_message.c_str());
        ImGui::Unindent();

        // OSK
        pen::os_show_on_screen_keyboard(any_active);
        pen::input_set_key_up(PK_BACK); // reset any back presses
        pen::input_set_key_up(PK_RETURN);
    }

    bool password_box(const c8* label, const c8* hint, c8* password_buf, bool& return_pressed, bool& active, Str& error_message, ImVec2 size)
    {
        bool next = false;
        f32 spacing = ImGui::GetStyle().ItemSpacing.x;

        // password input
        static bool show_password = false;
        if(ImGui::InputTextEx(
                label,
                hint,
                &password_buf[0],
                k_login_buf_size,
                {size.x - size.y - spacing, size.y},
                show_password ? 0 : ImGuiInputTextFlags_Password,
                nullptr, nullptr))
        {
            error_message.clear();
        }

        // handle active and move to next
        if(ImGui::IsItemActive()) {
            active = true;
        }
        else if(return_pressed) {
            if(ImGui::IsItemFocused())
            {
                ImGui::SetKeyboardFocusHere();
                return_pressed = false;
                next = true;
            }
        }

        // password visibility
        size_t addr = (size_t)password_buf;
        ImGui::PushID(addr);
        ImGui::SameLine();
        if(ImGui::Button(show_password ? ICON_FA_EYE_SLASH : ICON_FA_EYE,
                         {size.y, size.y}))
        {
            show_password = !show_password;
        }
        ImGui::PopID();

        return next;
    }

    void login_menu() {
        static c8  email_buf[k_login_buf_size] = {0};
        static c8  password_buf[k_login_buf_size] = {0};
        static Str error_message = "";

        // title
        ImGui::SetWindowFontScale(k_text_size_h2);
        ImGui::Spacing();
        ImGui::TextCentred("Log In");

        ImGui::SetWindowFontScale(k_text_size_body);

        bool return_pressed = pen::input_is_key_down(PK_RETURN);
        bool any_active = false;
        
        f32 padding = 0.0;
        ImVec2 boxsize = {};
        get_input_box_sizes(boxsize, padding);
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding, padding));

        // email
        if(ImGui::InputTextEx("##Email", "Email", &email_buf[0], k_login_buf_size, boxsize, 0, nullptr, nullptr)) {
            error_message.clear();
        }
        if(ImGui::IsItemActive()) {
            any_active = true;
        }
        else if(return_pressed) {
            if(ImGui::IsItemFocused())
            {
                ImGui::SetKeyboardFocusHere();
                return_pressed = false;
            }
        }

        // password
        bool next = password_box("##Password", "Password", password_buf, return_pressed, any_active, error_message, boxsize);

        ImGui::PopStyleVar();

        // BACK / LOGIN
        ImGui::Dummy(ImVec2(0.0, padding));
        ImGui::SetWindowFontScale(k_text_size_h2);
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding * 0.5, padding * 0.5));

        if(ImGui::Button("Back")) {
            ctx.view->page = Page::login_or_signup;
            pen::os_haptic_selection_feedback();
            
            memset(&email_buf[0], 0x0, k_login_buf_size);
            memset(&password_buf[0], 0x0, k_login_buf_size);
            error_message = "";
        }

        // validate
        bool valid = strlen(email_buf) && strlen(password_buf);
        if(valid) {
            ImGui::SameLine();
            if(ImGui::Button("Log In") || next) {
                pen::os_haptic_selection_feedback();
                Str jstr;
                jstr.appendf("{email: \"%s\", password: \"%s\", returnSecureToken: true}", email_buf, password_buf);

                CURLcode code;
                auto response = curl::request(
                    curl::url_with_key("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword").c_str(),
                    jstr.c_str(),
                    code
                );

                error_message = unpack_error_response(code, response);

                if(error_message.empty()) {
                    // stash credentials
                    pen::os_set_keychain_item("com.pmtech.dig", "email", email_buf);
                    pen::os_set_keychain_item("com.pmtech.dig", "password", password_buf);
                    pen::os_set_keychain_item("com.pmtech.dig", "lastauth", std::to_string(pen::get_time_ms()).c_str());
                    ctx.auth_response = response;
                    ctx.view->page = Page::login_complete;
                }
            }
        }
        ImGui::PopStyleVar();

        // Forgotten password
        ImGui::Dummy(ImVec2(0.0, padding));
        ImGui::SetWindowFontScale(k_text_size_h3);
        ImGui::Text("Forgot Password?");
        if(ImGui::IsItemClicked()) {
            ctx.view->page = Page::forgotten_password;
        }

        // error
        ImGui::Dummy(ImVec2(0.0, padding));
        ImGui::SetWindowFontScale(k_text_size_body);
        ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.5f, 0.0f, 0.0f, 1.0f));
        ImGui::TextWrapped("%s", error_message.c_str());
        ImGui::PopStyleColor();

        ImGui::Unindent();

        // OSK
        pen::os_show_on_screen_keyboard(any_active);
        pen::input_set_key_up(PK_BACK); // reset any back presses
        pen::input_set_key_up(PK_RETURN);
    }

    void signup_menu() {
        static c8 username_buf[k_login_buf_size] = {0};
        static c8 email_buf[k_login_buf_size] = {0};
        static c8 password_buf[k_login_buf_size] = {0};
        static c8 retype_buf[k_login_buf_size] = {0};
        static Str error_message = "";

        // title
        ImGui::SetWindowFontScale(k_text_size_h2);
        ImGui::Spacing();
        ImGui::TextCentred("Sign Up");
        
        bool return_pressed = pen::input_is_key_down(PK_RETURN);
        bool any_active = false;

        ImGui::SetWindowFontScale(k_text_size_body);

        f32 padding = 0.0;
        ImVec2 boxsize = {};
        get_input_box_sizes(boxsize, padding);

        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding, padding));
        
        if(ImGui::InputTextEx("##Username", "Username", &username_buf[0], k_login_buf_size, boxsize, 0, nullptr, nullptr)) {
            error_message.clear();
        }
        if(ImGui::IsItemActive()) {
            any_active = true;
        }
        else if(return_pressed) {
            if(ImGui::IsItemFocused())
            {
                ImGui::SetKeyboardFocusHere();
                return_pressed = false;
            }
        }
          
        if(ImGui::InputTextEx("##Email", "Email", &email_buf[0], k_login_buf_size, boxsize, 0, nullptr, nullptr)) {
            error_message.clear();
        }
        if(ImGui::IsItemActive()) {
            any_active = true;
        }
        else if(return_pressed) {
            if(ImGui::IsItemFocused())
            {
                ImGui::SetKeyboardFocusHere();
                return_pressed = false;
            }
        }

        bool next = password_box("##Password", "Password", password_buf, return_pressed, any_active, error_message, boxsize);
        if(next)
        {
            ImGui::SetKeyboardFocusHere();
            next = false;
        }

        next = password_box("##Retype", "Retype", retype_buf, return_pressed, any_active, error_message, boxsize);

        ImGui::PopStyleVar();

        // Buttons
        ImGui::Dummy(ImVec2(0.0, padding));
        ImGui::SetWindowFontScale(k_text_size_h2);
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(padding * 0.5, padding * 0.5));

        if(ImGui::Button("Back")) {
            pen::os_haptic_selection_feedback();
            ctx.view->page = Page::login_or_signup;
            
            memset(&username_buf[0], 0x0, k_login_buf_size);
            memset(&email_buf[0], 0x0, k_login_buf_size);
            memset(&password_buf[0], 0x0, k_login_buf_size);
            memset(&retype_buf[0], 0x0, k_login_buf_size);
            error_message = "";
        }

        // validate
        bool valid =
            strlen(email_buf) &&
            strlen(email_buf) &&
            strlen(password_buf) &&
            strlen(retype_buf);

        if(valid) {
            ImGui::SameLine();
            if(ImGui::Button("Sign Up") || next) {
                
                nlohmann::json response = {};
                
                if(strcmp(password_buf, retype_buf) == 0)
                {
                    pen::os_haptic_selection_feedback();
                    Str jstr;
                    jstr.appendf("{email: \"%s\", password: \"%s\", returnSecureToken: true}", email_buf, password_buf);

                    CURLcode code;
                    response = curl::request(
                        curl::url_with_key("https://identitytoolkit.googleapis.com/v1/accounts:signUp").c_str(),
                        jstr.c_str(),
                        code
                    );
                    
                    error_message = unpack_error_response(code, response);
                }
                else
                {
                    error_message = "error: passwords do not match";
                }
                
                if(error_message.empty()) {
                    // stash credentials
                    pen::os_set_keychain_item("com.pmtech.dig", "email", email_buf);
                    pen::os_set_keychain_item("com.pmtech.dig", "password", password_buf);
                    pen::os_set_keychain_item("com.pmtech.dig", "username", username_buf);
                    pen::os_set_keychain_item("com.pmtech.dig", "lastauth", std::to_string(pen::get_time_ms()).c_str());
                    ctx.auth_response = response;
                    ctx.view->page = Page::login_complete;
                }
            }
        }

        ImGui::PopStyleVar();

        // error
        ImGui::Dummy(ImVec2(0.0, padding));
        ImGui::SetWindowFontScale(k_text_size_body);
        ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.5f, 0.0f, 0.0f, 1.0f));
        ImGui::TextWrapped("%s", error_message.c_str());
        ImGui::PopStyleColor();

        ImGui::Unindent();

        // OSK
        pen::os_show_on_screen_keyboard(any_active);
        pen::input_set_key_up(PK_BACK); // reset any back presses
        pen::input_set_key_up(PK_RETURN);
    }

    void login_complete() {
        // copy auth credentials
        ctx.data_ctx.auth.mutex.lock();
        ctx.data_ctx.auth.dict = ctx.auth_response;
        ctx.data_ctx.auth.status = Status::e_ready;
        ctx.data_ctx.auth.mutex.unlock();

        // from keychain
        ctx.username = pen::os_get_keychain_item("com.pmtech.dig", "username");
        
        // set this to use globally
        s_tokenid = ((std::string)ctx.data_ctx.auth.dict["idToken"]).c_str();
        
        // kick off reg loader now we have auth
        pen::thread_create(registry_loader, 10 * 1024 * 1024, &ctx.data_ctx, pen::e_thread_start_flags::detached);

        // trigger update of likes
        update_likes_registry();

        // initialise store
        if(ctx.view && ctx.view->page == Page::login_complete) {
            if(ctx.stores.size() > 0) {
                if(ctx.store.name.empty()) {

                    // get user last visited store preferences
                    while(ctx.data_ctx.user_data.status == Status::e_not_initialised) {
                        pen::thread_sleep_ms(1);
                    }

                    // extract info from dict
                    std::string store_preference = "";
                    std::vector<std::string> section_preference = {};
                    ctx.data_ctx.user_data.mutex.lock();
                    if(ctx.data_ctx.user_data.dict.contains("last_store")) {
                        // store
                        store_preference = ctx.data_ctx.user_data.dict["last_store"];
                    }
                    ctx.data_ctx.user_data.mutex.unlock();

                    // load prev or default
                    if(!store_preference.empty())
                    {
                        // ..
                        PEN_LOG("last visited: %s", store_preference.c_str());
                        for(auto& sec : section_preference) {
                            PEN_LOG("%s", sec.c_str());
                        }

                        ctx.store = change_store(((std::string)ctx.data_ctx.user_data.dict["last_store"]).c_str());
                    }
                    else
                    {
                        ctx.store = change_store("juno");
                    }

                    ctx.data_ctx.user_data.mutex.unlock();
                }
                else {
                    ctx.store = change_store(ctx.store.name);
                }
            }
        }
    }

    void auto_login() {
        // enter
        ReleasesView* view = new ReleasesView;
        ctx.view = view;

        Str email_address = pen::os_get_keychain_item("com.pmtech.dig", "email");
        Str password = pen::os_get_keychain_item("com.pmtech.dig", "password");
        Str lastauth = pen::os_get_keychain_item("com.pmtech.dig", "lastauth");

        if(!email_address.empty() && !password.empty() && !k_force_login) {
            Str jstr;
            jstr.appendf("{email: \"%s\", password: \"%s\", returnSecureToken: true}", email_address.c_str(), password.c_str());

            CURLcode code;
            auto response = curl::request(
                curl::url_with_key("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword").c_str(),
                jstr.c_str(),
                code
            );

            if(code == CURLE_OK) {
                Str error_message = unpack_error_response(code, response);
                if(error_message.empty()) {
                    // stash last auth timestamp
                    pen::os_set_keychain_item("com.pmtech.dig", "lastauth", std::to_string(pen::get_time_ms()).c_str());
                    ctx.auth_response = response;
                    ctx.view->page = Page::login_complete;
                }
                else {
                    // need to debug the error message
                    view->page = Page::login_or_signup;

                    ctx.last_response_code = code;
                    ctx.last_response_message = error_message;
                }
            }
            else {
                // allow login, but without auth if we have credentials stored... these details would have been authenticated at sometime
                if(!lastauth.empty()) {
                    ctx.view->page = Page::login_complete;
                }
                else {
                    view->page = Page::login_or_signup;
                }

                ctx.last_response_code = code;
                ctx.last_response_message.setf("curl code %i", code);
            }
        }
        else
        {
            // new user
            view->page = Page::login_or_signup;
        }
    }

    void main_window() {
        s32 w, h;
        pen::window_get_size(w, h);
        ImGui::SetNextWindowPos(ImVec2(0.0f, 0.0f));
        ImGui::SetNextWindowSize(ImVec2((f32)w, (f32)h));

        ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(0.0f, 0.0f));

        ImGui::Begin("Main", nullptr, ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoScrollbar);

        ImGui::Dummy(ImVec2(0.0f, ctx.status_bar_height * 1.25f));

        // ..
        if(ctx.show_debug) {
            debug_menu();
        }

        // ui menus
        header_menu();

        // state machine for page naviagtion
        if(ctx.view) {
            switch(ctx.view->page) {
                case Page::login_or_signup:
                    login_or_singup_menu();
                break;
                case Page::login:
                    login_menu();
                break;
                case Page::signup:
                    signup_menu();
                break;
                case Page::forgotten_password:
                    forgotten_password_menu();
                break;
                case Page::login_complete:
                    login_complete();
                break;
                case Page::settings:
                    settings_menu();
                break;
                default:
                    store_menu();
                    view_menu();
                    view_reload();
                    release_feed();
                break;
            }
        }

        ImGui::PopStyleVar(4);
        ImGui::End();
    }

    void apply_clicks() {
        if(pen::input_is_mouse_down(PEN_MOUSE_L))
        {
            ctx.touch_down = true;
        }
        else
        {
            ctx.touch_down = false;
        }
    }

    void update_user() {
        if(ctx.username.empty()) {
            ctx.data_ctx.user_data.mutex.lock();
            if(ctx.data_ctx.user_data.dict.contains("username")) {
                ctx.username = ((std::string)ctx.data_ctx.user_data.dict["username"]).c_str();
            }
            ctx.data_ctx.user_data.mutex.unlock();
            ctx.data_ctx.user_data.status = Status::e_invalidated;
        }
    }

    void main_update() {
        update_user();
        apply_taps();
        apply_drags();
        apply_clicks();
        audio_player();
        issue_data_requests();
        issue_open_url_requests();
    }

    void setup_stores() {
        // grab stores
        if(ctx.stores.empty()) {
            ctx.data_ctx.stores.mutex.lock();
            ctx.stores = ctx.data_ctx.stores.dict;
            ctx.data_ctx.stores.mutex.unlock();
        }
    }

    void update_loading_anims() {
        // loading dots
        static f32 track_load_dots = 0.0f;
        track_load_dots += ctx.dt;
        if(track_load_dots > 1.0f) {
            track_load_dots -= 1.0f;
            ctx.loading_dots = (ctx.loading_dots + 1) % 4;
        }

        // loading spinner rotation
        ctx.loading_rot += ctx.dt;
        if(ctx.loading_rot > 2.0f * M_PI) {
            ctx.loading_rot = 0.0f;
        }
    }

    loop_t user_update() {

        if(ctx.backgrounded) {
            pen::thread_sleep_ms(1000);
            pen_main_loop_continue();
        }

        ctx.dt = 1.0f / (f32)pen::timer_elapsed_ms(frame_timer);
        update_loading_anims();

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
            if(ctx.releases_window) {
                main_update();
            }

            main_window();
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

    void* user_setup(void* params) {

        // unpack the params passed to the thread and signal to the engine it ok to proceed
        pen::job_thread_params* job_params = (pen::job_thread_params*)params;
        s_thread_info = job_params->job_info;
        pen::semaphore_post(s_thread_info->p_sem_continue, 1);

        // force audio in silent mode
        pen::os_ignore_slient();

        // allow background and lock screen audio
        pen::os_enable_background_audio(get_user_setting("setting_play_backgrounded", true));

        // support background control and info display
        pen::music_player_remote remote;
        remote.pause = audio_player_pause;
        remote.next = audio_player_next;
        remote.tick = audio_player_tick;
        remote.like = audio_player_toggle_like;
        pen::music_enable_remote_control(remote);

        // hook into background callbacks
        os_register_background_callback(enter_background);

        // get window size
        pen::window_get_size(ctx.w, ctx.h);

        // base ratio taken from iphone11 max dimension
        f32 font_ratio = 42.0f / 1125.0f;
        f32 font_pixel_size = ctx.w * font_ratio;

        // intialise pmtech systems
        pen::jobs_create_job(put::audio_thread_function, 1024 * 10, nullptr, pen::e_thread_start_flags::detached);
        
        // dev_ui::init(dev_ui::default_pmtech_style(), font_pixel_size);
        
        std::vector<dev_ui::font_options> fonts;
        
        // small font
        fonts.push_back({"data/fonts/cousine-regular.ttf", font_pixel_size, 0, 0, false});
        fonts.push_back({"data/fonts/cousine-regular.ttf", font_pixel_size, 0x2013, 0x2019, true});
        fonts.push_back({"data/fonts/fontawesome-webfont.ttf", font_pixel_size, ICON_MIN_FA, ICON_MAX_FA, true});
        init_ex(fonts);
        
        curl::init();

        // init context
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

        ImGui::GetStyle().Colors[ImGuiCol_CheckMark] = ImVec4(1.0f, 0.5f, 0.0f, 1.0f);
        ImGui::GetStyle().Colors[ImGuiCol_HeaderHovered] = ImVec4(1.0f, 0.5f, 0.0f, 1.0f);
        ImGui::GetStyle().Colors[ImGuiCol_HeaderActive] = ImVec4(1.0f, 0.5f, 0.0f, 1.0f);
        ImGui::GetStyle().Colors[ImGuiCol_Button] = ImVec4(1.0f, 0.5f, 0.0f, 1.0f);
        ImGui::GetStyle().Colors[ImGuiCol_ButtonActive] = ImVec4(1.0f, 0.5f, 0.0f, 1.0f);
        ImGui::GetStyle().Colors[ImGuiCol_ButtonHovered] = ImVec4(1.0f, 0.5f, 0.0f, 1.0f);
        ImGui::GetStyle().Colors[ImGuiCol_CheckMark] = ImVec4(1.0f, 0.5f, 0.0f, 1.0f);
        ImGui::GetStyle().Colors[ImGuiCol_FrameBgHovered] = ImVec4(1.0f, 1.0f, 1.0f, 1.0f);

        // spinner
        ctx.spinner_texture = put::load_texture("data/images/spinner.dds");

        // white label
        ctx.white_label_texture = put::load_texture("data/images/white_label.dds");

        // lets go
        pen::thread_create(user_data_thread, 10 * 1024 * 1024, &ctx.data_ctx, pen::e_thread_start_flags::detached);
        auto_login();

        pen_main_loop(user_update);
        return PEN_THREAD_OK;
    }

    void user_shutdown() {
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

void audio_player_tick()
{
    renderer_consume_cmd_buffer_non_blocking();
    put::audio_consume_command_buffer();
    audio_player();
}

void audio_player_toggle_like() {
    u32 r = ctx.top;

    auto& releases = ctx.view->releases;

    if(releases.flags[r] & EntityFlags::liked) {
        add_like(releases.key[r]);
        releases.flags[r] |= EntityFlags::liked;
    }
    else {
        remove_like(releases.key[r]);
        releases.flags[r] |= EntityFlags::liked;
    }
}

void audio_player_next(bool prev)
{
    u32 r = ctx.top;
    auto& releases = ctx.view->releases;

    s32 dir = 1;
    if(prev)
    {
        dir = -1;
    }

    if(r != -1) {

        // next track
        s32 sel = releases.select_track[r] + dir;

        // move to next release
        if(sel >= releases.track_filepath_count[r] || sel < 0)
        {
            r = ctx.top + dir;
            r = max<s32>(r, 0); // clamp releases to 0
            ctx.scroll_delta = vec2f::zero();
            if(r < releases.available_entries) {
                ctx.view->scroll.y = releases.posy[r-1];
                ctx.view->target_scroll_y = releases.posy[r];
                sel = releases.select_track[r];
            }
        }

        if(sel < releases.track_filepath_count[r]) {
            ctx.audio_ctx.play_track_filepath = releases.track_filepaths[r][sel];
            ctx.audio_ctx.invalidate_track = true;
        }

        // assign
        releases.select_track[r] = sel;
        ctx.top = r;
    }

    // flush an update
    audio_player();
    put::audio_consume_command_buffer();
    audio_player();
    renderer_consume_cmd_buffer_non_blocking();
}

void audio_player_pause(bool pause) {
    auto& audio_ctx = ctx.audio_ctx;

    // stop existing
    if(is_valid(audio_ctx.si))
    {
        // pause existing
        put::audio_group_set_pause(audio_ctx.gi, pause);
    }

    // flush an update
    put::audio_consume_command_buffer();
}

void audio_player_stop_existing() {
    auto& audio_ctx = ctx.audio_ctx;

    // stop existing
    if(is_valid(audio_ctx.si))
    {
        put::audio_release_resource(audio_ctx.si);
        audio_ctx.si = -1;
    }
    
    if(is_valid(audio_ctx.ci))
    {
        put::audio_channel_stop(audio_ctx.ci);
        put::audio_release_resource(audio_ctx.ci);
        audio_ctx.ci = -1;
    }
    
    if(is_valid(audio_ctx.si))
    {
        put::audio_release_resource(audio_ctx.si);
        audio_ctx.si = -1;
    }
    
    if(is_valid(audio_ctx.gi))
    {
        put::audio_release_resource(audio_ctx.gi);
        audio_ctx.gi = -1;
    }

    audio_ctx.started = false;
}

void audio_player()
{
    if(!ctx.view)
        return;
    
    auto& releases = ctx.view->releases;
    auto& audio_ctx = ctx.audio_ctx;
    
    if(ctx.backgrounded && !audio_ctx.play_bg)
    {
        ctx.audio_ctx.invalidate_track = true;
        return;
    }

    // audio player
    if(!ctx.mute)
    {
        u32 r = ctx.top;

        // guard
        if(r >= releases.available_entries) {
            return;
        }

        if(ctx.top == -1)
        {
            // stop existing
            audio_player_stop_existing();
            audio_ctx.play_track_filepath = "";
            audio_ctx.play_track_url = "";
        }
                
        // play new
        if(!k_force_streamed_audio)
        {
            if(audio_ctx.play_track_filepath.length() > 0 &&
               audio_ctx.invalidate_track &&
               pen::filesystem_file_exists(audio_ctx.play_track_filepath.c_str()))
            {
                // stop existing
                audio_player_stop_existing();
                
                audio_ctx.si = put::audio_create_stream(audio_ctx.play_track_filepath.c_str());
                audio_ctx.ci = put::audio_create_channel_for_sound(audio_ctx.si);
                audio_ctx.gi = put::audio_create_channel_group();
                
                put::audio_add_channel_to_group(audio_ctx.ci, audio_ctx.gi);
                put::audio_group_set_volume(audio_ctx.gi, 1.0f);
                
                u32 t = releases.select_track[ctx.top];
                Str track_name = "";
                if(t < releases.track_name_count[r]) {
                    track_name = releases.track_names[r][t];
                }
                
                pen::music_set_now_playing(releases.artist[r], releases.title[r], track_name);
                
                audio_ctx.read_tex_data_handle = 0;
                audio_ctx.invalidate_track = false;
                audio_ctx.started = false;
            }
        }
        else
        {
            if(audio_ctx.play_track_filepath.length() > 0 &&
               audio_ctx.invalidate_track &&
               pen::filesystem_file_exists(audio_ctx.play_track_filepath.c_str()))
            {
                // stop existing
                audio_player_stop_existing();
                audio_ctx.si = put::audio_create_sound_url(audio_ctx.play_track_filepath.c_str());
                audio_ctx.invalidate_track = false;
            }
            
            // defer the play
            if(!is_valid(audio_ctx.ci))
            {
                if(is_valid(audio_ctx.si))
                {
                    f32 buffered = put::audio_sound_get_buffered_percentage(audio_ctx.si);
                    
                    if(buffered > 10.0f)
                    {
                        audio_ctx.ci = put::audio_create_channel_for_sound(audio_ctx.si);
                        audio_ctx.gi = put::audio_create_channel_group();
                        
                        put::audio_add_channel_to_group(audio_ctx.ci, audio_ctx.gi);
                        put::audio_group_set_volume(audio_ctx.gi, 1.0f);
                        
                        u32 t = releases.select_track[ctx.top];
                        Str track_name = "";
                        if(t < releases.track_name_count[r]) {
                            track_name = releases.track_names[r][t];
                        }
                        
                        pen::music_set_now_playing(releases.artist[r], releases.title[r], track_name);
                        
                        audio_ctx.read_tex_data_handle = 0;
                        audio_ctx.invalidate_track = false;
                        audio_ctx.started = false;
                    }
                }
            }
        }
        
        // playing
        if(is_valid(audio_ctx.ci))
        {
            // get length and check errors
            u32 len_ms = 0;
            audio_sound_file_info info = {};
            auto info_err = put::audio_channel_get_sound_file_info(audio_ctx.si, &info);
            if(info_err == PEN_ERR_OK) {
                if(info.error != 0) {
                    Str cache = get_cache_path();
                    cache.appendf(releases.id[r].c_str());
                    pen::os_delete_directory(cache);
                    releases.flags[r] &= ~(EntityFlags::tracks_loaded | EntityFlags::tracks_cached);

                }
                else {
                    len_ms = info.length_ms;
                }
            }

            // get pos
            u32 pos_ms = 0;
            audio_channel_state state = {};
            auto state_err = put::audio_channel_get_state(audio_ctx.ci, &state);
            if(state_err == PEN_ERR_OK) {
                pos_ms = state.position_ms;
            }

            // set pos / length info
            // PEN_LOG("set time %i, %i", pos_ms, len_ms);
            pen::music_set_now_playing_time_info(pos_ms, len_ms);

            // read back texture data to display on lock screen
            if(releases.artwork_texture[r] && audio_ctx.read_tex_data_handle != releases.artwork_texture[r])
            {
                pen::resource_read_back_params rrbp;
                rrbp.format = releases.artwork_tcp[r].format;
                rrbp.block_size = releases.artwork_tcp[r].block_size;
                rrbp.data_size = releases.artwork_tcp[r].data_size;
                rrbp.depth_pitch = releases.artwork_tcp[r].data_size;
                rrbp.row_pitch = releases.artwork_tcp[r].width * rrbp.block_size;
                rrbp.resource_index = releases.artwork_texture[r];
                rrbp.call_back_function = set_now_playing_artwork;

                pen::renderer_read_back_resource(rrbp);

                audio_ctx.read_tex_data_handle = releases.artwork_texture[r];
            }

            put::audio_group_state gstate;
            memset(&gstate, 0x0, sizeof(put::audio_group_state));
            put::audio_group_get_state(audio_ctx.gi, &gstate);

            if(audio_ctx.started && gstate.play_state == put::e_audio_play_state::not_playing)
            {
                audio_player_stop_existing();

                // move to next track
                u32 next_track = releases.select_track[ctx.top] + 1;
                if(next_track < releases.track_filepath_count[ctx.top])
                {
                    ctx.scroll_delta.x = 0.0;
                    releases.select_track[ctx.top] += 1;
                    releases.flags[ctx.top] |= EntityFlags::transitioning;

                    if(os_is_backgrounded())
                    {
                        ctx.audio_ctx.play_track_filepath = releases.track_filepaths[ctx.top][releases.select_track[ctx.top]];
                        ctx.audio_ctx.invalidate_track = true;
                    }
                }
                else {
                    // move to next release
                    ctx.scroll_delta = vec2f::zero();
                    u32 next_release = ctx.top + 1;
                    if(next_release < releases.available_entries) {
                        ctx.view->target_scroll_y = releases.posy[next_release];
                    }

                    if(os_is_backgrounded())
                    {
                        ctx.top += 1;
                        u32 sel = releases.select_track[ctx.top];
                        if(sel < releases.track_filepath_count[ctx.top])
                        {
                            ctx.audio_ctx.play_track_filepath = releases.track_filepaths[ctx.top][sel];
                            ctx.audio_ctx.invalidate_track = true;
                        }
                    }
                }

                //

            }
            else if(gstate.play_state == put::e_audio_play_state::playing)
            {
                audio_ctx.started = true;
            }
        }
    }
}

bool has_like(const Str& id) {
    bool ret = false;
    ctx.data_ctx.user_data.mutex.lock();
    if(ctx.data_ctx.user_data.dict.contains("likes")) {
        if(ctx.data_ctx.user_data.dict["likes"].contains(id.c_str())) {
            if(ctx.data_ctx.user_data.dict["likes"][id.c_str()].is_boolean()) {
                ret = ctx.data_ctx.user_data.dict["likes"][id.c_str()];
            }
            else if(ctx.data_ctx.user_data.dict["likes"][id.c_str()].is_number()) {
                ret = ctx.data_ctx.user_data.dict["likes"][id.c_str()] > 0;
            }
        }
    }
    ctx.data_ctx.user_data.mutex.unlock();
    return ret;
}

f32 get_like_timestamp(const Str& id) {
    f32 ret = 0.0f;
    ctx.data_ctx.user_data.mutex.lock();
    if(ctx.data_ctx.user_data.dict.contains("likes")) {
        if(ctx.data_ctx.user_data.dict["likes"].contains(id.c_str())) {
            if(ctx.data_ctx.user_data.dict["likes"][id.c_str()].is_boolean()) {
                ret = 0.0f;
            }
            else if(ctx.data_ctx.user_data.dict["likes"][id.c_str()].is_number()) {
                ret = ctx.data_ctx.user_data.dict["likes"][id.c_str()];
            }
        }
    }
    ctx.data_ctx.user_data.mutex.unlock();
    return ret;
}

void add_like(const Str& id)
{
    ctx.data_ctx.user_data.mutex.lock();
    ctx.data_ctx.user_data.dict["likes"][id.c_str()] = get_like_timestamp_time();
    ctx.data_ctx.user_data.mutex.unlock();
    ctx.data_ctx.user_data.status = Status::e_invalidated;

    // async find the release and cache it to the likes cache
    std::thread cache_thread([id]() {
        // open cache
        Str filepath = get_persistent_filepath("likes_feed.json", true);
        auto likes_registry = nlohmann::json();
        try {
            likes_registry = nlohmann::json::parse(std::ifstream(filepath.c_str()));

        } catch (...) {
            // ..
        }

        // grab the release info
        Str search_url = "https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app/releases.json";
        search_url.appendf("?orderBy=\"$key\"&equalTo=\"%s\"&timeout=1s", id.c_str());
        search_url = append_auth(search_url);

        auto db = curl::download(search_url.c_str());
        if(db.data)
        {
            // store in reg
            nlohmann::json release;
            try {
                release = nlohmann::json::parse(db.data);
                likes_registry[id.c_str()] = release[id.c_str()];
            }
            catch(...) {
                // ..
            }
        }

        // write to disk
        PEN_LOG("add %s to likes registry", id.c_str());
        FILE* fp = fopen(filepath.c_str(), "wb");
        std::string j = likes_registry.dump();
        fwrite(j.c_str(), j.length(), 1, fp);
        fclose(fp);
    });
    cache_thread.detach();
}

void remove_like(const Str& id)
{
    ctx.data_ctx.user_data.mutex.lock();
    if(ctx.data_ctx.user_data.dict.contains("likes")) {
        ctx.data_ctx.user_data.dict["likes"].erase(id.c_str());
    }
    ctx.data_ctx.user_data.mutex.unlock();
    ctx.data_ctx.user_data.status = Status::e_invalidated;

    // remove the entry from the likes registry
    std::thread cache_thread([id]() {
        // open cache
        Str filepath = get_persistent_filepath("likes_feed.json", true);
        auto likes_registry = nlohmann::json();
        try {
            likes_registry = nlohmann::json::parse(std::ifstream(filepath.c_str()));

        } catch (...) {
            // ..
        }

        if(likes_registry.contains(id.c_str())) {
            likes_registry.erase(id.c_str());

            PEN_LOG("remove %s from likes registry", id.c_str());
            FILE* fp = fopen(filepath.c_str(), "wb");
            std::string j = likes_registry.dump();
            fwrite(j.c_str(), j.length(), 1, fp);
            fclose(fp);
        }
    });
    cache_thread.detach();
}

nlohmann::json get_likes()
{
    nlohmann::json result = {};
    ctx.data_ctx.user_data.mutex.lock();
    if(ctx.data_ctx.user_data.dict.contains("likes")) {
        result = ctx.data_ctx.user_data.dict["likes"];
    }
    ctx.data_ctx.user_data.mutex.unlock();

    return result;
}

void update_last_store(const Str& name) {
    ctx.data_ctx.user_data.mutex.lock();
    ctx.data_ctx.user_data.dict["last_store"] = name.c_str();
    ctx.data_ctx.user_data.mutex.unlock();
    ctx.data_ctx.user_data.status = Status::e_invalidated;
}

void update_store_prefs(const Str& store_name, const Str& view, const std::vector<Str> sections) {
    ctx.data_ctx.user_data.mutex.lock();
    ctx.data_ctx.user_data.dict["stores"][store_name.c_str()]["view"] = view.c_str();
    ctx.data_ctx.user_data.dict["stores"][store_name.c_str()]["sections"] = {};
    for(auto& section : sections) {
        ctx.data_ctx.user_data.dict["stores"][store_name.c_str()]["sections"].push_back(section.c_str());
    }
    ctx.data_ctx.user_data.mutex.unlock();
    ctx.data_ctx.user_data.status = Status::e_invalidated;
}

void settings_menu()
{
    ImGui::SetWindowFontScale(k_text_size_h3);

    ImGui::Spacing();
    ImGui::Spacing();
    ImGui::Spacing();

    ImGui::Indent();

    // cache size
    static int s_selected_cache_size_setting = get_user_setting("setting_cache_size", 0);
    static const c8* k_cache_options = "Small\0Med\0Large\0Uncapped\0";
    ImGui::Text("%s", "Cache Size");
    if(ImGui::Combo("##Cache Size", &s_selected_cache_size_setting, k_cache_options)) {
        set_user_setting("setting_cache_size", s_selected_cache_size_setting);
    }

    // background audio
    static bool s_play_backgrounded_setting = get_user_setting("setting_play_backgrounded", true);
    int i_playbg = s_play_backgrounded_setting;
    static const c8* k_play_bg_options = "No\0Yes\0";
    ImGui::Text("%s", "Background Audio");
    if(ImGui::Combo("##Background Audio", &i_playbg, k_play_bg_options)) {
        s_play_backgrounded_setting = i_playbg;
        set_user_setting("setting_play_backgrounded", s_play_backgrounded_setting);
        pen::os_enable_background_audio(s_play_backgrounded_setting);
    }

    ImGui::Unindent();

    ImGui::SetWindowFontScale(k_text_size_body);
}

void* data_cache_enumerate(void* userdata) {
    // get view from userdata
    ReleasesView* view = (ReleasesView*)userdata;

    Str cache_dir = get_cache_path();

    // track all folders
    std::vector<DirInfo> cached_releases;

    auto tt = pen::scope_timer("cache enum", true);

    s32 last_top = 26;

    s32 size_setting = get_user_setting("setting_cache_size", 0);

    s32 size_ranges[] = {
        500,
        2000,
        4000,
        1000000
    };

    s32 cache_range = size_ranges[size_setting];

    for(;;) {

        // apply updates when we have moved an amount
        if(abs(last_top - (s32)view->top_pos) < 25)
        {
            last_top = view->top_pos;
            pen::thread_sleep_ms(66);
            continue;
        }

        last_top = view->top_pos;

        // enum cache stats
        pen::fs_tree_node dir;
        pen::filesystem_enum_directory(cache_dir.c_str(), dir, 1, "**/*.*");
        view->data_ctx->cached_release_folders = 0;
        view->data_ctx->cached_release_bytes = 0;
        for(u32 i = 0; i < dir.num_children; ++i) {
            Str path = cache_dir;
            path.append(dir.children[i].name);

            pen::fs_tree_node release_dir;
            pen::filesystem_enum_directory(path.c_str(), release_dir);
            view->data_ctx->cached_release_folders++;

            auto info = get_folder_info_recursive(release_dir, path.c_str());
            view->data_ctx->cached_release_bytes += info.size;

            pen::filesystem_enum_free_mem(release_dir);

            cached_releases.push_back(info);
        }
        pen::filesystem_enum_free_mem(dir);

        // uncapped
        if(size_setting == 3)
        {
            view->threads_terminated++;
            return nullptr;
        }

        // sort the items
        std::sort(begin(cached_releases),end(cached_releases),[](DirInfo a, DirInfo b) { return a.mtime < b.mtime; });

        // wait until we have at least 200 entries
        while(view->release_pos_status != Status::e_ready) {
            // return early if something went wrong
            if(view->status == Status::e_not_available) {
                view->threads_terminated++;
                return nullptr;
            }
            // early out to terminate
            if(view->terminate) {
                view->threads_terminated++;
                return nullptr;
            }
            pen::thread_sleep_ms(1);
        }

        // iterate through releases in reverse remvoing items not in the view
        for(ssize_t i = cached_releases.size()-1; i >= cache_range; --i) {

            DirInfo ii = cached_releases[i];
            auto bn = str_basename(ii.path);
            u32 bnh = PEN_HASH(bn.c_str());
            PEN_LOG("scan %s", bn.c_str());

            if(view->release_pos.find(bnh) != view->release_pos.end()) {
                if(view->release_pos[bnh] > cache_range) {
                    PEN_LOG("should remove out of range %s", bn.c_str());
                    cached_releases.erase(cached_releases.begin() + i);
                    bool result = pen::os_delete_directory(ii.path);
                    if(result) {
                        PEN_LOG("deleted: %s", ii.path.c_str());
                        view->data_ctx->cached_release_bytes -= ii.size;
                        view->data_ctx->cached_release_folders--;
                    }
                }
            }
            else {
                PEN_LOG("should remove not in list %s", bn.c_str());
                cached_releases.erase(cached_releases.begin() + i);
                bool result = pen::os_delete_directory(ii.path);
                if(result) {
                    PEN_LOG("deleted: %s", ii.path.c_str());
                    view->data_ctx->cached_release_bytes -= ii.size;
                    view->data_ctx->cached_release_folders--;
                }
            }

            // early out to terminate
            if(view->terminate) {
                view->threads_terminated++;
                return nullptr;
            }
        }

        if(view->terminate) {
            view->threads_terminated++;
            return nullptr;
        }
    }

    // flag terminated
    view->threads_terminated++;
    return nullptr;
}

void enter_background(bool backgrounded) {
    ctx.audio_ctx.play_bg = get_user_setting("setting_play_backgrounded", true);
    if(!ctx.audio_ctx.play_bg)
    {
        if(backgrounded) {
            audio_suspend();
        }
        else {
            audio_resume();
        }
    }
    else
    {
        // this is required to reinit the audio system after we have been interrupted
        if(os_require_audio_reinit(true)) {
            audio_reinit();
        }
    }
    
    ctx.backgrounded = backgrounded;
}
