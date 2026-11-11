# VIS – Personenzählung und Belegungsanzeige

Flask-Anwendung, die Zählsensoren (IEE, Hanwha) abfragt, die Belegung je Gruppe anzeigt
und die Werte an Siemens Navigator überträgt.

## Voraussetzungen

- Python 3.11 (die Abhängigkeiten in `requirements.txt` sind mit 3.11 getestet)
- Netzwerkzugriff vom Server auf die Sensoren und auf den Proxy für Navigator

## Installation (SUSE Linux Enterprise Server)

```bash
sudo zypper install python311
```

```bash
python3.11 -m venv venv
```

```bash
venv/bin/pip install -r requirements.txt
```

## Konfiguration

1. `.env.example` nach `.env` kopieren und die Platzhalter ersetzen:

   ```bash
   cp .env.example .env && chmod 600 .env
   ```

   | Variable | Bedeutung |
   |---|---|
   | `APP_SECRET_KEY` | Pflicht. Schlüssel für die Sitzungs-Cookies, z. B. aus `python3.11 -c "import secrets; print(secrets.token_hex(32))"` |
   | `DEFAULT_ADMIN_PASSWORD` | Pflicht. Passwort des Administrators beim ersten Anlegen; ein später geändertes Passwort bleibt erhalten |
   | `DEFAULT_ADMIN_USER` | Benutzername des Administrators (Standard `admin`) |
   | `NAVIGATOR_USERNAME`, `NAVIGATOR_PASSWORD` | Zugangsdaten für Navigator; ohne sie findet kein Upload statt. Als Administrator auch in der Oberfläche unter „Navigator-Zugang“ änderbar; dafür muss der Benutzer, unter dem die Anwendung läuft, `.env` schreiben dürfen |
   | `SENSOR_IEE_PASSWORD` | Passwort für alle IEE-Sensoren |
   | `SENSOR_HANWHA_USERNAME`, `SENSOR_HANWHA_PASSWORD` | Zugangsdaten für alle Hanwha-Sensoren |
   | `SENSOR_<ID>_USERNAME`, `SENSOR_<ID>_PASSWORD` | Abweichende Zugangsdaten eines einzelnen Sensors, z. B. `SENSOR_7_PASSWORD`; haben Vorrang vor dem Standard des Typs |
   | `LOG_DIR`, `LOG_MAX_MB`, `LOG_DETAIL_KEEP` | Verzeichnis für Ereignis- und Detail-Protokoll (Standard `logs`), Größengrenze je Datei in MB (Standard 200), Anzahl aufbewahrter Detail-Protokolle (Standard 5) |
   | `NAVIGATOR_RETRY_MINUTES` | Abstand der Token-Anfragen, nachdem 5 in Folge fehlgeschlagen sind (Standard 15) |
   | `CERT_WARN_DAYS` | Ab so vielen Tagen vor Ablauf des Zertifikats sehen Administratoren einen Hinweis (Standard 30) |
   | `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCK_MINUTES` | Login-Sperre: nach so vielen Fehlversuchen (Standard 5) für einen Benutzernamen von einer Adresse sind weitere Versuche so viele Minuten (Standard 15) gesperrt. Ein Neustart hebt alle Sperren auf |
   | `APP_TIMEZONE` | Zeitzone für angezeigte Zeitstempel (Standard `Europe/Berlin`) |
   | `APP_PORT` | Port des Webservers (Standard 5000) |
   | `APP_DEBUG` | `False` im Betrieb. `True` aktiviert den Werkzeug-Debugger und ausführliche Logs |
   | `SESSION_LIFETIME_HOURS` | Gültigkeit einer Sitzung mit „Angemeldet bleiben“ (Standard 24) |
   | `MAX_UPLOAD_MB` | Maximale Größe eines Uploads (Standard 5) |
   | `NO_PROXY` | Adressen der IEE-Sensoren, falls auf dem Server `HTTPS_PROXY` gesetzt ist |

   Fehlt `APP_SECRET_KEY` oder `DEFAULT_ADMIN_PASSWORD`, bricht der Start mit einer Meldung ab.

