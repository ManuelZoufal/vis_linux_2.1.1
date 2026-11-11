# Änderungsverlauf

Die Anwendung zeigt diese Datei unter „Was ist neu“ an (Klick auf die Versionsnummer in der Navigationsleiste).
Format: eine Überschrift `## <Version> – <Datum>` je Version, darunter eine Zeile mit `- ` je Änderung.

## 2.1.22 – 2026-11-11
- Seite „Was ist neu“ mit dem Änderungsverlauf, erreichbar über die Versionsnummer in der Navigationsleiste
- Geplante Aktionen haben ein Feld für eine kurze Beschreibung; sie erscheint in der Liste, im Thread-Status und im Ereignisprotokoll
- Automatisches Zertifikatsmanagement: Ist das Zertifikat nur noch einen Tag gültig, stellt die Anwendung ein neues aus und verwendet es ohne Neustart. Liegen CA-Zertifikat und CA-Schlüssel auf dem Server, wird damit ausgestellt, sonst selbstsigniert
- Fehlt beim Start ein Zertifikat, wird eines erzeugt, statt den Start abzubrechen
- Knopf „Zertifikat jetzt erneuern“ unter „Logs“

## 2.1.21 – 2026-11-11
- Seite „Visualisierung“ als Kachelansicht: je Gruppe eine große Kachel mit der verkleinerten, live laufenden Belegungsanzeige als Vorschau
- Ein Klick öffnet die Anzeige

## 2.1.20 – 2026-11-11
- Automatische Tests (`tests/`, siehe Abschnitt „Tests“)
- Zwei Befunde der Tests behoben: das Skript der Seite „Visualisierung konfigurieren“ löste beim Laden einen Fehler aus und wurde entfernt (das Formular funktioniert ohne es)
- Der Export des Änderungsprotokolls nennt die Datei jetzt mit vollem Pfad

## 2.1.19 – 2026-11-11
- Weniger Protokollvolumen: erfolgreiche Abfragen, Uploads und die Zeilen des Webservers je Anfrage stehen nur noch im Debug-Modus im Server-Log
- Das Änderungsprotokoll ist wie die anderen Protokolle auf `LOG_MAX_MB` begrenzt, und die Seite „Logs“ lädt nur die neuesten 500 Einträge (neueste zuerst)
- Das ausführliche Server-Log lässt sich unter „Logs“ für 15 Minuten bis 24 Stunden ohne Neustart einschalten

## 2.1.18 – 2026-11-11
- Hanwha-Kameras: Der Ausweichweg über HTTP greift jetzt auch, wenn die Kamera die Verbindung auf Port 443 annimmt, aber den TLS-Handshake nicht abschließt
- Die TLS-Fähigkeit wird vor dem Senden eines Steuerbefehls geprüft

## 2.1.17 – 2026-11-11
- Schalter „Zählung aktiv“ je Sensor (`"counting": false` in `config.json`) für Geräte ohne Zählfunktion, z. B. Heatmap-Kameras: keine Abfrage, kein Zurücksetzen, kein Upload zu Navigator, kein Beitrag zur Belegung
- Neustart bleibt möglich
- Im Thread-Status „Keine Zählung“ statt Fehler
- Zurücksetzen und Neustart melden den Grund, wenn sie scheitern

## 2.1.16 – 2026-11-11
- Hanwha-Kameras: Zurücksetzen und Neustart gehen über HTTP, wenn die Kamera auf HTTPS nicht antwortet
- Der funktionierende Weg wird gemerkt und im Ereignisprotokoll vermerkt

## 2.1.15 – 2026-11-11
- Ereignisprotokoll (Ausfälle, Erholungen, Zeitpläne mit Grund je Sensor) und zeitlich begrenztes Detail-Protokoll unter „Logs“, je Datei auf `LOG_MAX_MB` (200 MB) begrenzt
- Kurze Fehlertexte statt ganzer Antwortseiten
- Navigator fordert nach 5 Fehlversuchen nur noch alle `NAVIGATOR_RETRY_MINUTES` (15) Minuten ein Token an

## 2.1.14 – 2026-11-10
- Aufräumen: ungenutzter Code entfernt (Tabellen `roles` und `schedules`, der Thread „Datenbankauszug“, ungenutzte Importe), Laufzeitdateien und `__pycache__` nicht mehr im Repository, Vorlage `env` heißt `.env.example`
- Die Seite „Logs“ verträgt ein fehlendes oder beschädigtes Änderungsprotokoll

