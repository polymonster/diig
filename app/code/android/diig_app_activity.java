package pmtech.diig;

import cc.pmtech.pen_activity;

import android.app.Activity;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebView;
import android.widget.FrameLayout;

public class diig_app_activity extends pen_activity
{
    // hidden youtube player: java <-> c++ bridge lives here (app side) rather
    // than in pmtech. native methods link by symbol name; ytRegister hands the
    // c++ side this activity's jclass + the JavaVM so it can call back in
    public static native void ytRegister();
    public static native void ytStateChange(int state, int error);
    public static native void ytTime(int position_ms, int duration_ms);

    private static Activity s_instance;
    private static WebView  s_webview;
    private static boolean  s_ready = false;
    private static String   s_pendingLoad = null;

    @Override
    protected void onCreate(Bundle arg0)
    {
        loadLibs("diig");
        s_instance = this;
        ytRegister();
        super.onCreate(arg0);
    }

    // pushes {r:1}/{s}/{t} messages from the page js into the native atomics
    public static class YtBridge
    {
        @JavascriptInterface
        public void postMessage(String json)
        {
            try
            {
                org.json.JSONObject o = new org.json.JSONObject(json);
                if (o.has("r"))
                {
                    // page script is up: replay any load issued while it booted
                    s_instance.runOnUiThread(() -> {
                        s_ready = true;
                        if (s_pendingLoad != null && s_webview != null)
                        {
                            s_webview.evaluateJavascript(s_pendingLoad, null);
                            s_pendingLoad = null;
                        }
                    });
                }
                if (o.has("s"))
                    ytStateChange(o.getInt("s"), o.optInt("e", 0));
                if (o.has("t"))
                    ytTime(o.getInt("t"), o.optInt("d", 0));
            }
            catch (Exception e)
            {
                // ignore malformed messages
            }
        }
    }

    public static void ytInit(final String html, final String baseUrl)
    {
        if (s_instance == null)
            return;

        s_instance.runOnUiThread(() -> {
            if (s_webview != null)
                return;

            WebView wv = new WebView(s_instance);
            wv.getSettings().setJavaScriptEnabled(true);
            wv.getSettings().setMediaPlaybackRequiresUserGesture(false);
            wv.getSettings().setDomStorageEnabled(true);
            wv.setWebChromeClient(new WebChromeClient());
            wv.addJavascriptInterface(new YtBridge(), "penyt");

            // must stay VISIBLE with a non zero size; GONE / INVISIBLE or a zero
            // frame can suspend media playback, so park it offscreen instead
            FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(320, 180);
            s_instance.addContentView(wv, params);
            wv.setTranslationX(-4000);

            // base url must match the origin player var in the payload
            wv.loadDataWithBaseURL(baseUrl, html, "text/html", "utf-8", null);

            s_webview = wv;
        });
    }

    public static void ytEval(final String js)
    {
        if (s_instance == null)
            return;

        s_instance.runOnUiThread(() -> {
            if (s_webview == null)
                return;

            if (!s_ready)
            {
                // only a load is worth remembering; play / pause / mute before
                // the page exists are no-ops anyway
                if (js.startsWith("yt_load("))
                    s_pendingLoad = js;
                return;
            }

            s_webview.evaluateJavascript(js, null);
        });
    }

    public static void ytShutdown()
    {
        if (s_instance == null)
            return;

        s_instance.runOnUiThread(() -> {
            if (s_webview != null)
            {
                ViewGroup parent = (ViewGroup) s_webview.getParent();
                if (parent != null)
                    parent.removeView(s_webview);
                s_webview.destroy();
                s_webview = null;
                s_ready = false;
                s_pendingLoad = null;
            }
        });
    }
}
