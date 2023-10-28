#include "renderer.h"
#include "timer.h"
#include "file_system.h"
#include "volume_generator.h"
#include "pen_string.h"
#include "loader.h"
#include "dev_ui.h"
#include "camera.h"
#include "debug_render.h"
#include "pmfx.h"
#include "pen_json.h"
#include "hash.h"
#include "str_utilities.h"
#include "input.h"
#include "ecs/ecs_scene.h"
#include "ecs/ecs_resources.h"
#include "ecs/ecs_editor.h"
#include "ecs/ecs_utilities.h"
#include "data_struct.h"
#include "maths/maths.h"

#define STB_IMAGE_IMPLEMENTATION
#include "stb/stb_image.h"

#include "audio/audio.h"

#include "../shader_structs/forward_render.h"

using namespace put;
using namespace pen;
using namespace ecs;

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
        p.window_width = 828;
        p.window_height = 1792;
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
    pen::job*                   s_thread_info = nullptr;

    put::camera                 main_camera;
    ecs::ecs_controller         game_controller;
    ecs_scene*                  main_scene;
    pen::timer*                 frame_timer;

    put::scene_view_renderer    svr_main;
    put::scene_view_renderer    svr_editor;
    put::scene_view_renderer    svr_shadow_maps;
    put::scene_view_renderer    svr_area_light_textures;
    put::scene_view_renderer    svr_omni_shadow_maps;

    pen::json                   releases_registry;

    void* user_setup(void* params)
    {
        //unpack the params passed to the thread and signal to the engine it ok to proceed
        pen::job_thread_params* job_params = (pen::job_thread_params*)params;
        s_thread_info = job_params->job_info;
        pen::semaphore_post(s_thread_info->p_sem_continue, 1);

        // intialise pmtech systems
        pen::jobs_create_job(physics::physics_thread_main, 1024 * 10, nullptr, pen::e_thread_start_flags::detached);
        pen::jobs_create_job(put::audio_thread_function, 1024 * 10, nullptr, pen::e_thread_start_flags::detached);
        
        dev_ui::init();
        dbg::init();
        curl::init();
        
        auto registry_data = curl::download("https://raw.githubusercontent.com/polymonster/dig/main/registry/releases.json");
        PEN_LOG("%s\n", registry_data.data);
        
        releases_registry = pen::json::load((const c8*)registry_data.data);

        // timer
        frame_timer = pen::timer_create();

        //create main camera and controller
        put::camera_create_perspective(&main_camera, 60.0f, k_use_window_aspect, 0.1f, 1000.0f);

        //create the main scene and controller
        main_scene = create_scene("main_scene");
        editor_init(main_scene, &main_camera);

        //create view renderers
        svr_main.name = "ecs_render_scene";
        svr_main.id_name = PEN_HASH(svr_main.name.c_str());
        svr_main.render_function = &render_scene_view;

        svr_editor.name = "ecs_render_editor";
        svr_editor.id_name = PEN_HASH(svr_editor.name.c_str());
        svr_editor.render_function = &render_scene_editor;

        svr_shadow_maps.name = "ecs_render_shadow_maps";
        svr_shadow_maps.id_name = PEN_HASH(svr_shadow_maps.name.c_str());
        svr_shadow_maps.render_function = &render_shadow_views;

        svr_area_light_textures.name = "ecs_render_area_light_textures";
        svr_area_light_textures.id_name = PEN_HASH(svr_area_light_textures.name.c_str());
        svr_area_light_textures.render_function = &ecs::render_area_light_textures;

        svr_omni_shadow_maps.name = "ecs_render_omni_shadow_maps";
        svr_omni_shadow_maps.id_name = PEN_HASH(svr_omni_shadow_maps.name.c_str());
        svr_omni_shadow_maps.render_function = &ecs::render_omni_shadow_views;

        pmfx::register_scene_view_renderer(svr_main);
        pmfx::register_scene_view_renderer(svr_editor);
        pmfx::register_scene_view_renderer(svr_shadow_maps);
        pmfx::register_scene_view_renderer(svr_area_light_textures);
        pmfx::register_scene_view_renderer(svr_omni_shadow_maps);

        pmfx::register_scene(main_scene, "main_scene");
        pmfx::register_camera(&main_camera, "model_viewer_camera");

        pmfx::init("data/configs/editor_renderer.jsn");
        put::init_hot_loader();

        pen::timer_start(frame_timer);

        editor_enable(false);

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
        put::dev_ui::show_console(false);
        
        pen::renderer_new_frame();

        f32 dt = pen::timer_elapsed_ms(frame_timer) / 1000.0f;
        pen::timer_start(frame_timer);

        put::dev_ui::new_frame();

        ecs::update(dt);
        pmfx::render();
        
        ImGui::Begin("Main");
        
        //
        // ..
        
        static constexpr size_t count = 100;
        static curl::DataBuffer* artwork[count];
        
        static bool init = true;
        if(init)
        {
            memset(&artwork[0], 0x0, sizeof(curl::DataBuffer*) * count);
            init = false;
        }
    
        static u32 artwork_textures[count] = { 0 };
        
        static curl::DataBuffer* play_track = nullptr;
        
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
            
            // display
            ImGui::Image(IMG(artwork_textures[r]), ImVec2(350, 350));
            ImGui::Text("%s", title.c_str());
            
            if(release["track_urls"].size() > 0)
            {
                for(u32 i = 0; i < release["track_urls"].size(); ++i)
                {
                    if(i > 0)
                    {
                        ImGui::SameLine();
                    }
                    
                    ImGui::PushID(r * 100 + i);
                    
                    if(ImGui::Button(ICON_FA_PLAY))
                    {
                        auto url = release["track_urls"][i].as_str();
                        
                        play_track = new curl::DataBuffer;
                        *play_track = curl::download(url.c_str());
                    }
                    
                    ImGui::PopID();
                }
            }
            
            
        }
        
        ImGui::End();
        
        // present
        put::dev_ui::render();
        pen::renderer_present();
        pen::renderer_consume_cmd_buffer();
        put::audio_consume_command_buffer();
        
        // hot reload
        pmfx::poll_for_changes();
        put::poll_hot_loader();

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
