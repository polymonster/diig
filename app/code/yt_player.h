// yt_player.h
// app-local hidden youtube player.
//
// a hidden webview hosts the youtube iframe api; state is pushed from the page's
// js into atomics that can be polled lock-free from the game thread via
// yt::get_state(). implemented per platform:
//   - ios / macos: yt_player.mm  (WKWebView)
//   - android:     yt_player_android.cpp  (android.webkit.WebView via the app
//                  activity + jni)
// other platforms link against no implementation (the feature is apple/android
// only), so guard calls behind the platform where discogs playback is used.

#pragma once

namespace yt
{
    namespace e_state
    {
        enum e_state
        {
            unavailable = 0,
            idle,
            buffering,
            playing,
            paused,
            ended,
            error
        };
    }

    struct player_state
    {
        unsigned int state = e_state::unavailable;
        unsigned int error_code = 0; // youtube iframe api error (2, 5, 100, 101, 150) when state == error
        unsigned int position_ms = 0;
        unsigned int duration_ms = 0;
    };

    void         init();
    void         load_video(const char* video_id);
    void         play();
    void         pause();
    void         stop();
    void         set_mute(bool mute);
    player_state get_state();
    void         shutdown();
}
