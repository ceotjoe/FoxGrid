# Push notifications

When a transmission starts, the server sends a push to all other active participants. The app registers its FCM token after
joining (once the mission lead has approved) and unregisters it when leaving the mission. With the app open, the banner shows the
transmission as before; the push appears only in the background.

## Setup

1. **Firebase project.** Create one, register an Android app and an iOS app with the ID `com.itwebservice.foxgrid`, and download
   their config files: `google-services.json` to `app/android/app/`, `GoogleService-Info.plist` to `app/ios/Runner/`
   (both are in `.gitignore`).
2. **iOS.** Create an APNs authentication key (`.p8`) in the Apple developer account and upload it in Firebase under
   Project settings → Cloud Messaging. The capabilities "Push Notifications" and "Remote notifications" are set in the Xcode
   project. Push only works on a real iPhone.
3. **Server.** Set `FOXGRID_FCM_PROJECT_ID` and `FOXGRID_FCM_CREDENTIALS_FILE` (service-account key); see
   [Deployment](deployment.md#6-optional-push-notifications). The key file must be readable by the container user (UID 10001).
4. **Release builds.** Store the two config files as base64 secrets (see [Release](release.md)).

Without the config files the Android app still builds and runs without push; the iOS build needs `GoogleService-Info.plist`.
The web app has no push (it would need a VAPID key and a service worker).

## Implementation notes

- Server: `backend/app/services/push.py` (FCM HTTP v1 or log-only). Tokens live in `push_tokens`, registered with an atomic upsert
  through `POST /push-tokens`. Push targets are active participants only.
- App: `PushRegistrar` in `app/lib/state/push.dart` and `app/lib/core/push.dart`. `firebase_messaging` is pinned to `^16` on purpose
  (version 17 only offers installation IDs, not the FCM registration token the server sends to).
- Android builds without `google-services.json` (the plugin is applied conditionally); iOS does not.
