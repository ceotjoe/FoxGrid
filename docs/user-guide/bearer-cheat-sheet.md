# FoxGrid – Cheat sheet for bearers (*Peiler*)

*One A4 page, meant to be printed and handed out. UI labels are German, as in the app.*

## 1 · Join
1. Open the invite **link / QR code** from the mission lead (`foxgrid://join?…`). Share it only inside the closed team.
2. Enter your **callsign**.
3. Wait on the waiting screen until the lead approves. It shows a **4-digit code** – the lead may ask you for it over the radio.
4. Next time: **"Zuletzt benutzt"** on the join screen rejoins without a new invite (same device only).

## 2 · Take a bearing
| Step | What to do |
|---|---|
| 1 | Watch for the **transmission banner** (push if the app is in the background) – the lead or others start/stop transmissions. |
| 2 | Take the bearing with your own equipment, standing at your position (GPS must be on). |
| 3 | Enter the **azimuth** and choose **true (rechtweisend) or magnetic**. The app converts using the declination for your position and shows the value it used. |
| 4 | Choose the **uncertainty σ** – it is **mandatory**. |
| 5 | Optional: signal strength and a note. Save. |

| Uncertainty | Use when |
|---|---|
| **Sharp ±5°** | clear, stable bearing |
| **Medium ±15°** | usable, some spread |
| **Poor ±30°** | weak, reflected, unsure |
| Custom | you know better |

*Be honest with σ: a too sharp value pulls the estimate wrongly, a wide one is simply weighted less.*

## 3 · Read the map
- **Orange marker** = most likely location of the interferer. **Ellipses** = 1σ and 2σ error region.
- **Rays** = all bearings. Elongated ellipse = bearings are nearly parallel.
- **Bulb icon** = the 3 best spots for your next bearing. It only suggests; nobody is sent anywhere.
- **Filter sheet:** contours (50/80/95 %), pick transmissions or time window, age weighting, distance rings of fixed stations.
- **Move so that the bearing lines cross at a wide angle** – that shrinks the ellipse fastest.

## 4 · Close range – homing (compass icon)
- Big **arrow** points to the most likely location, with distance. Inside the 1σ region you get a note.
- Arrow source: GPS course above 1.5 m/s, otherwise compass + declination.
- **Quick entry** at the bottom: S-buttons **S1 … S9+60** (S9 = −93 dBm, 6 dB per S-unit), a level field (dBm: no sign = negative, `+5` = positive, ± button cycles the sign; the unit button switches to S values like `7` or `9+20` and is remembered).
- **Attenuator** (off / 10 / 20 / 30 / 40 dB): select the value you really use – it is corrected afterwards.
- Switch **"log the last value every 2 s"** records a series. At least **5 readings** are needed before they count.
- Track colour: blue = weak, red = strong. Reflections distort levels – **bearings stay more reliable**.

## 5 · Team work
- **Chat:** mission channel and team channels. **Tasks:** work on what is assigned to you and update the status.
- You **see** the positions of the others; they see yours.
- Observers (guests) see the result but no chat and no positions.

## 6 · Offline & sync
- Everything is written **locally first**, then sent automatically (retry with backoff). The **sync bar at the top is always visible**; failed entries stay listed.
- Without network: bearings, readings, chat and outlier flags are queued. **Position updates are not re-sent.**
- The automatic declination needs network **once**, then the cached value is used. Maps show only tiles you have already viewed.

## 7 · Corrections
- **Bearings are never deleted.** A doubtful bearing is flagged as **outlier** or deactivated; edits are kept as revisions.
- Only the lead, deputy and analyst may flag *other people's* bearings. Wrong entry of your own: tell the analyst or lead in the chat.

## 8 · What you may and may not do
| You can | You cannot |
|---|---|
| bearings and readings, chat, tasks assigned to you, share position, export (GPX/KML/JSON/PDF) | enter external bearings, flag others' bearings, stop others' transmissions, create tasks or invites, change roles, end the mission |
