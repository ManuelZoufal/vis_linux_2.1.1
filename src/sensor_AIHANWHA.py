import socket
import ssl

import requests

from requests.auth import HTTPDigestAuth
from requests.exceptions import RequestException

from src.database import save_sensor_values
from src.sensor_base import Sensor, LoggingSession, REQUEST_TIMEOUT, short_reason
from src import event_log

class AI_HANWHA(Sensor):
    def __init__(self, sensor_id, ip_address, name, group_id, username, password, datapoint_id):
        """
        Initialize AI_HANWHA sensor object
        
        Args:
        sensor_id (int): Sensor ID
        ip_address (str): IP address of sensor
        name (str): Name of sensor
        group_id (int): Group ID
        username (str): Username for sensor
        password (str): Password for sensor
        datapoint_id (int): Datapoint ID
        """
        super().__init__(sensor_id, ip_address, name, "AI_HANWHA", group_id, datapoint_id)
        self.password = password
        self.username = username
        self.session = LoggingSession(f"SensorThread-{sensor_id}")
        self._control_scheme = 'https'  # scheme that last worked for reset and reboot
        self._unanswered = False

    def fetch_sensor_values(self):
        """
        Fetch sensor values from sensor and save to database

        Returns:
        bool: True if values fetched successfully, False
        otherwise
        """

        protocols = ["http"]

        for protocol in protocols:
            url = f"{protocol}://{self.ip_address}/stw-cgi/eventsources.cgi?msubmenu=peoplecount&action=check&Channel=0"
            try:
                response = self.session.get(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, timeout=REQUEST_TIMEOUT, proxies={"http": None, "https": None})
                response.raise_for_status()
                forward_value_line1, backward_value_line1, forward_value_line2, backward_value_line2 = self._parse_counts(response.text)
                self.forward_value = forward_value_line1 + forward_value_line2
                self.backward_value = backward_value_line1 + backward_value_line2
                self.occupancy = self.forward_value - self.backward_value
                save_sensor_values(self)
                self.log_debug(f"Sensor values fetched successfully via {protocol.upper()}, Response: {event_log.shorten(response.text, 200)}")
                return True

            except RequestException as e:
                self.log_failure('Abfrage', e)
                return False

        return False

    @staticmethod
    def _parse_counts(text):
        """
        Read the counters of both lines from the answer of the camera

        Returns:
        tuple: (in line 1, out line 1, in line 2, out line 2); a missing value counts as 0
        """
        data = text.split("\r")
        return tuple(next((int(line.split('=')[1]) for line in data if key in line), 0)
                     for key in ('Channel.0.LineIndex.1.InCount', 'Channel.0.LineIndex.1.OutCount',
                                 'Channel.0.LineIndex.2.InCount', 'Channel.0.LineIndex.2.OutCount'))

    def _read_counts(self):
        """
        Read the counters without storing them, to check a reset

        Returns:
        tuple: See _parse_counts; None if the camera did not answer
        """
        url = f"http://{self.ip_address}/stw-cgi/eventsources.cgi?msubmenu=peoplecount&action=check&Channel=0"
        try:
            response = self.session.get(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, timeout=REQUEST_TIMEOUT, proxies={"http": None, "https": None})
            response.raise_for_status()
            return self._parse_counts(response.text)
        except (RequestException, ValueError, IndexError):
            return None

    def _https_problem(self):
        """
        Check whether the camera completes a TLS handshake on its HTTPS port,
        before a control command is sent

        A camera that accepts the connection on port 443 but never finishes the
        handshake makes requests report a timeout of the answer. That cannot be
        told apart from a command that was sent and not answered, so the
        handshake is tested separately: nothing has been sent at that point.

        Returns:
        str: Short reason why HTTPS cannot be used, None if the handshake works
        """
        host, _, port = str(self.ip_address).partition(':')
        try:
            context = ssl._create_unverified_context()  # same as verify=False for the requests
            with socket.create_connection((host, int(port or 443)), timeout=REQUEST_TIMEOUT[0]) as sock:
                with context.wrap_socket(sock, server_hostname=host):
                    return None
        except socket.timeout:
            return "keine TLS-Verbindung (Zeitüberschreitung)"
        except (OSError, ValueError) as e:
            return event_log.shorten(f"keine TLS-Verbindung ({type(e).__name__}: {e})", 160)

    def _control(self, what, query):
        """
        Send a control command (reset, reboot) to the camera

        HTTPS is used if the camera completes a TLS handshake, otherwise the
        command is sent over HTTP, which is also what the counter values are
        read with. The scheme that worked is tried first the next time.
        Once a command has been sent, it is never repeated over the other
        scheme: neither when the camera answered with an error nor when the
        answer timed out, because the camera may already have executed it.

        Args:
        what (str): "Zurücksetzen" or "Neustart", for the messages
        query (str): Query string of system.cgi

        Returns:
        bool: True if the camera accepted the command
        """
        self.last_action_error = None
        self._unanswered = False  # True: the command failed without any answer of the camera
        schemes = [self._control_scheme] + [s for s in ('https', 'http') if s != self._control_scheme]
        failures = []
        for scheme in schemes:
            if scheme == 'https':
                problem = self._https_problem()
                if problem:
                    failures.append(f"HTTPS: {problem}")
                    self.log_info(f"{what} über HTTPS nicht möglich: {problem}")
                    event_log.detail(f"SensorThread-{self.sensor_id}", f"TLS-Prüfung https://{self.ip_address}/ | FEHLER {problem}")
                    continue
            url = f"{scheme}://{self.ip_address}/stw-cgi/system.cgi?{query}"
            response = None
            try:
                response = self.session.post(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, timeout=REQUEST_TIMEOUT, proxies={"http": None, "https": None})
                response.raise_for_status()
            except requests.exceptions.ConnectionError as e:
                # No connection on this scheme: note it and try the other one
                failures.append(f"{scheme.upper()}: {short_reason(e, response)}")
                self.log_failure(f"{what} über {scheme.upper()}", e, response, remember=False)
                continue
            except requests.RequestException as e:
                self.log_failure(what, e, response, action=True)
                self._unanswered = response is None
                return False
            if scheme != self._control_scheme:
                self._control_scheme = scheme
                event_log.event('info', f"SensorThread-{self.sensor_id}",
                                f"Steuerbefehle gehen ab jetzt über {scheme.upper()}, weil {failures[0] if failures else 'der andere Weg nicht antwortete'}",
                                f"Sensor {self.sensor_id}: {self.name}")
            self.log_info(f"{what} erfolgreich über {scheme.upper()}. Response: {response.status_code} | {event_log.shorten(response.text, 200)}")
            return True
        self.last_action_error = f"{what} fehlgeschlagen: {'; '.join(failures)}"
        self._unanswered = True
        return False

    def reset_sensor_values(self):
        """
        Reset sensor values

        If the camera does not answer the command, the counters are read. An
        answer with an error (e.g. a rejected login) is final. The
        command is repeated once, and only if the counters show that the camera
        did not execute it: none of them is lower than before and they are not
        all zero. If they cannot be read, nothing is repeated.

        Returns:
        bool: True if the counters were reset
        """
        query = 'msubmenu=databasereset&action=control&IncludeDataType=PeopleCount'
        source, label = f"SensorThread-{self.sensor_id}", f"Sensor {self.sensor_id}: {self.name}"
        before = self._read_counts()
        if self._control('Zurücksetzen', query):
            return True
        if not self._unanswered:
            return False  # the camera answered and refused
        first_error = self.last_action_error or "Zurücksetzen fehlgeschlagen"
        after = self._read_counts()
        if after is None:
            self.last_action_error = f"{first_error}. Zählwerte danach nicht lesbar, daher keine Wiederholung"
            return False
        if not any(after) or (before is not None and any(now < earlier for now, earlier in zip(after, before))):
            # The camera executed the command although it did not confirm it
            self.last_action_error = None
            message = f"Zurücksetzen nicht bestätigt ({first_error}), die Zählwerte sind aber zurückgesetzt: vorher {before}, danach {after}"
            self.log_info(message)
            event_log.event('info', source, message, label)
            return True
        self.log_info(f"Zählwerte nach dem Zurücksetzen unverändert ({after}), der Befehl wird einmal wiederholt. Erster Versuch: {first_error}")
        event_log.detail(source, f"Kontrolle nach Zurücksetzen | Zählwerte vorher {before}, danach {after} | Befehl wird einmal wiederholt")
        if self._control('Zurücksetzen', query):
            event_log.event('info', source, f"Zurücksetzen erst beim zweiten Versuch erfolgreich. Erster Versuch: {first_error}", label)
            return True
        self.last_action_error = f"{self.last_action_error or 'Zurücksetzen fehlgeschlagen'} (auch die Wiederholung; erster Versuch: {first_error})"
        return False

    def reboot_sensor(self):
        """
        Reboot sensor
        """
        return self._control('Neustart', 'msubmenu=power&action=control&Type=Restart')

    def check_credentials(self):
        """
        Check user name and password with a read-only request

        Returns:
        tuple: (bool, str) - success and a short description
        """
        if not self.username or not self.password:
            return False, "Benutzername oder Passwort nicht hinterlegt"
        url = f"http://{self.ip_address}/stw-cgi/eventsources.cgi?msubmenu=peoplecount&action=check&Channel=0"
        try:
            # A new connection without the session, so cached authentication cannot hide a wrong password
            response = requests.get(url, auth=HTTPDigestAuth(self.username, self.password), verify=False, timeout=REQUEST_TIMEOUT, proxies={"http": None, "https": None})
        except RequestException as e:
            return False, f"Sensor nicht erreichbar ({type(e).__name__})"
        if response.status_code in (401, 403):
            return False, f"Anmeldung abgelehnt (HTTP {response.status_code})"
        if not response.ok:
            return False, f"Unerwartete Antwort (HTTP {response.status_code})"
        return True, "Anmeldung erfolgreich"