2. In `config.json` die IP-Adressen der Sensoren eintragen. Die Zugangsdaten der Sensoren gehören in die `.env`
   (siehe Tabelle) oder werden als Administrator unter „Sensor-Zugang“ gepflegt. Die Felder `username` und `password`
   in `config.json` werden weiterhin gelesen, wenn in der `.env` nichts hinterlegt ist.

3. Zertifikat und Schlüssel des Webservers als `Webserver_IP.crt` und `Webserver_IP.pem`
   im Programmverzeichnis ablegen (siehe Abschnitt „Zertifikat“). Beide Dateien gehören nicht
   ins Repository und stehen in `.gitignore`.

## Start

Die Anwendung muss aus dem Programmverzeichnis gestartet werden, weil `config.json`,
`sensor_data.db` und `change_log.txt` relativ dazu gesucht werden.

```bash
venv/bin/python app.py
```

Danach ist die Oberfläche unter `https://<Server>:<APP_PORT>/` erreichbar.

Hinweise:

- Benutzer und Passwörter in `sensor_data.db` bleiben über Neustarts erhalten. Beim Start werden
  nur die Zählwerte geleert, weil sie neu von den Sensoren gelesen werden.
- `DEFAULT_ADMIN_PASSWORD` gilt nur beim ersten Anlegen des Administrators. Ist dessen Passwort
  verloren, die Anwendung stoppen, `sensor_data.db` löschen und neu starten (alle Benutzer werden
  dabei entfernt).
- Nicht parallel zu einer zweiten Instanz mit derselben `config.json` starten: Beide würden
  dieselben Sensoren abfragen, die Zeitpläne (Zurücksetzen, Neustart) doppelt ausführen und
  doppelt an Navigator senden.
- Ein Port unter 1024 (z. B. 443) erfordert Root-Rechte oder die Capability `cap_net_bind_service`.
- Ist `firewalld` aktiv, muss der Port freigegeben sein:

  ```bash
  sudo firewall-cmd --permanent --add-port=<APP_PORT>/tcp && sudo firewall-cmd --reload
  ```

## Zertifikat

Ohne `Webserver_IP.crt` und `Webserver_IP.pem` bricht der Start mit einer Meldung ab. Das Ablaufdatum
steht für Administratoren unter „Logs“; ab `CERT_WARN_DAYS` Tagen vor Ablauf erscheint auf jeder Seite ein Hinweis.
Die Anwendung lädt das Zertifikat nur beim Start, ein Tausch wird also erst nach einem Neustart wirksam.

Neues Zertifikat von der eigenen CA ausstellen (`ca.crt`, `ca.key`):

```bash
openssl genrsa -out Webserver_IP.pem 2048
```

```bash
openssl req -new -key Webserver_IP.pem -out Webserver_IP.csr -subj "/C=DE/O=<Organisation>/CN=<Name>"
```

Datei `san.ext` mit der Adresse, über die die Geräte den Server aufrufen:

```
subjectAltName = IP:<SERVER-IP>
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
```

```bash
openssl x509 -req -in Webserver_IP.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out Webserver_IP.crt -days 365 -sha256 -extfile san.ext
```

```bash
chmod 600 Webserver_IP.pem
```

Der Schlüssel darf kein Passwort haben und muss für den Benutzer lesbar sein, unter dem die Anwendung läuft.

## Betrieb als Dienst (Beispiel)

`/etc/systemd/system/vis.service`, Pfade und Benutzer anpassen:

```ini
[Unit]
Description=VIS Personenzaehlung und Belegungsanzeige
After=network-online.target
Wants=network-online.target

[Service]
User=vis
WorkingDirectory=/opt/vis
ExecStart=/opt/vis/venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now vis
```

```bash
journalctl -u vis -f
```

## Überwachung

Administratoren finden unter „Logs“:

- **Thread-Status:** je Hintergrund-Thread den Zustand, den letzten erfolgreichen Durchlauf und den letzten Fehler,
  alle 2 Sekunden aktualisiert, mit Export.
