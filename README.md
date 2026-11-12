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
   | `DISPLAY_FAULT_MINUTES` | Die Belegungsanzeige zeigt einen kleinen roten Punkt, wenn ein zählender Sensor der Gruppe so lange keine Werte liefert (Standard 5) |
   | `CERT_WARN_DAYS` | Ab so vielen Tagen vor Ablauf des Zertifikats sehen Administratoren einen Hinweis (Standard 30) |
   | `CERT_AUTO_RENEW`, `CERT_RENEW_DAYS`, `CERT_VALID_DAYS` | Automatische Erneuerung des Zertifikats (Standard an, 1 Tag vor Ablauf, 365 Tage gültig), siehe „Zertifikat“ |
   | `CERT_CA_CERT`, `CERT_CA_KEY`, `CERT_CA_KEY_PASSWORD` | Eigene CA zum Ausstellen (Standard `ca.crt`, `ca.key`, kein Passwort) |
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

Das Ablaufdatum steht für Administratoren unter „Einstellungen“; ab `CERT_WARN_DAYS` Tagen vor Ablauf erscheint auf
jeder Seite ein Hinweis.

### Automatische Erneuerung

Der Thread „Zertifikat“ prüft stündlich. Ist das Zertifikat nur noch `CERT_RENEW_DAYS` Tage (Standard 1) gültig,
abgelaufen oder fehlt es beim Start, erzeugt die Anwendung mit `openssl` einen neuen Schlüssel und ein neues
Zertifikat (`CERT_VALID_DAYS`, Standard 365 Tage) und verwendet es sofort, ohne Neustart.

- Liegen `ca.crt` und `ca.key` (`CERT_CA_CERT`, `CERT_CA_KEY`) im Programmverzeichnis, stellt diese CA das
  Zertifikat aus. Geräte, die der CA vertrauen, merken vom Wechsel nichts. Die Laufzeit endet spätestens mit
  der des CA-Zertifikats. Schlägt das Ausstellen fehl, bleibt das alte Zertifikat in Betrieb und der Thread
  meldet den Fehler; es wird dann nicht ersatzweise selbstsigniert.
- Ohne diese Dateien ist das neue Zertifikat selbstsigniert. Browser und Anzeigegeräte zeigen dann eine Warnung,
  bis es dort als vertrauenswürdig hinterlegt wurde.
- Inhaber und Adressen (subjectAltName) werden vom bisherigen Zertifikat übernommen. Gibt es keines, werden
  Rechnername und IP-Adresse des Servers eingetragen.
- Die bisherigen Dateien bleiben als `Webserver_IP.crt.alt` und `Webserver_IP.pem.alt` erhalten.
- Ein von Hand getauschtes Zertifikat lädt die Anwendung bei der nächsten stündlichen Prüfung, sofort mit einem Neustart.
- Unter „Einstellungen“ stehen der Zeitpunkt der nächsten Erneuerung, die Art der Ausstellung und die Schaltfläche
  „Zertifikat jetzt erneuern“. Abschalten: `CERT_AUTO_RENEW=false`; dann bricht der Start ohne Zertifikat ab.

Der CA-Schlüssel `ca.key` liegt dafür auf dem Server; wer ihn lesen kann, kann Zertifikate ausstellen, denen
die Geräte vertrauen. Er sollte nur für den Benutzer der Anwendung lesbar sein (`chmod 600 ca.key`).

### Von Hand ausstellen

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

Administratoren finden unter „Logs“ vier Registerkarten (Ereignis- und Änderungsprotokoll mit 20 Zeilen je Seite)
und unter „Einstellungen“ das Zertifikat, das ausführliche Server-Log und die Zugangsdaten:

- **Thread-Status:** je Hintergrund-Thread den Zustand, den letzten erfolgreichen Durchlauf und den letzten Fehler,
  alle 2 Sekunden aktualisiert, mit Export.
- **Ereignisprotokoll** (`logs/events.log`, immer aktiv): der erste Fehler einer Ausfallserie, stündlich eine Erinnerung,
  solange sie andauert, die Erholung mit Dauer des Ausfalls sowie jeder ausgeführte Zeitplan mit dem Grund je
  fehlgeschlagenem Sensor. Filter nach Zeitraum und Quelle, Export. Erreicht die Datei `LOG_MAX_MB`, wird sie zu
  `events.log.1` und eine neue begonnen; es liegen also höchstens zwei Dateien vor.
- **Ausführliches Server-Log** (unter „Einstellungen“): schreibt für 15 Minuten bis 24 Stunden zusätzlich jede Sensorabfrage, jede Webanfrage
  und die Meldungen der Bibliotheken ins Server-Log, ohne Neustart, und schaltet sich danach selbst ab. Es ändert nur die
  Protokollstufe; der Werkzeug-Debugger bleibt an `APP_DEBUG` in der `.env` gebunden und lässt sich nicht über die
  Oberfläche einschalten.
- **Störungspunkt auf der Belegungsanzeige:** Liefert ein zählender Sensor einer Gruppe seit `DISPLAY_FAULT_MINUTES`
  (Standard 5) Minuten keine Werte, zeigt die Anzeige dieser Gruppe oben rechts einen kleinen roten Punkt. Er
  verschwindet mit der ersten erfolgreichen Abfrage. Sensoren ohne Zählung und der Navigator-Upload lösen ihn nicht aus.
- **Zurücksetzen mit Kontrolle (Kameras):** Antwortet eine Kamera auf den Befehl nicht, liest die Anwendung die
  Zählwerte. Sind sie zurückgesetzt, gilt der Befehl als ausgeführt. Sind sie unverändert, wird er einmal wiederholt.
  Sind sie nicht lesbar oder hat die Kamera mit einem Fehler geantwortet, wird nichts wiederholt.
- **Detail-Protokoll** (`logs/detail_<Datum>_<Uhrzeit>.log`): für 15 Minuten bis 24 Stunden jede Anfrage an Sensoren
  und Navigator mit Dauer, Status und gekürzter Antwort. Es endet nach Ablauf der Zeit, beim Erreichen von `LOG_MAX_MB`
  oder bei einem Neustart. Passwörter, Token und Antworten auf Anmeldungen werden nicht geschrieben.

## Tests

Die Tests liegen in `tests/` und brauchen keine Sensoren, kein Navigator und keinen laufenden Server. Sie arbeiten
in einem temporären Verzeichnis mit eigener Konfiguration; Anfragen an andere Adressen als `127.0.0.1` schlagen fehl.

```bash
venv/bin/pip install -r requirements-dev.txt
```

```bash
venv/bin/python -m pytest
```

Auf GitHub laufen sie bei jedem Push und jedem Pull Request (`.github/workflows/tests.yml`).

## Versionen

Die Version steht in `app.py` (`APP_VERSION`) und wird in der Navigationsleiste angezeigt. Der Änderungsverlauf steht in
[CHANGELOG.md](CHANGELOG.md); angemeldete Benutzer sehen ihn in der Oberfläche mit einem Klick auf die Versionsnummer.
Ein Eintrag `APP_VERSION` in `.env` hat keine Wirkung.

## Enthaltene Bibliotheken

| Bibliothek | Version | Lizenz | Datei |
|---|---|---|---|
| Chart.js | 4.6.1 | MIT (`static/vendor/chart.js-LICENSE.md`) | `static/vendor/chart.umd.min.js` |
| chartjs-plugin-datalabels | 2.2.0 | MIT (`static/vendor/chartjs-plugin-datalabels-LICENSE.md`) | `static/vendor/chartjs-plugin-datalabels.min.js` |

Die Dateien sind unverändert aus den npm-Paketen übernommen.
