# Release: App Store und Google Play

Ein Git-Tag `v<version>` löst `.github/workflows/release.yml` aus: Tests, signierte Builds für Android und iOS,
Upload nach Google Play (Spur `internal`) und TestFlight, dazu ein GitHub-Release mit AAB und IPA.
Die Freigabe zur Prüfung bei Apple und die Veröffentlichung in Produktion bleiben bewusst manuell.

## Ablauf eines Releases

1. In `app/pubspec.yaml` die Version setzen (`version: 0.2.0+1`, der Teil nach `+` wird in CI ersetzt).
2. Änderungstext in `store/metadata/android/*/changelogs/default.txt` und
   `store/metadata/ios/*/release_notes.txt` anpassen.
3. Commit, dann `git tag v0.2.0 && git push --tags`. Der Tag muss zur `pubspec.yaml`-Version passen, sonst bricht
   der Lauf ab.
4. Der Lauf wartet an der GitHub-Umgebung `store-release` (siehe unten) auf eure Freigabe.
5. Google Play: Release in der Play Console von `internal` auf `beta`/`production` hochstufen.
   TestFlight: Build in App Store Connect der Version zuordnen und zur Prüfung einreichen.

Manueller Probelauf ohne Upload: Actions > Release > Run workflow (Häkchen „publish“ aus). AAB und IPA liegen
danach als Artefakte am Lauf. Die Build-Nummer ist `github.run_number` (+ optionale Repository-Variable
`BUILD_NUMBER_OFFSET`, falls ein Store schon höhere Nummern kennt).

Nur Texte, Grafiken und Screenshots aktualisieren: Actions > Store metadata > Run workflow.

## Einmalige Einrichtung

### GitHub

- Settings > Environments > `store-release` anlegen, unter „Required reviewers“ euch selbst eintragen.
  Alle Secrets unten als **Environment secrets** dieser Umgebung speichern.
- Settings > Pages > Source „Deploy from a branch“, Branch `main`, Ordner `/docs`. Danach sind die
  Datenschutzerklärungen unter `https://<user>.github.io/<repo>/privacy` und `/privacy-en` erreichbar. Die URLs
  stehen in `store/metadata/ios/*/privacy_url.txt` und `docs/store-compliance.md`; sie sind auf
  `ceotjoe/FoxGrid` voreingestellt und anzupassen, falls das Repository anders heißt.

### Android (Google Play)

1. Upload-Schlüssel erzeugen und **sicher** (Passwortmanager) aufbewahren:
   ```bash
   keytool -genkeypair -v -keystore foxgrid-upload.jks -alias upload -keyalg RSA -keysize 4096 -validity 10000
   ```
   Mit „Play App Signing“ (Standard bei neuen Apps) behält Google den eigentlichen Signierschlüssel; geht der
   Upload-Schlüssel verloren, lässt er sich über den Play-Support zurücksetzen.
2. App in der Play Console anlegen (Paketname `com.itwebservice.foxgrid`), Fragebögen ausfüllen
   (`docs/store-compliance.md`) und **den ersten Release einmal von Hand** hochladen (bei einer neuen App verlangt
   Google das). Danach kann die Automatisierung übernehmen. Bis die App erstmals veröffentlicht wurde, beim
   manuellen Lauf `play_release_status = draft` wählen.
3. Dienstkonto für die API: Play Console > Einrichtung > API-Zugriff > Dienstkonto anlegen, Rolle „Release-Manager“
   (oder mindestens Rechte für Releases und Store-Eintrag), JSON-Schlüssel herunterladen.

