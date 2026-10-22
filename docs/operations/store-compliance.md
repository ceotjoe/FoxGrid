# Store disclosures (App Store Connect and Google Play)

Answers for the questionnaires that cannot be uploaded through Fastlane. They must match
`app/ios/Runner/PrivacyInfo.xcprivacy` and the [privacy policy](../privacy/privacy.md); when the data flow changes, update all three.

## Apple – App Privacy ("Data Used to Track You" / "Data Linked to You")

The app sends data only to the server entered by the user (not to the publisher) and uses it only for the app's function.
Apple still requires the disclosure as soon as data leaves the app.

| Data type | Collected | Linked to identity | Tracking | Purpose |
|---|---|---|---|---|
| Precise location | yes | yes | no | App functionality |
| User ID (callsign) | yes | yes | no | App functionality |
| Other user content (chat, tasks, notes) | yes | yes | no | App functionality |

- Tracking: no (`NSPrivacyTracking` = false, no tracking domains).
- Encryption: standard HTTPS only, `ITSAppUsesNonExemptEncryption` = false.
- Age rating: no content from the questionnaire categories; user chat exists, but only in closed mission groups by
  invitation (no unrestricted web access). Expected result 4+; answer the "user-generated content" question honestly.
- Category: Utilities (primary), Navigation (secondary).

## Google Play – Data safety

| Question | Answer |
|---|---|
| Does the app collect or share user data? | Yes (data leaves the device towards the group's server) |
| Is data encrypted in transit? | Yes (HTTPS/WSS) |
| Can users request deletion? | Yes, from the server operator (see privacy policy) |
| Precise location | collected, not shared with third parties, purpose: app functionality, not optional |
| User IDs (callsign) | collected, purpose: app functionality |
| Messages / other content | collected, purpose: app functionality |
| Device or other IDs (push token) | collected, purpose: app functionality (notification when a transmission starts); handed to Google FCM for delivery (service provider) |
| Sharing with third parties | no (push delivery via Google FCM/Apple APNs is processing on behalf; OSM tile servers only receive IP and map section, which is not sharing of user data in the sense of the form; when in doubt check under "Approximate location/IP") |

- Privacy policy URL: `https://ceotjoe.github.io/FoxGrid/privacy` (after enabling GitHub Pages).
- Permissions: `INTERNET`, `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `VIBRATE`, `POST_NOTIFICATIONS`. No background location,
  so no special declaration for `ACCESS_BACKGROUND_LOCATION` is needed.
- Content rating (IARC): category "Utility/Productivity", user interaction: yes (chat),
  no sharing of location with other users outside the mission group.
- App access: the app is unusable without a server and an invite → in the "App access" form provide demo access
  (server URL and invite token), see `store/metadata/ios/review_information/notes.txt`.
- Target audience: 18+ is simplest (tool for radio amateurs); 13+ is possible but triggers the families policy.

## Open items for the publisher

- Enter name and address in `docs/privacy/privacy.md` / `privacy.de.md` and remove the draft notice.
- Legal review (callsigns and location tracks are personal data; see the notes on GDPR in the
  [phase 0 plan](../adr/archive/phase0-plan.md), question 11).
- Provide a public demo server with HTTPS for the store review.
