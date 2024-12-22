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

import argparse
import json
import logging
import random
import shutil
import ssl
import string
import tempfile
import zipfile

import cherrypy
import ftplib
import yaml
import paho.mqtt.client as mqtt

# MQTT API reference:
# https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md

def noop():
    pass


# This class is based on:
# https://stackoverflow.com/questions/12164470/python-ftp-implicit-tls-connection-issue
# and
# https://gist.github.com/hoogenm/de42e2ef85b38179297a0bba8d60778b
class FTPS(ftplib.FTP_TLS):
    # Implicit SSL for FTP

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        # When modifying the socket, ensure that it is ssl wrapped
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        # Override the ntransfercmd method to wrap the socket
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        conn = self.sock.context.wrap_socket(
            conn, server_hostname=self.host, session=self.sock.session
        )
        # Superclass will try to unwrap the socket after transfer
        conn.unwrap = noop
        return conn, size

    def makepasv(self):
        # Ignore the host value returned by PASV
        host, port = super().makepasv()
        return self.host, port


class MQTT:
    def __init__(self, hostname, username, password, port=8883):
        self.hostname = hostname
        self.port = port
        self.subs = {}
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.tls_set(cert_reqs=ssl.CERT_NONE)
        self.client.tls_insecure_set(True)
        self.client.username_pw_set(username, password)
        self.client.connect(hostname, port, 60)
        self.client.loop_start()

    def send_json(self, topic, data):
        msg = json.dumps(data)
        self.client.publish(topic, msg)

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()

class Printer:
    def __init__(self, printer):
        self.name = str(printer['name'])
        self.host = str(printer['host'])
        self.serial = str(printer['serial'])
        self.key = str(printer['key'])
        self.mqtt = MQTT(self.host, 'bblp', self.key)


class PrintAPI:
    def __init__(self, config):
        self.printers = {p['name']: Printer(p) for p in config.printers}

    def stop(self):
        for p in self.printers.values():
            p.mqtt.stop()

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def version(self, pname):
        printer = self.printers[pname]
        return {
            'api': '1.1.0',
            'server': '1.1.0',
            'text': 'OctoPrint 1.1.0 (PandaPrint 1.0)',
        }

    def _parse_file(self, fp):
        filename = fp.filename
        basename = filename.rsplit('.', 1)[0]
        with tempfile.TemporaryFile() as f:
            shutil.copyfileobj(fp.file, f)
            with zipfile.ZipFile(f) as zf:
                gcode_files = [x for x in zf.namelist() if x.startswith('Metadata/') and x.endswith('.gcode')]
                if len(gcode_files) == 1:
                    # There's only one plate, send the original file
                    f.seek(0)
                    yield filename, f
                    return
                for plate_no in range(1, len(gcode_files)+1):
                    # Split the plate into multiple files
                    plate = []
                    for fn in zf.namelist():
                        if fn.startswith('Metadata/'):
                            base, ext = fn.split('.', 1)
                            if str(plate_no) in base:
                                plate.append(fn)
                        else:
                            # This file is not plate-specific
                            plate.append(fn)
                    # Make a new zipfile
                    with tempfile.TemporaryFile() as outf:
                        with zipfile.ZipFile(outf, mode='w') as outzf:
                            for fn in plate:
                                base, ext = fn.split('.', 1)
                                # Rename every plate "plate_1".  Only
                                # the base, not the extension (.md5
                                # may be present).
                                base = base.replace(str(plate_no), '1')
                                outfn = f'{base}.{ext}'
                                outzf.writestr(outfn, zf.read(fn))
                        outf.seek(0)
                        yield f'{basename}-{plate_no}.3mf', outf

    @cherrypy.expose
    def upload(self, pname, location, **kw):
        # https://docs.octoprint.org/en/master/api/files.html#upload-file-or-create-folder
        printer = self.printers[pname]
        do_print = str(kw.get('print', False)).lower() == 'true'
        fp = kw['file']


        # ftps upload
        first_filename = None
        with FTPS() as ftp:
            ftp.connect(host=printer.host, port=990, timeout=30)
            ftp.login('bblp', printer.key)
            ftp.prot_p()
            for newfilename, newfp in self._parse_file(fp):
                if first_filename is None:
                    first_filename = newfilename
                ftp.storbinary(f'STOR /model/{newfilename}', newfp)

        if do_print:
            printer.mqtt.send_json(
                f'device/{printer.serial}/request',
                {
                    "print": {
                        "sequence_id": "0",
                        "command": "project_file",
                        "param": "Metadata/plate_1.gcode",
                        "project_id": "0",
                        "profile_id": "0",
                        "task_id": "0",
                        "subtask_id": "0",
                        "subtask_name": "",

                        #"file": filename,
                        "url":  f"file:///sdcard/model/{first_filename}",
                        #"md5": "",

                        "bed_type": "auto",

                        #"timelapse": True,
                        #"bed_levelling": True,
                        #"flow_cali": True,
                        #"vibration_cali": True,
                        #"layer_inspect": True,
                        #"ams_mapping": "",
                        #"use_ams": false,
                    }
                }
            )
        cherrypy.response.status = "201 Resource Created"


class PandaConfig:
    def __init__(self):
        self.listen_address = '::'
        self.listen_port = 8080
        self.printers = []

    def load(self, data):
        self.listen_address = data.get('listen-address', self.listen_address)
        self.listen_port = data.get('listen-port', self.listen_port)
        self.printers = data.get('printers', self.printers)

    def load_from_file(self, path):
        with open(path) as f:
            self.load(yaml.safe_load(f))


class PandaServer:
    def __init__(self, config):
        self.api = PrintAPI(config)

        mapper = cherrypy.dispatch.RoutesDispatcher()
        mapper.connect('api', "/{pname}/api/version",
                       controller=self.api, action='version')
        mapper.connect('api', "/{pname}/api/files/{location}",
                       conditions=dict(method=['POST']),
                       controller=self.api, action='upload')
        cherrypy.config.update({
            'global': {
                'environment': 'production',
                'server.socket_host': config.listen_address,
                'server.socket_port': config.listen_port,
            }
        })
        conf = {
            '/': {
                'request.dispatch': mapper,
            }
        }
        app=cherrypy.tree.mount(root=None, config=conf)

    def start(self):
        cherrypy.engine.start()

    def stop(self):
        cherrypy.engine.exit()
        cherrypy.server.httpserver = None
        self.api.stop()

def main():
    parser = argparse.ArgumentParser(
        description='Relay for Bambu Lab printers')
    parser.add_argument('config_file',
                        help='Config file')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    config = PandaConfig()
    config.load_from_file(args.config_file)
    server = PandaServer(config)
    server.start()

if __name__ == '__main__':
    main()