- **Ereignisprotokoll** (`logs/events.log`, immer aktiv): der erste Fehler einer Ausfallserie, stündlich eine Erinnerung,
  solange sie andauert, die Erholung mit Dauer des Ausfalls sowie jeder ausgeführte Zeitplan mit dem Grund je
  fehlgeschlagenem Sensor. Filter nach Zeitraum und Quelle, Export. Erreicht die Datei `LOG_MAX_MB`, wird sie zu
  `events.log.1` und eine neue begonnen; es liegen also höchstens zwei Dateien vor.
- **Detail-Protokoll** (`logs/detail_<Datum>_<Uhrzeit>.log`): für 15 Minuten bis 24 Stunden jede Anfrage an Sensoren
  und Navigator mit Dauer, Status und gekürzter Antwort. Es endet nach Ablauf der Zeit, beim Erreichen von `LOG_MAX_MB`
  oder bei einem Neustart. Passwörter, Token und Antworten auf Anmeldungen werden nicht geschrieben.

## Versionen

Die Version steht in `app.py` (`APP_VERSION`) und wird in der Navigationsleiste angezeigt.
Ein Eintrag `APP_VERSION` in `.env` hat keine Wirkung mehr und kann entfernt werden.

| Version | Änderungen |
|---|---|
| 2.1.19 | Weniger Protokollvolumen: erfolgreiche Abfragen, Uploads und die Zeilen des Webservers je Anfrage stehen nur noch im Debug-Modus im Server-Log; das Änderungsprotokoll ist wie die anderen Protokolle auf `LOG_MAX_MB` begrenzt, und die Seite „Logs“ lädt nur die neuesten 500 Einträge (neueste zuerst) |
| 2.1.18 | Hanwha-Kameras: Der Ausweichweg über HTTP greift jetzt auch, wenn die Kamera die Verbindung auf Port 443 annimmt, aber den TLS-Handshake nicht abschließt; die TLS-Fähigkeit wird vor dem Senden eines Steuerbefehls geprüft |
| 2.1.17 | Schalter „Zählung aktiv“ je Sensor (`"counting": false` in `config.json`) für Geräte ohne Zählfunktion, z. B. Heatmap-Kameras: keine Abfrage, kein Zurücksetzen, kein Upload zu Navigator, kein Beitrag zur Belegung; Neustart bleibt möglich; im Thread-Status „Keine Zählung“ statt Fehler; Zurücksetzen und Neustart melden den Grund, wenn sie scheitern |
| 2.1.16 | Hanwha-Kameras: Zurücksetzen und Neustart gehen über HTTP, wenn die Kamera auf HTTPS nicht antwortet; der funktionierende Weg wird gemerkt und im Ereignisprotokoll vermerkt |
| 2.1.15 | Ereignisprotokoll (Ausfälle, Erholungen, Zeitpläne mit Grund je Sensor) und zeitlich begrenztes Detail-Protokoll unter „Logs“, je Datei auf `LOG_MAX_MB` (200 MB) begrenzt; kurze Fehlertexte statt ganzer Antwortseiten; Navigator fordert nach 5 Fehlversuchen nur noch alle `NAVIGATOR_RETRY_MINUTES` (15) Minuten ein Token an |
| 2.1.14 | Aufräumen: ungenutzter Code entfernt (Tabellen `roles` und `schedules`, der Thread „Datenbankauszug“, ungenutzte Importe), Laufzeitdateien und `__pycache__` nicht mehr im Repository, Vorlage `env` heißt `.env.example`; die Seite „Logs“ verträgt ein fehlendes oder beschädigtes Änderungsprotokoll |
| 2.1.13 | Eingaben bei Gruppen und beim Bearbeiten von Sensoren werden geprüft (Meldung statt Fehlerseite); maximale Belegung wird als Zahl gespeichert; Sensoren, Gruppen und IP-Adressen sortieren numerisch; beim Löschen einer Gruppe werden ihre Bilder entfernt; der Datenpunkt eines noch nie erreichten Sensors geht beim Bearbeiten nicht mehr verloren; Fehlertexte enthalten bei HTTP-Fehlern die Antwort des Sensors |
| 2.1.12 | Ablaufdatum des Zertifikats unter „Logs“, im Export und als Hinweis für Administratoren ab 30 Tagen vor Ablauf (`CERT_WARN_DAYS`); Zertifikat und Schlüssel sind nicht mehr Teil des Repositorys |
| 2.1.11 | Sensor-Zugangsdaten in `.env` statt in `config.json`: Standard je Sensortyp (`SENSOR_IEE_PASSWORD`, `SENSOR_HANWHA_USERNAME`, `SENSOR_HANWHA_PASSWORD`) und Einzelwerte je Sensor (`SENSOR_<ID>_USERNAME`, `SENSOR_<ID>_PASSWORD`); Seite „Sensor-Zugang“ zum Ändern, Prüfen und zum Übernehmen der alten Werte aus `config.json` |
| 2.1.10 | Abschnitt „Debug-Informationen“ unter „Logs“ entfernt (zeigte nur „is active“ je Thread, die Angabe „inactive“ konnte nie erscheinen); stattdessen lässt sich der Thread-Status als Textdatei exportieren |
| 2.1.9 | Navigator: ein Token wird für alle Uploads wiederverwendet statt für jeden Sensor neu angefordert; Sensoren ohne Datenpunkt werden übersprungen; Platzhalterbild für den Wartungsmodus (`static/images/maintenance.png`) |
| 2.1.8 | Chart.js wird lokal aus `static/vendor/` ausgeliefert statt vom CDN: die Belegungsanzeige funktioniert ohne Internetzugang des Anzeigegeräts |
| 2.1.7 | Login-Sperre nach wiederholten Fehlversuchen (`LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCK_MINUTES`); Rollenänderungen und gelöschte Benutzer wirken sofort statt erst nach Ablauf der Sitzung; das eigene Konto und der letzte Administrator lassen sich nicht löschen oder herabstufen |
| 2.1.6 | Zeitstempel folgen der Sommerzeit (`APP_TIMEZONE`, Standard `Europe/Berlin`); Änderungen an `config.json` laufen unter einer Sperre und werden atomar geschrieben; Navigator-Zugangsdaten lassen sich als Administrator unter „Navigator-Zugang“ ändern und testen |
| 2.1.5 | Virtuelle Sensoren stören den Start nicht mehr und lassen sich bearbeiten (Name, Gruppe, Belegung); Gruppe löschen legt die Standardgruppe nur einmal an und verschiebt die Sensoren korrekt; Passwort ändern funktioniert für alle Rollen; ein doppelter Benutzername ergibt eine Meldung statt einer Fehlerseite; Meldungen werden auf allen Seiten der Benutzerverwaltung angezeigt |
| 2.1.4 | Zeitpläne: Bearbeiten ändert den bestehenden Zeitplan statt einen neuen anzulegen; gelöschte und geänderte Zeitpläne wirken sofort statt erst nach einem Neustart; wöchentliche Zeitpläne funktionieren; Eingaben werden geprüft; ein fehlgeschlagener Sensor bricht die Aktion für die übrigen nicht mehr ab; Änderungen stehen im Änderungsprotokoll |
| 2.1.3 | Anmeldepflicht für die schreibende API und die Visualisierungs-Konfiguration; Namen und Texte werden in der Oberfläche als Text statt als HTML eingesetzt; Webinterface-Proxy entfernt, der Knopf öffnet den Sensor in einem neuen Tab |
| 2.1.2 | Live-Thread-Status unter „Logs“; Start ohne Debug-Modus und Reloader (ein Prozess); Pflichtwerte in `.env`; Benutzer und Passwörter bleiben über Neustarts erhalten; Timeouts für Sensorabfragen; Korrekturen an `update-settings` und am Lauftext |
| 2.1.1 | Ausgangsstand |

## Enthaltene Bibliotheken

| Bibliothek | Version | Lizenz | Datei |
|---|---|---|---|
| Chart.js | 4.6.1 | MIT (`static/vendor/chart.js-LICENSE.md`) | `static/vendor/chart.umd.min.js` |
| chartjs-plugin-datalabels | 2.2.0 | MIT (`static/vendor/chartjs-plugin-datalabels-LICENSE.md`) | `static/vendor/chartjs-plugin-datalabels.min.js` |

Die Dateien sind unverändert aus den npm-Paketen übernommen.
