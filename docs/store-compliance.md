# Store-Angaben (App Store Connect und Google Play)

Antworten für die Fragebögen, die sich nicht per Fastlane hochladen lassen. Sie müssen zu
`app/ios/Runner/PrivacyInfo.xcprivacy` und `docs/privacy.md` passen; bei Änderungen am Datenfluss alle drei anpassen.

## Apple – App-Datenschutz („Nutzungsdaten“)

Die App sendet Daten ausschließlich an den vom Nutzer eingegebenen Server (nicht an den Anbieter) und nutzt sie
nur für die App-Funktion. Apple verlangt die Angabe trotzdem, sobald Daten die App verlassen.

| Datentyp | Erhoben | Mit Identität verknüpft | Tracking | Zweck |
|---|---|---|---|---|
| Genauer Standort | ja | ja | nein | App-Funktionalität |
| Benutzer-ID (Rufzeichen) | ja | ja | nein | App-Funktionalität |
| Sonstige Nutzerinhalte (Chat, Aufgaben, Notizen) | ja | ja | nein | App-Funktionalität |

- Tracking: nein (`NSPrivacyTracking` = false, keine Tracking-Domains).
- Verschlüsselung: nur Standard-HTTPS, `ITSAppUsesNonExemptEncryption` = false.
- Altersfreigabe: keine Inhalte der Fragebogen-Kategorien, Nutzerchat vorhanden, aber nur in geschlossenen
  Einsatzgruppen per Einladung (kein uneingeschränkter Web-Zugang). Ergebnis voraussichtlich 4+; die Frage nach
  „Nutzergenerierte Inhalte“ ehrlich beantworten.
- Kategorie: Dienstprogramme (primär), Navigation (sekundär).

## Google Play – Datensicherheit

| Frage | Antwort |
|---|---|
| Erhebt oder teilt die App Nutzerdaten? | Ja (Daten verlassen das Gerät Richtung Server der Gruppe) |
| Daten bei der Übertragung verschlüsselt? | Ja (HTTPS/WSS) |
| Können Nutzer die Löschung verlangen? | Ja, beim Server-Betreiber (siehe Datenschutzerklärung) |
| Genauer Standort | erhoben, nicht an Dritte weitergegeben, Zweck: App-Funktionalität, nicht optional |
| Nutzer-IDs (Rufzeichen) | erhoben, Zweck: App-Funktionalität |
| Nachrichten / Sonstige Inhalte | erhoben, Zweck: App-Funktionalität |
| Weitergabe an Dritte | nein (OSM-Kachel-Server erhalten nur IP und Kartenausschnitt, das ist keine Weitergabe von Nutzerdaten im Sinne des Formulars; im Zweifel unter „Ungefährer Standort/IP“ nachsehen) |

- Datenschutzerklärung-URL: `https://ceotjoe.github.io/FoxGrid/privacy` (nach Aktivieren von GitHub Pages).
- Berechtigungen: `INTERNET`, `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `VIBRATE`. Kein Hintergrundstandort,
  daher keine Sondererklärung zu `ACCESS_BACKGROUND_LOCATION` nötig.
- Inhaltseinstufung (IARC): Kategorie „Dienstprogramm/Produktivität“, Nutzerinteraktion: ja (Chat),
  keine Standortweitergabe an andere Nutzer außerhalb der Einsatzgruppe.
- App-Zugriff: Die App ist ohne Server und Einladung nicht nutzbar → im Formular „App-Zugriff“ Demo-Zugang
  (Server-URL und Einladungstoken) angeben, siehe `store/metadata/ios/review_information/notes.txt`.
- Zielgruppe: 18+ ist am einfachsten (Funkamateur-Werkzeug); 13+ ist möglich, löst aber Familienrichtlinien aus.

## Offene Punkte für den Anbieter

- Name und Anschrift in `docs/privacy.md` / `docs/privacy-en.md` eintragen, Entwurfshinweis entfernen.
- Rechtliche Prüfung (Rufzeichen und Standortverläufe sind personenbezogene Daten, siehe Frage 11 in
  `docs/phase0-plan.md`).
- Öffentlichen Demo-Server mit HTTPS für die Store-Prüfung bereitstellen.
