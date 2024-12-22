# PandaPrint
# Copyright (C) 2024 James E. Blair <corvus@gnu.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import cherrypy
import collections
import fixtures
import ftplib
import io
import json
import logging
import paho.mqtt.client as mqtt
import pandaprint.server
import requests
import socket
import ssl
import testtools
import threading
import uuid
import zipfile


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
            try:
                ftp.retrbinary(f'RETR {path}', f.write)
            except ftplib.error_perm:
                # No file
                return None
            return f.getvalue()


def make_zip_file(plates=1):
    with io.BytesIO() as f:
        with zipfile.ZipFile(f, mode='w') as zf:
            for pno in range(1, plates+1):
                zf.writestr(f'Metadata/plate_{pno}.png', b'PNG')
                zf.writestr(f'Metadata/plate_{pno}.gcode', f'G0X{pno}\n'.encode('utf8'))
            zf.writestr('3D/3dmodel.model', b'')
            zf.writestr('[Content_Types].xml', b'')
            zf.writestr('_rels/.rels', b'')
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
        filename = 'test_upload.3mf'
        config = get_config()
        name = config['printers'][0]['name']
        server = self.useFixture(PandaServerFixture(config))
        url = f'http://localhost:{server.port}/{name}/api/files/local'

        testfile = make_zip_file()
        files = {'file': (filename, testfile)}
        resp = requests.post(url, files=files)
        self.assertEqual(201, resp.status_code)
        data = get_ftp_file(f'/model/{filename}')
        self.assertEqual(testfile, data)

    def test_upload_multiple(self):
        filename = 'test_multiple.3mf'
        config = get_config()
        name = config['printers'][0]['name']
        server = self.useFixture(PandaServerFixture(config))
        url = f'http://localhost:{server.port}/{name}/api/files/local'

        testfile = make_zip_file(2)
        files = {'file': (filename, testfile)}
        resp = requests.post(url, files=files)
        self.assertEqual(201, resp.status_code)
        data = get_ftp_file(f'/model/{filename}')
        self.assertIsNone(data)
        data = get_ftp_file(f'/model/test_multiple-1.3mf')
        with io.BytesIO(data) as f:
            with zipfile.ZipFile(f) as zf:
                names = zf.namelist()
                self.assertIn('3D/3dmodel.model', names)
                self.assertIn('Metadata/plate_1.gcode', names)
                self.assertIn('Metadata/plate_1.png', names)
                self.assertNotIn('Metadata/plate_2.gcode', names)
                self.assertNotIn('Metadata/plate_2.png', names)
                plate = zf.read('Metadata/plate_1.gcode')
                self.assertEqual(b'G0X1\n', plate)
        data = get_ftp_file(f'/model/test_multiple-2.3mf')
        with io.BytesIO(data) as f:
            with zipfile.ZipFile(f) as zf:
                names = zf.namelist()
                self.assertIn('3D/3dmodel.model', names)
                self.assertIn('Metadata/plate_1.gcode', names)
                self.assertIn('Metadata/plate_1.png', names)
                self.assertNotIn('Metadata/plate_2.gcode', names)
                self.assertNotIn('Metadata/plate_2.png', names)
                plate = zf.read('Metadata/plate_1.gcode')
                self.assertEqual(b'G0X2\n', plate)

    def test_upload_and_print(self):
        filename = 'test_print.3mf'
        config = get_config()
        mqtt_fix = self.useFixture(MQTTFixture())
        name = config['printers'][0]['name']
        serial = config['printers'][0]['serial']
        server = self.useFixture(PandaServerFixture(config))
        url = f'http://localhost:{server.port}/{name}/api/files/local'

        testfile = make_zip_file()
        files = {'file': (filename, testfile)}
        resp = requests.post(url, files=files, data={'print': 'true'})
        self.assertEqual(201, resp.status_code)
        data = get_ftp_file(f'/model/{filename}')
        self.assertEqual(testfile, data)
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
                     "url": f"file:///sdcard/model/{filename}",
                     "bed_type": "auto"
                 }
             }],
            msgs)
