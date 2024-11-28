import threading
import io
import testtools
import fixtures
import pandaprint.server
import cherrypy
import socket
import requests
import collections
import paho.mqtt.client as mqtt
import ssl
import uuid
import json

def get_config():
    name = uuid.uuid4().hex
    serial = uuid.uuid4().hex
    return {
        'printers': [
            {
                'name': name,
                'host': 'localhost',
                'serial': serial,
                'key': '5678',
            }
        ],
        'listen-port': 0,
    }


class PandaServerFixture(fixtures.Fixture):
    def __init__(self, config):
        self._config = config
        super().__init__()

    def _setUp(self):
        config = pandaprint.server.PandaConfig()
        config.load(self._config)
        self.server = pandaprint.server.PandaServer(config)
        self.server.start()
        self.addCleanup(self.stop)

        while True:
            self.port = cherrypy.server.bound_addr[1]
            try:
                with socket.create_connection(('localhost', self.port)):
                    break
            except ConnectionRefusedError:
                pass

    def stop(self):
        self.server.stop()


class MQTTFixture(fixtures.Fixture):
    def _setUp(self):
        self.event = threading.Event()
        self.topic_messages = collections.defaultdict(list)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)
        self.client.username_pw_set('bblp', '5678')
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect('localhost', 8883, 60)
        self.client.loop_start()
        self.event.wait()

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.client.subscribe('#')
        self.event.set()

    def on_message(self, client, userdata, msg):
        self.topic_messages[msg.topic].append(msg.payload)

    def get_messages(self, topic):
        return self.topic_messages[topic]

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()


def get_ftp_file(path):
    with pandaprint.server.FTPS() as ftp:
        ftp.connect(host='localhost', port=990, timeout=30)
        ftp.login('bblp', '5678')
        ftp.prot_p()
        with io.BytesIO() as f:
            ftp.retrbinary(f'RETR {path}', f.write)
            return f.getvalue()

class TestServer(testtools.TestCase):
    def test_server_version(self):
        config = get_config()
        name = config['printers'][0]['name']
        server = self.useFixture(PandaServerFixture(config))
        url = f'http://localhost:{server.port}/{name}/api/version'
        resp = requests.get(url)
        out = resp.json()
        self.assertEqual(
            out,
            {
                'api': '1.1.0',
                'server': '1.1.0',
                'text': 'OctoPrint 1.1.0 (PandaPrint 1.0)'
            }
        )

    def test_upload_only(self):
        config = get_config()
        name = config['printers'][0]['name']
        server = self.useFixture(PandaServerFixture(config))
        url = f'http://localhost:{server.port}/{name}/api/files/local'

        files = {'file': ('test_upload.gcode', 'G0X0\n')}
        resp = requests.post(url, files=files)
        self.assertEqual(201, resp.status_code)
        data = get_ftp_file('/model/test_upload.gcode')
        self.assertEqual(b'G0X0\n', data)

    def test_upload_and_print(self):
        config = get_config()
        mqtt_fix = self.useFixture(MQTTFixture())
        name = config['printers'][0]['name']
        serial = config['printers'][0]['serial']
        server = self.useFixture(PandaServerFixture(config))
        url = f'http://localhost:{server.port}/{name}/api/files/local'

        files = {'file': ('test_print.gcode', 'G0X0\n')}
        resp = requests.post(url, files=files, data={'print': 'true'})
        self.assertEqual(201, resp.status_code)
        data = get_ftp_file('/model/test_upload.gcode')
        self.assertEqual(b'G0X0\n', data)
        msgs = [json.loads(x) for x in mqtt_fix.get_messages(f'device/{serial}/request')]
        self.assertEqual(
             [{
                 "print": {
                     "sequence_id": "0",
                     "command": "project_file",
                     "param": "Metadata/plate_1.gcode",
                     "project_id": "0",
                     "profile_id": "0",
                     "task_id": "0",
                     "subtask_id": "0",
                     "subtask_name": "",
                     "url": "file:///sdcard/model/test_print.gcode",
                     "bed_type": "auto"
                 }
             }],
            msgs)