## 2.1.13 – 2026-11-10
- Eingaben bei Gruppen und beim Bearbeiten von Sensoren werden geprüft (Meldung statt Fehlerseite)
- Maximale Belegung wird als Zahl gespeichert
- Sensoren, Gruppen und IP-Adressen sortieren numerisch
- Beim Löschen einer Gruppe werden ihre Bilder entfernt
- Der Datenpunkt eines noch nie erreichten Sensors geht beim Bearbeiten nicht mehr verloren
- Fehlertexte enthalten bei HTTP-Fehlern die Antwort des Sensors

## 2.1.12 – 2026-11-10
- Ablaufdatum des Zertifikats unter „Logs“, im Export und als Hinweis für Administratoren ab 30 Tagen vor Ablauf (`CERT_WARN_DAYS`)
- Zertifikat und Schlüssel sind nicht mehr Teil des Repositorys

## 2.1.11 – 2026-11-10
- Sensor-Zugangsdaten in `.env` statt in `config.json`: Standard je Sensortyp (`SENSOR_IEE_PASSWORD`, `SENSOR_HANWHA_USERNAME`, `SENSOR_HANWHA_PASSWORD`) und Einzelwerte je Sensor (`SENSOR_<ID>_USERNAME`, `SENSOR_<ID>_PASSWORD`)
- Seite „Sensor-Zugang“ zum Ändern, Prüfen und zum Übernehmen der alten Werte aus `config.json`

## 2.1.10 – 2026-11-10
- Abschnitt „Debug-Informationen“ unter „Logs“ entfernt (zeigte nur „is active“ je Thread, die Angabe „inactive“ konnte nie erscheinen)
- Stattdessen lässt sich der Thread-Status als Textdatei exportieren

## 2.1.9 – 2026-11-10
- Navigator: ein Token wird für alle Uploads wiederverwendet statt für jeden Sensor neu angefordert
- Sensoren ohne Datenpunkt werden übersprungen
- Platzhalterbild für den Wartungsmodus (`static/images/maintenance.png`)

## 2.1.8 – 2026-11-10
- Chart.js wird lokal aus `static/vendor/` ausgeliefert statt vom CDN: die Belegungsanzeige funktioniert ohne Internetzugang des Anzeigegeräts

## 2.1.7 – 2026-11-10
- Login-Sperre nach wiederholten Fehlversuchen (`LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCK_MINUTES`)
- Rollenänderungen und gelöschte Benutzer wirken sofort statt erst nach Ablauf der Sitzung
- Das eigene Konto und der letzte Administrator lassen sich nicht löschen oder herabstufen

## 2.1.6 – 2026-11-10
- Zeitstempel folgen der Sommerzeit (`APP_TIMEZONE`, Standard `Europe/Berlin`)
- Änderungen an `config.json` laufen unter einer Sperre und werden atomar geschrieben
- Navigator-Zugangsdaten lassen sich als Administrator unter „Navigator-Zugang“ ändern und testen

## 2.1.5 – 2026-11-10
- Virtuelle Sensoren stören den Start nicht mehr und lassen sich bearbeiten (Name, Gruppe, Belegung)
- Gruppe löschen legt die Standardgruppe nur einmal an und verschiebt die Sensoren korrekt
- Passwort ändern funktioniert für alle Rollen
- Ein doppelter Benutzername ergibt eine Meldung statt einer Fehlerseite
- Meldungen werden auf allen Seiten der Benutzerverwaltung angezeigt

## 2.1.4 – 2026-11-10
- Zeitpläne: Bearbeiten ändert den bestehenden Zeitplan statt einen neuen anzulegen
- Gelöschte und geänderte Zeitpläne wirken sofort statt erst nach einem Neustart
- Wöchentliche Zeitpläne funktionieren
- Eingaben werden geprüft
- Ein fehlgeschlagener Sensor bricht die Aktion für die übrigen nicht mehr ab
- Änderungen stehen im Änderungsprotokoll

## 2.1.3 – 2026-11-10
- Anmeldepflicht für die schreibende API und die Visualisierungs-Konfiguration
- Namen und Texte werden in der Oberfläche als Text statt als HTML eingesetzt
- Webinterface-Proxy entfernt, der Knopf öffnet den Sensor in einem neuen Tab

## 2.1.2 – 2026-11-10
- Live-Thread-Status unter „Logs“
- Start ohne Debug-Modus und Reloader (ein Prozess)
- Pflichtwerte in `.env`
- Benutzer und Passwörter bleiben über Neustarts erhalten
- Timeouts für Sensorabfragen
- Korrekturen an `update-settings` und am Lauftext

## 2.1.1
- Ausgangsstand
