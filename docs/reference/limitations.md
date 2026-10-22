# Known limitations

- **Web:** the offline queue lives in memory only, because no sqlite-WASM files are shipped; on Android/iOS it is persistent
  (SQLite). No tile cache in the browser (it uses the HTTP cache). No push on the web (needs a VAPID key and a service worker).
- **Position updates** are not resent when the connection is missing (only bearings, chat, tasks, outlier flags and transmissions go
  through the queue).
- **Declination:** the automatic value needs network once; afterwards the cached value applies.
- **Map tiles** come from `tile.openstreetmap.org` and `tile.opentopomap.org`. Their usage policies forbid bulk downloads; for
  production and offline areas you need your own tile server (bulk download is blocked for public OSM servers in the app).
- **CAT radio control:** protocols (Icom CI-V, Kenwood/Yaesu ASCII), calibration, profiles (IC-705, IC-9700, Kenwood, Yaesu FT-991A)
  and a polling service exist, but **no transport**. USB-OTG and Bluetooth each need a platform plugin and hardware to test; until
  then S-values are typed in. The raw scales of the radios are approximations; the calibration in the settings compensates.
- **RSSI fusion:** the model assumes a source with isotropic radiation and Gaussian scatter (default 6 dB). Reflections and shadowing
  create outliers that are only absorbed by the scatter. With fewer than 5 readings the track is ignored. The S9 convention (−93 dBm)
  holds for VHF/UHF (above about 30 MHz), not for HF; below 30 MHz the app warns when a mission is created.
- **Homing arrow:** uses the GPS course above 1.5 m/s, otherwise compass plus declination; without a compass (web) it points
  relative to north.
- **Position suggestions** use the Fisher information of the bearings (Gaussian approximation without outlier share and without
  RSSI) and prefer places near the target at equal angular accuracy. Terrain, roads and reachability are unknown to the engine; only
  the mission's search area restricts the candidates.
- **Fixed stations** give only a coarse area (kilometres), see [Engine](../concepts/engine.md#fixed-omnidirectional-stations).
- **MQTT:** the key is in every message, so without TLS at the broker it can be read (see [MQTT interface](mqtt.md)). The relay hook
  and the bearing stations are only tested against simulation and a test broker, not on real hardware. The relay controller must
  report its state as `{"squelch": …, "ctcss": …}` over MQTT.
- **Deep links** (`foxgrid://join?...`) are registered but not yet tried on a real device. The QR scanner is missing (the app shows
  QR codes but cannot scan them).
- **Engine:** the PNG raster output is not implemented.
- **Quarantine** cannot be undone in bulk; reactivate bearings one by one.
- **Live channel:** no replay by sequence number; clients reload the snapshot after a reconnect.
