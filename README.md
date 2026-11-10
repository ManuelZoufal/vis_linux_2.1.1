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

1. `env` nach `.env` kopieren und die Platzhalter ersetzen:

   ```bash
   cp env .env && chmod 600 .env
   ```

   | Variable | Bedeutung |
   |---|---|
   | `APP_SECRET_KEY` | Pflicht. Schlüssel für die Sitzungs-Cookies, z. B. aus `python3.11 -c "import secrets; print(secrets.token_hex(32))"` |
   | `DEFAULT_ADMIN_PASSWORD` | Pflicht. Passwort des Administrators beim ersten Anlegen; ein später geändertes Passwort bleibt erhalten |
   | `DEFAULT_ADMIN_USER` | Benutzername des Administrators (Standard `admin`) |
   | `NAVIGATOR_USERNAME`, `NAVIGATOR_PASSWORD` | Zugangsdaten für Navigator; ohne sie findet kein Upload statt. Als Administrator auch in der Oberfläche unter „Navigator-Zugang“ änderbar; dafür muss der Benutzer, unter dem die Anwendung läuft, `.env` schreiben dürfen |
   | `APP_TIMEZONE` | Zeitzone für angezeigte Zeitstempel (Standard `Europe/Berlin`) |
   | `APP_PORT` | Port des Webservers (Standard 5000) |
   | `APP_DEBUG` | `False` im Betrieb. `True` aktiviert den Werkzeug-Debugger und ausführliche Logs |
   | `SESSION_LIFETIME_HOURS` | Gültigkeit einer Sitzung mit „Angemeldet bleiben“ (Standard 24) |
   | `MAX_UPLOAD_MB` | Maximale Größe eines Uploads (Standard 5) |
   | `NO_PROXY` | Adressen der IEE-Sensoren, falls auf dem Server `HTTPS_PROXY` gesetzt ist |

   Fehlt `APP_SECRET_KEY` oder `DEFAULT_ADMIN_PASSWORD`, bricht der Start mit einer Meldung ab.

2. In `config.json` die IP-Adressen und Zugangsdaten der Sensoren eintragen.

3. Zertifikat und Schlüssel des Webservers als `Webserver_IP.crt` und `Webserver_IP.pem`
   im Programmverzeichnis ablegen.

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

Administratoren sehen unter „Logs“ den Abschnitt „Thread-Status“: je Hintergrund-Thread den
Zustand, den letzten erfolgreichen Durchlauf und den letzten Fehler, alle 2 Sekunden aktualisiert.

## Versionen

Die Version steht in `app.py` (`APP_VERSION`) und wird in der Navigationsleiste angezeigt.
Ein Eintrag `APP_VERSION` in `.env` hat keine Wirkung mehr und kann entfernt werden.

| Version | Änderungen |
|---|---|
| 2.1.6 | Zeitstempel folgen der Sommerzeit (`APP_TIMEZONE`, Standard `Europe/Berlin`); Änderungen an `config.json` laufen unter einer Sperre und werden atomar geschrieben; Navigator-Zugangsdaten lassen sich als Administrator unter „Navigator-Zugang“ ändern und testen |
| 2.1.5 | Virtuelle Sensoren stören den Start nicht mehr und lassen sich bearbeiten (Name, Gruppe, Belegung); Gruppe löschen legt die Standardgruppe nur einmal an und verschiebt die Sensoren korrekt; Passwort ändern funktioniert für alle Rollen; ein doppelter Benutzername ergibt eine Meldung statt einer Fehlerseite; Meldungen werden auf allen Seiten der Benutzerverwaltung angezeigt |
| 2.1.4 | Zeitpläne: Bearbeiten ändert den bestehenden Zeitplan statt einen neuen anzulegen; gelöschte und geänderte Zeitpläne wirken sofort statt erst nach einem Neustart; wöchentliche Zeitpläne funktionieren; Eingaben werden geprüft; ein fehlgeschlagener Sensor bricht die Aktion für die übrigen nicht mehr ab; Änderungen stehen im Änderungsprotokoll |
| 2.1.3 | Anmeldepflicht für die schreibende API und die Visualisierungs-Konfiguration; Namen und Texte werden in der Oberfläche als Text statt als HTML eingesetzt; Webinterface-Proxy entfernt, der Knopf öffnet den Sensor in einem neuen Tab |
| 2.1.2 | Live-Thread-Status unter „Logs“; Start ohne Debug-Modus und Reloader (ein Prozess); Pflichtwerte in `.env`; Benutzer und Passwörter bleiben über Neustarts erhalten; Timeouts für Sensorabfragen; Korrekturen an `update-settings` und am Lauftext |
| 2.1.1 | Ausgangsstand |
