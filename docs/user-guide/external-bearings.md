# External bearings (e.g. from the BNetzA)

Sometimes bearings reach the mission lead from outside the group, for example from the Bundesnetzagentur. The lead, a deputy or an
analyst enters them at a named **bearing point**, and they join the estimate like any other bearing. Other roles can see the
points and their bearings but not create or change them (see [Roles and permissions](roles.md)).

## Add a point

*Menu → verwalten → Externe Peilpunkte → Peilpunkt.* Give it a name (unique within the mission, for example "BNetzA Köln") and set the
location in any of three ways. They all move the same marker:

- tap on the map,
- type the coordinates: decimal degrees (`50.9`, `50,9`), degrees and minutes (`50° 54.5' N`) or degrees, minutes, seconds; use N/S/E/W
  (or O for east) instead of a sign if you like,
- **Mein Standort** takes the device location (including its accuracy).

The switch *In Schätzung einbeziehen* decides whether the point's bearings move the estimate. It can be changed later in the list.

## Enter bearings

After saving a point, the entry sheet opens at once; later use the **+** on the point in the list. Enter the azimuth in degrees,
**true north (rechtweisend)**, which is how regulators report it, a sigma (sharp ±5°, medium ±15°, poor ±30°) and a note. The
measurement time defaults to now; tap it to set an earlier time. *Speichern + weitere* keeps the sheet open for the next value.

The bearing is drawn from the point's position, never from your device. It works offline like everything else and is sent later.

## Good to know

- A point's position cannot be edited. If it is wrong, add a new point and deactivate the old one (its bearings stay in the log but no
  longer count).
- Switching a point off or deactivating it removes its bearings from the estimate. They stay listed and exported, and are drawn dashed.
- On the map each point has its own colour and a label. *Filter → Externe Peilungen anzeigen* hides them from the display only; the
  estimate does not change.
- Exports (PDF, GPX, KML, JSON) name the point: bearings read "extern: BNetzA Köln", and a point that does not count is marked
  "nicht in Schätzung".
- Points and their bearings are never deleted, like all bearings.
