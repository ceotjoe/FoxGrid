# Release: App Store and Google Play

A Git tag `v<version>` triggers `.github/workflows/release.yml`: tests, signed builds for Android and iOS,
upload to Google Play (track `internal`) and TestFlight, plus a GitHub release with the AAB and IPA.
Submitting for review at Apple and publishing to production deliberately stay manual.

## Release procedure

1. Set the version in `app/pubspec.yaml` (`version: 0.2.0+1`; the part after `+` is replaced in CI).
2. Update the change text in `store/metadata/android/*/changelogs/default.txt` and
   `store/metadata/ios/*/release_notes.txt`.
3. Commit, then `git tag v0.2.0 && git push --tags`. The tag must match the `pubspec.yaml` version, otherwise the run aborts.
4. The run waits for your approval at the GitHub environment `store-release` (see below).
5. Google Play: promote the release in the Play Console from `internal` to `beta`/`production`.
   TestFlight: assign the build to the version in App Store Connect and submit it for review.

Manual dry run without upload: Actions > Release > Run workflow (untick "publish"). The AAB and IPA are then attached to
the run as artifacts. The build number is `github.run_number` (+ the optional repository variable `BUILD_NUMBER_OFFSET`, in case a
store already knows higher numbers).

To update only texts, graphics and screenshots: Actions > Store metadata > Run workflow.

## One-time setup

### GitHub

- Settings > Environments > create `store-release` and add yourselves under "Required reviewers".
  Store all secrets below as **environment secrets** of this environment.
- Settings > Pages > Source "GitHub Actions" (used by `.github/workflows/pages.yml` for the web app).
- The store listings link to the privacy policy at `https://<user>.github.io/<repo>/privacy` (English) and `/privacy-de`
  (German), built from `docs/privacy/` with Jekyll (`docs/_config.yml`). The URLs are in `store/metadata/ios/*/privacy_url.txt`
  and [store-compliance.md](store-compliance.md); they are preset to `ceotjoe/FoxGrid`.
  **Open item:** with Pages set to "GitHub Actions" the Flutter web deployment replaces the site, so the Jekyll pages are only
  published if the workflow also builds them (or if Pages is switched back to "Deploy from a branch", `/docs`, which drops the web app).
  Decide on one setup before the first store submission.

### Android (Google Play)

1. Generate an upload key and keep it **safe** (password manager):
   ```bash
   keytool -genkeypair -v -keystore foxgrid-upload.jks -alias upload -keyalg RSA -keysize 4096 -validity 10000
   ```
   With "Play App Signing" (the default for new apps) Google keeps the actual signing key; if the upload key is lost it
   can be reset through Play support.
2. Create the app in the Play Console (package name `com.itwebservice.foxgrid`), fill in the questionnaires
   (`docs/operations/store-compliance.md`) and **upload the first release by hand once** (Google requires this for a new app). After
   that the automation can take over. Until the app has been published for the first time choose
   `play_release_status = draft` in the manual run.
3. Service account for the API: Play Console > Setup > API access > create a service account, role "Release manager"
   (or at least rights for releases and store listing), download the JSON key.

| Secret | Content |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | `base64 -i foxgrid-upload.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_ALIAS` | `upload` |
| `ANDROID_KEY_PASSWORD` | password of the key |
| `PLAY_SERVICE_ACCOUNT_JSON` | entire content of the JSON file |

For push notifications additionally the Firebase app configuration (not in the repository, see [Push notifications](push-notifications.md)):

| Secret | Content |
|---|---|
| `GOOGLE_SERVICES_JSON_BASE64` | `base64 -i google-services.json` (Android app `com.itwebservice.foxgrid`) |
| `GOOGLE_SERVICE_INFO_PLIST_BASE64` | `base64 -i GoogleService-Info.plist` (iOS app `com.itwebservice.foxgrid`) |

Local release build: copy `app/android/key.properties.example` to `key.properties` and fill it in.
Without a keystore Gradle signs with the debug key; CI rejects such bundles.

### iOS (App Store Connect)

1. Create the app in App Store Connect (bundle ID `com.itwebservice.foxgrid`, team `Q486NF4XF6`).
2. Create an "Apple Distribution" certificate (Xcode > Settings > Accounts > Manage Certificates, or in the
   developer portal) and export it with its private key as `.p12` from Keychain Access.
3. In the developer portal create a provisioning profile of type **App Store** for the bundle ID. Its **name** must be
   `FoxGrid App Store` (see `app/ios/ExportOptions.plist` and `IOS_PROFILE` in `fastlane/Fastfile`).
4. App Store Connect > Users and Access > Integrations > create an API key (role "App Manager"),
   download the `.p8` (possible only once).

| Secret | Content |
|---|---|
| `IOS_DIST_CERT_P12_BASE64` | `base64 -i dist.p12` |
| `IOS_DIST_CERT_PASSWORD` | password of the `.p12` |
| `IOS_PROVISIONING_PROFILE_BASE64` | `base64 -i FoxGrid_App_Store.mobileprovision` |
| `ASC_KEY_ID`, `ASC_ISSUER_ID` | from the API key page |
| `ASC_KEY_P8` | entire content of the `.p8` (including the BEGIN/END lines) |

For the "Store metadata" workflow (iOS) additionally, because Apple requires a reviewer contact and demo access:
`REVIEW_FIRST_NAME`, `REVIEW_LAST_NAME`, `REVIEW_PHONE`, `REVIEW_EMAIL`, `REVIEW_DEMO_SERVER` (HTTPS URL of a
public demo server) and `REVIEW_DEMO_INVITE` (invite token of a demo mission). The texts are in
`store/metadata/ios/review_information/notes.txt`. Store builds only accept HTTPS servers, so the
demo server needs a valid certificate.

## What is not automated

- Age rating, privacy questionnaires, content rating, target audience: `docs/operations/store-compliance.md`.
- Price/availability, submission for app review, phased release.
- Uploading the App Store icon (1024 px): `store/app-store-icon-1024.png` (Fastlane does not upload it).
- Privacy policy: enter name and address, remove the draft notice, have it reviewed legally.

## Graphics and texts

- Texts: `store/metadata/{ios,android}/<de-DE|en-US>/`. Limits: name/title/subtitle 30 characters, Play short description 80,
  iOS keywords 100, description 4000.
- Screenshots: raw images from the running app in `store/screenshots/raw/<device>/NN_name.png`, captions in
  `store/captions.json`, then `python3 tools/store/generate_assets.py` (needs `rsvg-convert` and ImageMagick).
  The output goes into the Fastlane layout under `store/metadata/`. The app UI is German, so the English
  listings show the same screens with English captions.
- Raw images are made like this: start the stack with `docker compose up -d`, create a demo mission with
  `uv run tools/simulator/run.py`, run the app in the simulator/emulator against `http://localhost:8000` (only debug builds
  allow HTTP), set the status bar with `xcrun simctl status_bar booted override --time 9:41 ...`.

## Troubleshooting

- `The bundle is signed with the debug key`: check the `ANDROID_KEYSTORE_*` secrets.
- `Version code N has already been used`: raise the repository variable `BUILD_NUMBER_OFFSET`.
- iOS "No profile for team/bundle": the profile name must be exactly `FoxGrid App Store` and match the certificate.
- Google Play "Only releases with status draft may be created on draft app": upload the first release by hand; until then
  choose `draft`.
