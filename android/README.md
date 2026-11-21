# Orbit Lite Android WebView wrapper

This is Android Studio source for a simple app wrapper that opens the Orbit Lite hosted website.
It is source code, not a compiled APK. Build an APK using Android Studio.

## Build
1. Install Android Studio on a computer and open this folder as a project.
2. Let Gradle sync. If prompted, install Android SDK Platform 35 and compatible Build Tools.
3. Use Build > Build APK(s). The debug APK is normally under `app/build/outputs/apk/debug/`.
4. Install the debug APK on your Android device.

The app currently points to `http://na-one.enzonic.com:26367`. For production, configure HTTPS and replace the URL in `MainActivity.java`, then turn off cleartext traffic.
