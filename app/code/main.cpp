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

#include "../shader_structs/forward_render.h"

using namespace put;
using namespace pen;
using namespace ecs;

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

    void* user_setup(void* params)
    {
        //unpack the params passed to the thread and signal to the engine it ok to proceed
        pen::job_thread_params* job_params = (pen::job_thread_params*)params;
        s_thread_info = job_params->job_info;
        pen::semaphore_post(s_thread_info->p_sem_continue, 1);

        // intialise pmtech systems
        pen::jobs_create_job(physics::physics_thread_main, 1024 * 10, nullptr, pen::e_thread_start_flags::detached);
        dev_ui::init();
        dbg::init();

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
        ImGui::Text("%s", "Hello this is dig");
        ImGui::End();
        
        put::dev_ui::render();

        // present
        pen::renderer_present();
        pen::renderer_consume_cmd_buffer();

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
