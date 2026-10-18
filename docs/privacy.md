---
title: Datenschutzerklärung – FoxGrid
permalink: /privacy
---

# Datenschutzerklärung FoxGrid

*English version: [Privacy policy](privacy-en)*

Stand: 17. Oktober 2026

> **ENTWURF – vor der Veröffentlichung prüfen.** Die Angaben unter „Verantwortlicher“ und „Betreiber des Servers“
> sind auszufüllen, der Text sollte rechtlich geprüft werden. Danach diesen Hinweis entfernen.

## 1. Worum es geht

FoxGrid ist eine App für Funkamateure, mit der eine Gruppe gemeinsam einen Störsender im VHF/UHF-Bereich (z. B. auf einem Relais)
peilt. Die App ist ein **Client für einen FoxGrid-Server, den eure Gruppe selbst betreibt**. Es gibt keinen
zentralen FoxGrid-Dienst des App-Anbieters.

## 2. Verantwortlicher

Für die App (Herausgeber im App Store und bei Google Play):
[Name, Anschrift, E-Mail des Anbieters]

Der Anbieter der App erhebt, speichert und empfängt **keine** personenbezogenen Daten aus der Nutzung der App.

Für alle Daten, die beim Benutzen eines FoxGrid-Servers anfallen, ist **der Betreiber des jeweiligen Servers**
verantwortlich (in der Regel die Person oder der Verein, die euch den Einladungslink gegeben hat).
Wendet euch für Auskunft, Berichtigung und Löschung an diese Stelle.

## 3. Welche Daten die App verarbeitet

Beim Beitritt zu einem Einsatz und während der Nutzung sendet die App an den von euch eingegebenen Server:

| Daten | Zweck | Wann |
|---|---|---|
| Rufzeichen und Rolle (mobil/fest) | Zuordnung von Peilungen, Chat und Aufgaben zu Teilnehmenden | Beitritt |
| Standort (Breite, Länge, Genauigkeit) | Position bei Peilungen; Anzeige der Teilnehmenden auf der Karte | nur bei geöffneter App, nachdem ihr den Standortzugriff erlaubt habt |
| Peilungen (Zeit, Position, Azimut, Unsicherheit, Feldstärke, Notiz) | Berechnung des wahrscheinlichsten Störer-Standorts | wenn ihr eine Peilung speichert |
| Pegelwerte (S-Meter/dBm) | Nahpeilung und Schätzung | wenn ihr sie erfasst |
| Chatnachrichten und Aufgaben | Zusammenarbeit im Team | wenn ihr sie sendet |
| Zugangstoken (JWT) | Anmeldung am Server ohne Passwort | Beitritt |

Die App fragt **keinen Standortzugriff im Hintergrund** an. Es gibt keine Werbung, keine Analyse- und
Tracking-Werkzeuge und keine Weitergabe an Dritte durch die App.

## 4. Speicherung auf dem Gerät

Zugangsdaten, Einstellungen, noch nicht übertragene Eingaben (Offline-Warteschlange) und geladene Karten-
kacheln werden lokal auf eurem Gerät gespeichert. Beim Deinstallieren der App werden sie entfernt.

## 5. Speicherdauer auf dem Server

Der Betreiber legt die Aufbewahrung fest. Voreinstellung der FoxGrid-Software: Positionsverläufe werden
30 Tage nach Ende eines Einsatzes gelöscht. Peilungen bleiben zur Nachvollziehbarkeit erhalten (sie werden
nie gelöscht, nur als Ausreißer markiert oder deaktiviert). Wer die Löschung seiner Daten verlangen möchte,
wendet sich an den Betreiber des Servers.

## 6. Kartenkacheln

Die Kartenansicht lädt Kacheln direkt von Servern von OpenStreetMap (tile.openstreetmap.org) oder
OpenTopoMap (opentopomap.org). Dabei wird technisch bedingt eure IP-Adresse an diese Dienste übertragen,
ebenso der ausgewählte Kartenausschnitt. Es gelten deren Datenschutzhinweise:
<https://wiki.osmfoundation.org/wiki/Privacy_Policy> und <https://opentopomap.org/about>.

## 7. Verbindung

Die App verbindet sich in der Store-Version ausschließlich per HTTPS bzw. WSS mit dem Server.

## 8. Eure Rechte

Ihr habt nach der DSGVO das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung,
Datenübertragbarkeit und Widerspruch sowie das Recht, euch bei einer Aufsichtsbehörde zu beschweren.
Gegenüber dem Server-Betreiber macht ihr diese Rechte geltend; die App bietet dafür den Export eines Einsatzes.

## 9. Kontakt

[E-Mail des Anbieters]

Quellcode und Fehlermeldungen: <https://github.com/ceotjoe/FoxGrid>
