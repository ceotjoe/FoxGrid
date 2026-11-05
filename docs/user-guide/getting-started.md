# Getting started

This guide describes the app from a user's point of view. The in-app labels are German; the German label is given in
parentheses where it matters.

## Create or join a mission

- **Create** ("Einsatz anlegen"): enter the server URL, a mission name, the frequency (any VHF/UHF frequency; below 30 MHz the app
  warns), your callsign and optionally a repeater. You become the mission lead.
- **Invite others:** the person icon shows the invite as token, link (`foxgrid://join?server=…&token=…`) and QR code. Share it only
  in a closed group, see [Access control](mission-lead-security.md).
- **Join:** enter or open the link, give your callsign. Unless the link is an exercise link, you wait on a waiting screen until the
  mission lead approves; the screen shows a four-digit code the lead may ask you for over the radio.
- **Return:** the join screen lists recently used missions ("Zuletzt benutzt"); tapping one rejoins without a new invite on the same
  device.

Release builds connect to HTTPS servers only.

## Roles

| Source | Meaning |
|---|---|
| Mobile ("Mobil") | capture bearings and readings in the field; the default for anyone joining by link |
| Fixed ("Fest") | additionally reports S-values from a fixed omnidirectional station, see [Fixed stations](omni-stations.md) |

What a participant may *do* depends on their **role**: Einsatzleiter, Co-Leiter, Auswerter, Koordinator, Peiler (the default for a
link) or Beobachter (read-only). See [Roles and permissions](roles.md).

## Capture a bearing

1. The map shows participants, rays of all bearings, the most likely location and its error ellipse, live.
2. When the interferer transmits, start a transmission (banner on all devices, push to those in the background); stop it afterwards.
   Only the starter, the lead, a deputy and an analyst can stop it.
3. Capture a bearing at your position: azimuth, whether it is **true or magnetic** (the app converts using the declination for your
   position and shows the value used), and the **uncertainty** (mandatory): sharp ±5°, medium ±15°, poor ±30°, or custom. Optionally
   add a signal strength and a note.
4. Bearings are never deleted. A doubtful bearing can be marked as an **outlier** or deactivated; the log keeps every revision.

## Reading the result

- The orange marker is the maximum-likelihood location; the ellipses are the 1σ and 2σ error regions.
- The filter sheet switches contours (50/80/95 % probability mass), selects transmissions or a time window, enables age weighting and
  toggles the distance rings of fixed stations.
- The bulb icon shows the three best places for the next bearing and the expected gain. It only displays; nobody is sent anywhere.
- Parallel bearings give an elongated ellipse: move so the bearing lines cross at a wide angle.

## More

- [Homing](homing.md): close-range search with signal strength.
- [Fixed stations](omni-stations.md): omnidirectional stations on the repeater input.
- [Roles and permissions](roles.md): who may do what.
- [External bearings](external-bearings.md): the lead or an analyst enters bearings received from outside, e.g. from the BNetzA.
- [Coordination and export](coordination.md): chat, tasks, offline behaviour, export.
- [Known limitations](../reference/limitations.md).
