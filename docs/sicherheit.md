# Sicherheit im Einsatz

FoxGrid hat keine Passwörter. Der Zugang zu einem Einsatz hängt an einem **Einladungslink**. Wer den Link kennt,
könnte ohne weitere Maßnahmen mitlesen oder falsche Peilungen einspeisen. Dieses Dokument beschreibt, was FoxGrid
dagegen tut, was die Einsatzleitung selbst tun sollte und was bewusst nicht abgedeckt ist.

## Was passieren kann

| Fall | Beispiel | Gegenmittel in FoxGrid |
|---|---|---|
| Link wird bekannt | Er steht in einer Gruppe, in der auch der Störer mitliest | Ablauf nach 24 h, Nutzungsgrenze, „Link ersetzen“, Freigabe durch die Leitung |
| Rufzeichen wird übernommen | Jemand meldet sich als ein Kollege an, der noch nicht dabei ist | Rufzeichen sind an ein Gerät gebunden; Beitritts-Code per Funk |
| Falsche Daten | Jemand schickt Peilungen in die falsche Richtung | Vertrauensstufe, Quarantäne, Auffälligkeits-Hinweise |
| Überflutung | Chat oder Peilungen werden massenhaft gesendet | Rate-Limits (HTTP 429) |
| Fremdes Gerät | Handy verloren oder gestohlen | Teilnehmer entfernen, Gerät freigeben |

## Was FoxGrid tut

1. **Freigabe-Warteschlange.** Wer über einen Link beitritt, sieht nur einen Wartebildschirm. Karte, Peilungen, Chat, Live-Kanal
   und Push-Meldungen bleiben gesperrt, bis die Einsatzleitung im Menü „Teilnehmer“ freigibt. Abgelehnte kommen mit dem Link
   nicht wieder hinein.
2. **Beitritts-Code.** Der Wartebildschirm zeigt vier Ziffern. Dieselben stehen bei der Leitung neben dem Eintrag. Die Leitung
   fragt per Funk nach dem Code: Nur wer wirklich vor dem Gerät sitzt, kann ihn nennen. Wer sich als ein Kollege ausgibt, der
   nicht beigetreten ist, kann ihn nicht nennen.
3. **Gerätebindung.** Jede Installation erzeugt ein zufälliges Geheimnis; der Server speichert nur einen Hash. Ein bestehendes
   Rufzeichen lässt sich nur mit demselben Geheimnis erneut betreten. Beim Handywechsel gibt die Leitung das Gerät frei.
4. **Rollen nur von der Leitung.** Über einen Link tritt man immer als „Mobil“ bei. „Fest“ und „Leitung“ vergibt die Leitung.
5. **Vertrauen.** Nur vertraute Teilnehmer bewegen die Schätzung. Freigabe und Beförderung durch die Leitung gelten als Vertrauen.
   Links mit `auto_approve` (für Übungen) liefern zunächst nicht vertraute Teilnehmer: ihre Peilungen sind sichtbar und im
   Protokoll, ändern das Ergebnis aber nicht, bis die Leitung ihnen vertraut.
6. **Quarantäne.** Nimmt alle Peilungen und Messwerte eines Teilnehmers auf einmal aus der Schätzung, entzieht das Vertrauen und
   kann ihn zugleich entfernen. Nichts wird gelöscht: Das Protokoll bleibt vollständig, jede Peilung trägt eine Revision.
7. **Auffälligkeiten.** Die Leitung kann prüfen lassen, wessen Daten nicht zusammenpassen (Peilungen gegen das Ergebnis der anderen,
   Positionssprünge, Standort der Peilung gegen den eigenen Positionsverlauf). Das sind Hinweise, keine Urteile.
8. **Rate-Limits.** Beitritte pro Absender-Adresse, Peilungen, Messwerte und Chat pro Teilnehmer. Die App sendet bei 429 später erneut.
9. **Sicherheitsprotokoll.** Die Leitung sieht, wer wann beigetreten, freigegeben, entfernt oder unter Quarantäne gestellt wurde und
   wer Einladungen erzeugt oder ersetzt hat. Fehlversuche von fremden Geräten stehen ebenfalls drin.

## Checkliste für die Einsatzleitung

**Vorher**

- Den Link nicht in offene oder gemischte Gruppen posten. Besser: persönlich, per QR oder in einer Gruppe, in der nur das Team ist.
- Die Funkgruppe festlegen, über die der Beitritts-Code abgefragt wird.
- Für Übungen mit bekanntem Teilnehmerkreis darf ein `auto_approve`-Link benutzt werden; im Ernstfall nicht.

**Während des Einsatzes**

- Neue Einträge unter „Teilnehmer“ nur freigeben, wenn der Code per Funk stimmt und das Rufzeichen zu einer bekannten Person gehört.
- Nach dem Aufbau des Teams den Link **ersetzen** (Einladungs-Dialog → „Link ersetzen“). Wer schon drin ist, bleibt drin.
- Ab und zu die Auffälligkeiten prüfen (Lupe im Teilnehmer-Menü), besonders wenn das Ergebnis plötzlich springt.
- Bei Verdacht: erst **Vertrauen entziehen** (Daten zählen nicht mehr, nichts geht verloren), bei Bestätigung **Quarantäne**
  und entfernen.

**Nachher**

- Das Sicherheitsprotokoll durchsehen, bevor der Einsatz archiviert wird. Es gehört zum Protokoll des Einsatzes.
- Einsatz beenden: Danach können keine neuen Teilnehmer mehr beitreten.

## Was nicht abgedeckt ist

- **Mitlesen des Funkverkehrs** und alles, was außerhalb von FoxGrid passiert.
- **Ein übernommenes Gerät, das entsperrt ist.** Die Gerätebindung schützt vor dem Link, nicht vor einem Angreifer mit dem Handy.
  Die Leitung muss das Konto entfernen.
- **Ein kompromittierter Server.** Die Geräte-Geheimnisse liegen dort nur als Hash, aber wer den Server beherrscht, sieht die Einsatzdaten.
- **Ein vertrauter Teilnehmer, der absichtlich schlechte Daten liefert.** Die Schätzung verträgt einzelne Ausreißer, ein gezielter
  Angriff mit mehreren vertrauten Konten nicht. Das ist eine Sache der Auswahl der Leute.
- Das Geheimnis liegt in den App-Einstellungen (SharedPreferences), nicht im Schlüsselbund. Ein Gerät mit Root-Zugriff kann es auslesen.
- Das Zurücknehmen einer Quarantäne ist nur Peilung für Peilung möglich.

## Betrieb

- Hinter einem Reverse-Proxy: `FORWARDED_ALLOW_IPS` für uvicorn auf die Proxy-Adresse setzen, sonst teilen sich alle Nutzer einen
  Beitritts-Zähler und Rate-Limits greifen zu früh.
- Grenzen anpassbar: `FOXGRID_INVITE_TTL_HOURS`, `FOXGRID_INVITE_MAX_USES`, `FOXGRID_RATE_*_PER_MIN` (siehe README).
- HTTPS ist in Release-Builds Pflicht; ohne TLS lesen Unbeteiligte Token und Daten mit.
