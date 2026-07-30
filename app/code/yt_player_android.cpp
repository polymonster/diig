// yt_player_android.cpp
// android implementation of the app-local hidden youtube player.
//
// the build globs code/**.cpp into every platform, so the whole translation
// unit is guarded to android. it is fully self-contained: java -> c++ native
// methods link by symbol name (no JNI_OnLoad needed), and for c++ -> java the
// JavaVM + the app activity's jclass are captured from the ytRegister static
// native call (invoked from the activity, where the app classloader is active).

#if defined(PEN_PLATFORM_ANDROID)

#include "yt_player.h"
#include "yt_player_html.h"

#include <jni.h>
#include <atomic>
#include <string>
#include <cstdio>

namespace
{
    JavaVM*               s_vm = nullptr;
    jclass                s_activity_class = nullptr; // global ref to diig_app_activity
    std::atomic<uint32_t> s_state = {yt::e_state::unavailable};
    std::atomic<uint32_t> s_error = {0};
    std::atomic<uint32_t> s_position_ms = {0};
    std::atomic<uint32_t> s_duration_ms = {0};

    JNIEnv* jni_env()
    {
        if (!s_vm)
            return nullptr;

        JNIEnv* env = nullptr;
        int status = s_vm->GetEnv((void**)&env, JNI_VERSION_1_6);
        if (status == JNI_EDETACHED)
        {
            if (s_vm->AttachCurrentThread(&env, nullptr) != 0)
                return nullptr;
        }
        else if (status != JNI_OK)
        {
            return nullptr;
        }
        return env;
    }

    void yt_apply_state(int yt_state, uint32_t error_code)
    {
        switch (yt_state)
        {
            case -2: // custom error marker from js onError
                s_error = error_code;
                s_state = yt::e_state::error;
                break;
            case -1: // unstarted
            case 5:  // cued
                s_state = yt::e_state::idle;
                break;
            case 0:
                s_state = yt::e_state::ended;
                break;
            case 1:
                s_state = yt::e_state::playing;
                break;
            case 2:
                s_state = yt::e_state::paused;
                break;
            case 3:
                s_state = yt::e_state::buffering;
                break;
        }
    }

    // call a static void method (String arg) on the app activity class
    void call_activity_static(const char* method, const char* sig, jstring a0 = nullptr, jstring a1 = nullptr)
    {
        JNIEnv* env = jni_env();
        if (!env || !s_activity_class)
            return;

        jmethodID m = env->GetStaticMethodID(s_activity_class, method, sig);
        if (!m)
            return;

        if (a1)
            env->CallStaticVoidMethod(s_activity_class, m, a0, a1);
        else if (a0)
            env->CallStaticVoidMethod(s_activity_class, m, a0);
        else
            env->CallStaticVoidMethod(s_activity_class, m);
    }

    void yt_eval(const char* js)
    {
        JNIEnv* env = jni_env();
        if (!env)
            return;
        jstring jjs = env->NewStringUTF(js);
        call_activity_static("ytEval", "(Ljava/lang/String;)V", jjs);
        env->DeleteLocalRef(jjs);
    }

    // video ids are only ever [A-Za-z0-9_-], strip anything else
    std::string yt_sanitise_video_id(const char* video_id)
    {
        std::string safe;
        if (!video_id)
            return safe;
        for (const char* c = video_id; *c; ++c)
        {
            if ((*c >= 'a' && *c <= 'z') || (*c >= 'A' && *c <= 'Z') || (*c >= '0' && *c <= '9') || *c == '-' || *c == '_')
                safe.push_back(*c);
        }
        return safe;
    }
}

// java -> c++ (package pmtech.diig, class diig_app_activity). underscores in the
// class name are mangled to _1
extern "C" JNIEXPORT void JNICALL
Java_pmtech_diig_diig_1app_1activity_ytRegister(JNIEnv* env, jclass clazz)
{
    env->GetJavaVM(&s_vm);
    if (s_activity_class)
        env->DeleteGlobalRef(s_activity_class);
    s_activity_class = (jclass)env->NewGlobalRef(clazz);
}

extern "C" JNIEXPORT void JNICALL
Java_pmtech_diig_diig_1app_1activity_ytStateChange(JNIEnv* env, jclass clazz, jint state, jint error)
{
    yt_apply_state((int)state, (uint32_t)error);
}

extern "C" JNIEXPORT void JNICALL
Java_pmtech_diig_diig_1app_1activity_ytTime(JNIEnv* env, jclass clazz, jint position_ms, jint duration_ms)
{
    s_position_ms = (uint32_t)position_ms;
    s_duration_ms = (uint32_t)duration_ms;
}

namespace yt
{
    void init()
    {
        JNIEnv* env = jni_env();
        if (!env || !s_activity_class)
            return;

        jstring jhtml = env->NewStringUTF(k_yt_html);
        jstring jbase = env->NewStringUTF(k_yt_base_url);
        call_activity_static("ytInit", "(Ljava/lang/String;Ljava/lang/String;)V", jhtml, jbase);
        env->DeleteLocalRef(jhtml);
        env->DeleteLocalRef(jbase);

        s_state = e_state::idle;
    }

    void load_video(const char* video_id)
    {
        std::string safe = yt_sanitise_video_id(video_id);
        if (safe.empty())
            return;

        // optimistically flag buffering so callers never observe a stale ended /
        // error state between issuing a load and the js callbacks arriving
        s_error = 0;
        s_position_ms = 0;
        s_duration_ms = 0;
        s_state = e_state::buffering;

        std::string js = "yt_load('";
        js += safe;
        js += "')";
        yt_eval(js.c_str());
    }

    void play()
    {
        yt_eval("yt_play()");
    }

    void pause()
    {
        yt_eval("yt_pause()");
    }

    void stop()
    {
        s_state = e_state::idle;
        s_position_ms = 0;
        s_duration_ms = 0;
        yt_eval("yt_stop()");
    }

    void set_mute(bool mute)
    {
        yt_eval(mute ? "yt_mute(1)" : "yt_mute(0)");
    }

    player_state get_state()
    {
        player_state state;
        state.state = s_state;
        state.error_code = s_error;
        state.position_ms = s_position_ms;
        state.duration_ms = s_duration_ms;
        return state;
    }

    void shutdown()
    {
        call_activity_static("ytShutdown", "()V");
        s_state = e_state::unavailable;
    }
} // namespace yt

#endif // PEN_PLATFORM_ANDROID