| Secret | Inhalt |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | `base64 -i foxgrid-upload.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | Keystore-Passwort |
| `ANDROID_KEY_ALIAS` | `upload` |
| `ANDROID_KEY_PASSWORD` | Passwort des Schlüssels |
| `PLAY_SERVICE_ACCOUNT_JSON` | gesamter Inhalt der JSON-Datei |

Lokaler Release-Build: `app/android/key.properties.example` nach `key.properties` kopieren und ausfüllen.
Ohne Keystore signiert Gradle mit dem Debug-Schlüssel; CI weist solche Bundles ab.

### iOS (App Store Connect)

1. App in App Store Connect anlegen (Bundle-ID `com.itwebservice.foxgrid`, Team `Q486NF4XF6`).
2. Zertifikat „Apple Distribution“ erzeugen (Xcode > Settings > Accounts > Manage Certificates oder im
   Developer-Portal) und mit privatem Schlüssel als `.p12` aus der Schlüsselbundverwaltung exportieren.
3. Im Developer-Portal ein Provisioning-Profil vom Typ **App Store** für die Bundle-ID anlegen. Der **Name** muss
   `FoxGrid App Store` lauten (siehe `app/ios/ExportOptions.plist` und `IOS_PROFILE` in `fastlane/Fastfile`).
4. App Store Connect > Benutzer und Zugriff > Integrationen > API-Schlüssel (Rolle „App Manager“) anlegen,
   `.p8` herunterladen (nur einmal möglich).

| Secret | Inhalt |
|---|---|
| `IOS_DIST_CERT_P12_BASE64` | `base64 -i dist.p12` |
| `IOS_DIST_CERT_PASSWORD` | Passwort der `.p12` |
| `IOS_PROVISIONING_PROFILE_BASE64` | `base64 -i FoxGrid_App_Store.mobileprovision` |
| `ASC_KEY_ID`, `ASC_ISSUER_ID` | aus der API-Schlüsselseite |
| `ASC_KEY_P8` | gesamter Inhalt der `.p8` (inkl. BEGIN/END-Zeilen) |

Für den Workflow „Store metadata“ (iOS) zusätzlich, weil Apple Prüfer-Kontakt und Demo-Zugang verlangt:
`REVIEW_FIRST_NAME`, `REVIEW_LAST_NAME`, `REVIEW_PHONE`, `REVIEW_EMAIL`, `REVIEW_DEMO_SERVER` (HTTPS-URL eines
öffentlichen Demo-Servers) und `REVIEW_DEMO_INVITE` (Einladungstoken eines Demo-Einsatzes). Die Texte stehen in
`store/metadata/ios/review_information/notes.txt`. Die App akzeptiert in Store-Builds nur HTTPS-Server, der
Demo-Server braucht also ein gültiges Zertifikat.

## Was nicht automatisiert ist

- Altersfreigabe, Datenschutz-Fragebögen, Inhaltseinstufung, Zielgruppe: `docs/store-compliance.md`.
- Preis/Verfügbarkeit, Einreichung zur App-Prüfung, Stufenweise Veröffentlichung.
- App-Store-Icon (1024 px) hochladen: `store/app-store-icon-1024.png` (Fastlane lädt es nicht hoch).
- Datenschutzerklärung: Name und Anschrift eintragen, Entwurfshinweis entfernen, rechtlich prüfen.

## Grafiken und Texte

- Texte: `store/metadata/{ios,android}/<de-DE|en-US>/`. Grenzen: Name/Titel/Untertitel 30 Zeichen, Play-Kurztext 80,
  iOS-Keywords 100, Beschreibung 4000.
- Screenshots: Rohbilder aus der laufenden App in `store/screenshots/raw/<gerät>/NN_name.png`, Beschriftungen in
  `store/captions.json`, dann `python3 tools/store/generate_assets.py` (braucht `rsvg-convert` und ImageMagick).
  Die Ausgabe landet im Fastlane-Layout unter `store/metadata/`. Die App-Oberfläche ist deutsch, die englischen
  Listings zeigen deshalb dieselben Bildschirme mit englischer Beschriftung.
- Rohbilder entstehen so: Stack mit `docker compose up -d`, Demo-Einsatz mit `uv run tools/simulator/run.py`,
  App im Simulator/Emulator gegen `http://localhost:8000` (nur Debug-Builds erlauben HTTP), Statusleiste mit
  `xcrun simctl status_bar booted override --time 9:41 ...`.

## Fehlersuche

- `The bundle is signed with the debug key`: Secrets `ANDROID_KEYSTORE_*` prüfen.
- `Version code N has already been used`: Repository-Variable `BUILD_NUMBER_OFFSET` erhöhen.
- iOS „No profile for team/bundle“: Profilname muss exakt `FoxGrid App Store` sein und zum Zertifikat passen.
- Google Play „Only releases with status draft may be created on draft app“: erster Release von Hand, bis dahin
  `draft` wählen.
