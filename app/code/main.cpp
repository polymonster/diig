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

#include "maths/maths.h"
#include "audio/audio.h"

#define STB_IMAGE_IMPLEMENTATION
#include "stb/stb_image.h"

using namespace put;
using namespace pen;

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

namespace physics
{
    extern void* physics_thread_main(void* params);
}

namespace
{
    pen::job*   s_thread_info = nullptr;
    pen::timer* frame_timer;
    pen::json   releases_registry;
    u32         clear_screen;

    void* user_setup(void* params)
    {
        //unpack the params passed to the thread and signal to the engine it ok to proceed
        pen::job_thread_params* job_params = (pen::job_thread_params*)params;
        s_thread_info = job_params->job_info;
        pen::semaphore_post(s_thread_info->p_sem_continue, 1);

        // intialise pmtech systems
        pen::jobs_create_job(put::audio_thread_function, 1024 * 10, nullptr, pen::e_thread_start_flags::detached);
        dev_ui::init();
        curl::init();
        
        // load registry
        auto registry_data = curl::download("https://raw.githubusercontent.com/polymonster/dig/main/registry/releases.json");
        PEN_LOG("%s\n", registry_data.data);
        releases_registry = pen::json::load((const c8*)registry_data.data);

        // timer
        frame_timer = pen::timer_create();
        pen::timer_start(frame_timer);
        
        // for clearing the backbuffer
        clear_state cs;
        cs.r = 1.0f;
        cs.g = 1.0f;
        cs.b = 1.0f;
        cs.a = 1.0f;
        clear_screen = pen::renderer_create_clear_state(cs);

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
        pen::timer_start(frame_timer);
        pen::renderer_new_frame();
        
        // clear backbuffer
        pen::renderer_set_targets(PEN_BACK_BUFFER_COLOUR, PEN_BACK_BUFFER_DEPTH);
        pen::renderer_clear(clear_screen);

        put::dev_ui::new_frame();
                
        //
        s32 w, h;
        pen::window_get_size(w, h);
        ImGui::SetNextWindowPos(ImVec2(0.0, 0.0));
        ImGui::SetNextWindowSize(ImVec2((f32)w, (f32)h));
        
        ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0, 0.0));
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(0.0, 0.0));
        
        ImGui::Begin("Main", nullptr, ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoScrollbar);
        
        static constexpr size_t count = 25;
        static curl::DataBuffer* artwork[count];
        
        static bool init = true;
        if(init)
        {
            memset(&artwork[0], 0x0, sizeof(curl::DataBuffer*) * count);
            init = false;
        }
    
        static u32 artwork_textures[count] = { 0 };
        
        static curl::DataBuffer* play_track = nullptr;
        static Str play_track_filepath;
        static bool playing = false;
        
        for(u32 r = 0; r < count; ++r)
        {
            auto release = releases_registry[r];
            auto title = release["title"].as_str();
            
            if(release["artworks"].size() > 0)
            {
                if(!artwork[r])
                {
                    auto art = release["artworks"];
                    
                    auto url = art[1].as_str();
                    
                    artwork[r] = new curl::DataBuffer;
                    *artwork[r] = curl::download(url.c_str());
                    
                    //
                    s32 w, h, c;
                    stbi_uc* rgba = stbi_load_from_memory((stbi_uc const*)artwork[r]->data, (s32)artwork[r]->size, &w, &h, &c, 4);
                    
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
                    tcp.bind_flags =
                    tcp.usage = PEN_USAGE_DEFAULT;
                    tcp.bind_flags = PEN_BIND_SHADER_RESOURCE;
                    tcp.cpu_access_flags = 0;
                    tcp.flags = 0;
                    tcp.block_size = 4;
                    tcp.pixels_per_block = 1;
                    tcp.collection_type = pen::TEXTURE_COLLECTION_NONE;
                    
                    tcp.data = rgba;
                    tcp.data_size = w * h * c * 4;
                    
                    artwork_textures[r] = pen::renderer_create_texture(tcp);
                }
            }
            
            // title
            ImGui::TextWrapped("%s", title.c_str());
            
            // images
            ImGui::BeginChildEx("rel", r+1, ImVec2(w, w), false, 0);
            u32 numImages = std::max<u32>(1, release["track_urls"].size());
            for(u32 i = 0; i < numImages; ++i)
            {
                if(i > 0)
                {
                    ImGui::SameLine();
                }
                
                ImGui::Image(IMG(artwork_textures[r]), ImVec2(w, w));
                
                static float sx = 0.0f;
                if(ImGui::IsItemHovered())
                {
                    if(pen::input_is_mouse_down(PEN_MOUSE_L))
                    {
                        sx -= ImGui::GetIO().MouseDelta.x;
                        ImGui::SetScrollX(sx);
                    }
                }
            }
            ImGui::EndChild();
            
            // tracks
            if(release["track_urls"].size() > 0)
            {
                for(u32 i = 0; i < release["track_urls"].size(); ++i)
                {
                    if(i > 0)
                    {
                        ImGui::SameLine();
                    }
                    
                    ImGui::Text("%s", ICON_FA_DOT_CIRCLE_O);
                    
                    ImGui::PushID(r);
                    ImGui::PushID(i);
                    
                    /*
                    if(ImGui::Button(ICON_FA_PLAY))
                    {
                        auto url = release["track_urls"][i].as_str();
                        
                        play_track = new curl::DataBuffer;
                        *play_track = curl::download(url.c_str());
                        
                        url = pen::str_replace_string(url, "https://", "");
                        url = pen::str_replace_string(url, "/", "_");
                        
                        Str root = "/Users/alex.dixon/dev/";
                        root.append(url.c_str());
                        url = root;
                        
                        // stash
                        FILE* fp = fopen(url.c_str(), "wb");
                        fwrite(play_track->data, play_track->size, 1, fp);
                        fclose(fp);
                        
                        play_track_filepath = url;
                    }
                    */
                    
                    ImGui::PopID();
                    ImGui::PopID();
                }
                
                // track name
                if(release["track_names"].size() > 0)
                {
                    ImGui::TextWrapped("%s", release["track_names"][0].as_cstr());
                }
            }
            else
            {
                ImGui::Text("%s", ICON_FA_MOON_O);
            }
            
            ImGui::Spacing();
            ImGui::Spacing();
        }
        
        if(play_track_filepath.length() > 0 && playing == false)
        {
            u32 si = put::audio_create_sound(play_track_filepath.c_str());
            u32 ci = put::audio_create_channel_for_sound(si);
            u32 gi = put::audio_create_channel_group();
            
            put::audio_add_channel_to_group(ci, gi);
            put::audio_group_set_volume(gi, 1.0f);
            
            playing = true;
        }
        
        ImGui::PopStyleVar(4);
        ImGui::End();
        
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
