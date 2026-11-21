# Orbit Lite Android wrapper (cloud APK build)

This Android WebView shell opens the hosted Orbit Lite messenger. It does not modify your server or database.

## Build on GitHub Actions
1. Upload the contents of this folder to a GitHub repository (keep `.github/workflows/build-apk.yml`).
2. Open the repository's **Actions** tab.
3. Select **Build Orbit Lite APK** and click **Run workflow** (or push to `main` to trigger).
4. When the run finishes, open it, scroll to **Artifacts**, and download `OrbitLite-debug-apk`.
5. Extract the ZIP artifact to get `app-debug.apk`, then install it on Android.

Server URL is currently `http://na-one.enzonic.com:26367`. HTTP is enabled in the app manifest because the server URL is HTTP; using HTTPS is preferable if the host supports it.
