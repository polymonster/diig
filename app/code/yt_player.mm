// yt_player.mm
// ios / macos implementation of the app-local hidden youtube player.
// hosts the youtube iframe api in an offscreen WKWebView; state is pushed from
// js into atomics that yt::get_state() reads lock-free from the game thread.
// only compiled on apple targets (the build globs code/**.mm into xcode only).

#include "yt_player.h"
#include "yt_player_html.h"

#include <atomic>
#include <string>
#include <cstdint>

#import <TargetConditionals.h>
#import <WebKit/WebKit.h>

#if TARGET_OS_IPHONE
#import <UIKit/UIKit.h>
#else
#import <Cocoa/Cocoa.h>
#endif

@interface dig_yt_bridge : NSObject <WKScriptMessageHandler>
@end

namespace
{
    struct yt_context
    {
        WKWebView*            webview = nil;
        dig_yt_bridge*        bridge = nil;
        std::atomic<uint32_t> state = {yt::e_state::unavailable};
        std::atomic<uint32_t> error_code = {0};
        std::atomic<uint32_t> position_ms = {0};
        std::atomic<uint32_t> duration_ms = {0};

        // main thread only: evals issued before the page's script has executed
        // would silently fail, so hold the last load until the js ready marker
        bool                  page_ready = false;
        NSString*             pending_load = nil;
    };
    yt_context s_yt;

    void yt_apply_state(int yt_state, uint32_t error_code)
    {
        switch (yt_state)
        {
            case -2: // custom error marker from js onError
                s_yt.error_code = error_code;
                s_yt.state = yt::e_state::error;
                break;
            case -1: // unstarted
            case 5:  // cued
                s_yt.state = yt::e_state::idle;
                break;
            case 0:
                s_yt.state = yt::e_state::ended;
                break;
            case 1:
                s_yt.state = yt::e_state::playing;
                break;
            case 2:
                s_yt.state = yt::e_state::paused;
                break;
            case 3:
                s_yt.state = yt::e_state::buffering;
                break;
        }
    }

    void yt_eval(NSString* js)
    {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (!s_yt.webview)
                return;

            if (!s_yt.page_ready)
            {
                // only a load is worth remembering; play / pause / mute before
                // the page exists are no-ops anyway
                if ([js hasPrefix:@"yt_load("])
                    s_yt.pending_load = js;
                return;
            }

            [s_yt.webview evaluateJavaScript:js completionHandler:nil];
        });
    }

    // video ids are only ever [A-Za-z0-9_-], strip anything else so ids can be
    // safely spliced into evaluateJavaScript strings
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

@implementation dig_yt_bridge
- (void)userContentController:(WKUserContentController*)userContentController
      didReceiveScriptMessage:(WKScriptMessage*)message
{
    if (![message.body isKindOfClass:[NSDictionary class]])
        return;

    NSDictionary* dict = (NSDictionary*)message.body;
    NSNumber*     r = dict[@"r"];
    NSNumber*     s = dict[@"s"];
    NSNumber*     e = dict[@"e"];
    NSNumber*     t = dict[@"t"];
    NSNumber*     d = dict[@"d"];

    // page script is up: flush any load issued while it was booting
    // (script message handlers are delivered on the main thread)
    if (r)
    {
        s_yt.page_ready = true;
        if (s_yt.pending_load && s_yt.webview)
        {
            [s_yt.webview evaluateJavaScript:s_yt.pending_load completionHandler:nil];
            s_yt.pending_load = nil;
        }
    }

    if (s)
        yt_apply_state([s intValue], e ? [e unsignedIntValue] : 0);

    if (t)
        s_yt.position_ms = [t unsignedIntValue];

    if (d)
        s_yt.duration_ms = [d unsignedIntValue];
}
@end

namespace yt
{
    void init()
    {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (s_yt.webview)
                return;

            WKWebViewConfiguration* config = [[WKWebViewConfiguration alloc] init];
#if TARGET_OS_IPHONE
            config.allowsInlineMediaPlayback = YES;
#endif
            config.mediaTypesRequiringUserActionForPlayback = WKAudiovisualMediaTypeNone;

            s_yt.bridge = [[dig_yt_bridge alloc] init];
            [config.userContentController addScriptMessageHandler:s_yt.bridge name:@"penyt"];

            // must have a non zero frame positioned offscreen; hidden or zero sized
            // webviews can have media playback suspended by the os
            CGRect frame = CGRectMake(-2000.0f, 0.0f, 320.0f, 180.0f);
            s_yt.webview = [[WKWebView alloc] initWithFrame:frame configuration:config];

#if TARGET_OS_IPHONE
            s_yt.webview.userInteractionEnabled = NO;
            UIWindow* window = [[[UIApplication sharedApplication] windows] firstObject];
            [window addSubview:s_yt.webview];
#else
            NSWindow* window = [[[NSApplication sharedApplication] windows] firstObject];
            [[window contentView] addSubview:s_yt.webview];
#endif

            // base url must match the origin player var in the payload
            [s_yt.webview loadHTMLString:[NSString stringWithUTF8String:k_yt_html]
                                 baseURL:[NSURL URLWithString:[NSString stringWithUTF8String:k_yt_base_url]]];

            s_yt.state = e_state::idle;
        });
    }

    void load_video(const char* video_id)
    {
        std::string safe = yt_sanitise_video_id(video_id);
        if (safe.empty())
            return;

        // optimistically flag buffering so callers never observe a stale ended / error
        // state between issuing a load and the js callbacks arriving
        s_yt.error_code = 0;
        s_yt.position_ms = 0;
        s_yt.duration_ms = 0;
        s_yt.state = e_state::buffering;

        yt_eval([NSString stringWithFormat:@"yt_load('%s')", safe.c_str()]);
    }

    void play()
    {
        yt_eval(@"yt_play()");
    }

    void pause()
    {
        yt_eval(@"yt_pause()");
    }

    void stop()
    {
        s_yt.state = e_state::idle;
        s_yt.position_ms = 0;
        s_yt.duration_ms = 0;
        yt_eval(@"yt_stop()");
    }

    void set_mute(bool mute)
    {
        yt_eval(mute ? @"yt_mute(1)" : @"yt_mute(0)");
    }

    player_state get_state()
    {
        player_state state;
        state.state = s_yt.state;
        state.error_code = s_yt.error_code;
        state.position_ms = s_yt.position_ms;
        state.duration_ms = s_yt.duration_ms;
        return state;
    }

    void shutdown()
    {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (!s_yt.webview)
                return;

            [[s_yt.webview.configuration userContentController] removeScriptMessageHandlerForName:@"penyt"];
            [s_yt.webview removeFromSuperview];
            s_yt.webview = nil;
            s_yt.bridge = nil;
            s_yt.page_ready = false;
            s_yt.pending_load = nil;
            s_yt.state = e_state::unavailable;
        });
    }
} // namespace yt
