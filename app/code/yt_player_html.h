// yt_player_html.h
// shared html payload for the hidden webview backed youtube player.
// the js posts {s: <yt player state>} on state change, {s:-2, e:<code>} on error,
// {t: <position ms>, d: <duration ms>} on a 250ms interval while alive, and
// {r:1} once its script has executed (so a load issued before the page is ready
// can be held and replayed).
// post() targets a wkwebview script message handler (ios / macos) or an android
// javascript interface, so the same payload works on all platforms.
//
// the page must be loaded with k_yt_base_url as its base url and it must match
// the origin / widget_referrer player vars in the js below. it needs to be a
// neutral https origin: youtube rejects the embed (error 152) if the page
// claims https://www.youtube.com as its own origin, and a missing origin is
// also rejected.

#pragma once

namespace
{
    const char* k_yt_base_url = "https://www.example.com";

    const char* k_yt_html = R"(
<!doctype html><html><head><meta name='viewport' content='initial-scale=1'></head>
<body style='margin:0;background:#000'>
<div id='p'></div>
<script>
var player=null, pend=null;
function post(m){
    if(window.webkit&&window.webkit.messageHandlers&&window.webkit.messageHandlers.penyt){window.webkit.messageHandlers.penyt.postMessage(m);}
    else if(window.penyt&&window.penyt.postMessage){window.penyt.postMessage(JSON.stringify(m));}
}
var tag=document.createElement('script');
tag.src='https://www.youtube.com/iframe_api';
document.head.appendChild(tag);
function onYouTubeIframeAPIReady(){
    player=new YT.Player('p',{height:'90',width:'160',
        playerVars:{autoplay:1,controls:0,rel:0,modestbranding:1,iv_load_policy:3,playsinline:1,
            origin:'https://www.example.com',widget_referrer:'https://www.example.com'},
        events:{
            onReady:function(e){ if(pend){ e.target.loadVideoById(pend); pend=null; } },
            onStateChange:function(e){ post({s:e.data}); },
            onError:function(e){ post({s:-2,e:e.data}); }
        }});
    setInterval(function(){
        if(player&&player.getCurrentTime){
            post({t:Math.floor((player.getCurrentTime()||0)*1000),d:Math.floor((player.getDuration()||0)*1000)});
        }
    },250);
}
function yt_load(id){ if(player&&player.loadVideoById){ player.loadVideoById(id); } else { pend=id; } }
function yt_play(){ if(player&&player.playVideo){ player.playVideo(); } }
function yt_pause(){ if(player&&player.pauseVideo){ player.pauseVideo(); } }
function yt_stop(){ pend=null; if(player&&player.stopVideo){ player.stopVideo(); } }
function yt_mute(m){ if(!player){ return; } if(m){ if(player.mute){player.mute();} } else { if(player.unMute){player.unMute();} } }
post({r:1});
</script>
</body></html>
)";
} // namespace
