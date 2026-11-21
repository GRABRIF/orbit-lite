package com.orbitlite.app;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.ValueCallback;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.JavascriptInterface;
import android.graphics.Color;

public class MainActivity extends Activity {
    private WebView webView;
    private ValueCallback<Uri[]> fileCallback;
    private static final int FILE_PICKER = 515;
    private static final int NOTIFICATION_PERMISSION_REQUEST = 516;
    private static final String URL = "http://na-one.enzonic.com:26367";
    private static final String CHANNEL = "orbit_messages";


    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(21,23,32));
        getWindow().setNavigationBarColor(Color.rgb(21,23,32));
        createChannel();
        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(21,23,32));
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setLoadsImagesAutomatically(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        settings.setSupportZoom(false);
        webView.addJavascriptInterface(new NativeBridge(this), "OrbitNativeNotifications");
        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("*/*");
                pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params != null && params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                if (params != null && params.getAcceptTypes() != null && params.getAcceptTypes().length > 0) {
                    pick.putExtra(Intent.EXTRA_MIME_TYPES, params.getAcceptTypes());
                }
                pick.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
                try {
                    startActivityForResult(pick, FILE_PICKER);
                    return true;
                } catch (Exception ex) {
                    fileCallback = null;
                    callback.onReceiveValue(null);
                    return false;
                }
            }
        });
        setContentView(webView);
        if (state != null) webView.restoreState(state);
        else webView.loadUrl(URL);
    }


    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Orbit Lite сообщения", NotificationManager.IMPORTANCE_DEFAULT));
        }
    }

    private boolean notificationsGranted() {
        return Build.VERSION.SDK_INT < 33 || checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == NOTIFICATION_PERMISSION_REQUEST && webView != null) {
            String status = notificationsGranted() ? "granted" : "denied";
            webView.evaluateJavascript("window.__orbitPermissionResult && window.__orbitPermissionResult('" + status + "')", null);
        }
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == FILE_PICKER && fileCallback != null) {
            Uri[] selected = null;
            if (resultCode == RESULT_OK && data != null) {
                if (data.getClipData() != null) {
                    int count = data.getClipData().getItemCount();
                    selected = new Uri[count];
                    for (int i = 0; i < count; i++) selected[i] = data.getClipData().getItemAt(i).getUri();
                } else if (data.getData() != null) selected = new Uri[]{data.getData()};
            }
            fileCallback.onReceiveValue(selected);
            fileCallback = null;
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


    public static class NativeBridge {
        private final MainActivity activity;
        NativeBridge(MainActivity activity) { this.activity = activity; }

        @JavascriptInterface public String permissionStatus() {
            return activity.notificationsGranted() ? "granted" : "default";
        }

        @JavascriptInterface public String requestPermission() {
            if (Build.VERSION.SDK_INT < 33) return "granted";
            if (activity.notificationsGranted()) return "granted";
            activity.runOnUiThread(() -> activity.requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATION_PERMISSION_REQUEST));
            return "pending";
        }

        @JavascriptInterface public void show(String title, String body, String tag) {
            if (!activity.notificationsGranted()) return;
            NotificationManager manager = (NotificationManager) activity.getSystemService(NOTIFICATION_SERVICE);
            if (manager == null) return;
            Intent launch = activity.getPackageManager().getLaunchIntentForPackage(activity.getPackageName());
            PendingIntent pending = null;
            if (launch != null) {
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;
                pending = PendingIntent.getActivity(activity, 0, launch, flags);
            }
            Notification.Builder builder = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(activity, CHANNEL) : new Notification.Builder(activity);
            builder.setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle(title == null || title.isEmpty() ? "Orbit Lite" : title).setContentText(body).setAutoCancel(true);
            if (pending != null) builder.setContentIntent(pending);
            manager.notify(tag == null || tag.isEmpty() ? (int) System.currentTimeMillis() : tag.hashCode(), builder.build());
        }
    }
}
