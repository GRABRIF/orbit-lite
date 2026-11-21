package com.orbitlite.app;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.ValueCallback;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.JavascriptInterface;

public class MainActivity extends Activity {
    private WebView webView;
    private ValueCallback<Uri[]> pendingFileCallback;
    private static final int FILE_CHOOSER_REQUEST = 314;
    private static final String ORBIT_URL = "http://na-one.enzonic.com:26367";
    private static final String NOTIFICATION_CHANNEL = "orbit_messages";

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.rgb(21,23,32));
        getWindow().setNavigationBarColor(Color.rgb(21,23,32));
        createNotificationChannel();
        requestNotificationPermissionIfNeeded();
        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(21,23,32));
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setLoadsImagesAutomatically(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        webView.addJavascriptInterface(new OrbitNotificationBridge(this), "OrbitAndroidNotifications");
        webView.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                String shim = "(function(){try{if(window.__orbitAndroidNotificationShim)return;window.__orbitAndroidNotificationShim=true;"
                    + "function OrbitNotification(title,opts){opts=opts||{};try{OrbitAndroidNotifications.show(String(title||'Orbit Lite'),String(opts.body||''),String(opts.tag||''));}catch(e){}};"
                    + "OrbitNotification.permission='granted';OrbitNotification.requestPermission=function(){return Promise.resolve('granted');};"
                    + "window.Notification=OrbitNotification;}catch(e){}})();";
                view.evaluateJavascript(shim, null);
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (pendingFileCallback != null) pendingFileCallback.onReceiveValue(null);
                pendingFileCallback = callback;
                Intent picker = new Intent(Intent.ACTION_GET_CONTENT);
                picker.addCategory(Intent.CATEGORY_OPENABLE);
                picker.setType("*/*");
                picker.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params != null && params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                try {
                    startActivityForResult(Intent.createChooser(picker, "Выберите файлы"), FILE_CHOOSER_REQUEST);
                    return true;
                } catch (Exception e) {
                    pendingFileCallback = null;
                    callback.onReceiveValue(null);
                    return false;
                }
            }
        });
        setContentView(webView);
        if (savedInstanceState != null) webView.restoreState(savedInstanceState);
        else webView.loadUrl(ORBIT_URL);
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(NOTIFICATION_CHANNEL, "Orbit Lite messages", NotificationManager.IMPORTANCE_DEFAULT);
            channel.setDescription("Notifications for new Orbit Lite messages");
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) nm.createNotificationChannel(channel);
        }
    }

    private void requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 515);
        }
    }

    public static class OrbitNotificationBridge {
        private final Context appContext;
        OrbitNotificationBridge(Context context) { appContext = context.getApplicationContext(); }
        @JavascriptInterface public void show(String title, String body, String tag) {
            if (Build.VERSION.SDK_INT >= 33 && appContext.checkSelfPermission("android.permission.POST_NOTIFICATIONS") != android.content.pm.PackageManager.PERMISSION_GRANTED) return;
            NotificationManager nm = (NotificationManager) appContext.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm == null) return;
            Intent launch = appContext.getPackageManager().getLaunchIntentForPackage(appContext.getPackageName());
            PendingIntent pi = null;
            if (launch != null) {
                launch.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;
                pi = PendingIntent.getActivity(appContext, 0, launch, flags);
            }
            Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(appContext, NOTIFICATION_CHANNEL) : new Notification.Builder(appContext);
            b.setSmallIcon(android.R.drawable.ic_dialog_info)
             .setContentTitle(title == null || title.isEmpty() ? "Orbit Lite" : title)
             .setContentText(body == null ? "" : body)
             .setAutoCancel(true);
            if (pi != null) b.setContentIntent(pi);
            int id = (tag == null || tag.isEmpty()) ? (int)System.currentTimeMillis() : tag.hashCode();
            nm.notify(id, b.build());
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_CHOOSER_REQUEST && pendingFileCallback != null) {
            Uri[] picked = null;
            if (resultCode == RESULT_OK && data != null) {
                if (data.getClipData() != null) {
                    int n = data.getClipData().getItemCount();
                    picked = new Uri[n];
                    for (int i = 0; i < n; i++) picked[i] = data.getClipData().getItemAt(i).getUri();
                } else if (data.getData() != null) {
                    picked = new Uri[]{data.getData()};
                }
            }
            pendingFileCallback.onReceiveValue(picked);
            pendingFileCallback = null;
        }
    }

    @Override protected void onSaveInstanceState(Bundle outState) {
        if (webView != null) webView.saveState(outState);
        super.onSaveInstanceState(outState);
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }
}
