#!/usr/bin/env python3
"""Exercise the loopback TLS ingress with disposable certificates and high ports."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Echo(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(dict(self.headers)).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory(prefix='nimbus-nginx-')
        cls.root = Path(cls.work.name)
        cls.echo = ThreadingHTTPServer(('127.0.0.1', 0), Echo)
        threading.Thread(target=cls.echo.serve_forever, daemon=True).start()
        ports = []
        for _ in range(3):
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                ports.append(sock.getsockname()[1])
        cls.http, cls.https, cls.backend = ports
        def openssl(*args):
            subprocess.run(['openssl', *args], cwd=cls.root, check=True, capture_output=True)
        openssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'root.key',
                '-out', 'root.pem', '-days', '1', '-subj', '/CN=Nimbus disposable root',
                '-addext', 'basicConstraints=critical,CA:TRUE',
                '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'intermediate.key',
                '-out', 'intermediate.csr', '-subj', '/CN=Nimbus disposable intermediate')
        (cls.root/'intermediate.ext').write_text('basicConstraints=critical,CA:TRUE,pathlen:1\nkeyUsage=critical,keyCertSign,cRLSign\n')
        openssl('x509', '-req', '-in', 'intermediate.csr', '-CA', 'root.pem', '-CAkey',
                'root.key', '-CAcreateserial', '-out', 'intermediate.pem', '-days', '1',
                '-extfile', 'intermediate.ext')
        openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'issuer.key',
                '-out', 'issuer.csr', '-subj', '/CN=Nimbus disposable issuer')
        (cls.root/'issuer.ext').write_text('basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n')
        openssl('x509', '-req', '-in', 'issuer.csr', '-CA', 'intermediate.pem', '-CAkey',
                'intermediate.key', '-CAcreateserial', '-out', 'issuer.pem', '-days', '1',
                '-extfile', 'issuer.ext')
        openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'key.pem',
                '-out', 'server.csr', '-subj', '/CN=cloud.nimbus.test')
        (cls.root/'server.ext').write_text('basicConstraints=critical,CA:FALSE\nsubjectAltName=DNS:cloud.nimbus.test,DNS:nimbus.test\n')
        openssl('x509', '-req', '-in', 'server.csr', '-CA', 'issuer.pem', '-CAkey',
                'issuer.key', '-CAcreateserial', '-out', 'leaf.pem', '-days', '1',
                '-extfile', 'server.ext')
        (cls.root/'cert.pem').write_bytes((cls.root/'leaf.pem').read_bytes() + (cls.root/'issuer.pem').read_bytes() + (cls.root/'intermediate.pem').read_bytes())
        template = (ROOT/'deploy/nginx.conf.template').read_text()
        for source, target in (
            ('LEGACY_DOMAIN', 'nimbus.test'), ('DOMAIN', 'cloud.nimbus.test'),
            ('listen 127.0.0.1:9443 ssl http2;', f'listen 127.0.0.1:{cls.backend} ssl http2;'),
            ('127.0.0.1:8000', f'127.0.0.1:{cls.echo.server_port}'),
            ('/etc/letsencrypt/live/cloud.nimbus.test/fullchain.pem', str(cls.root/'cert.pem')),
            ('/etc/letsencrypt/live/cloud.nimbus.test/privkey.pem', str(cls.root/'key.pem')),
            ('/etc/ssl/certs/ca-certificates.crt', str(cls.root/'root.pem')),
            ('/var/log/nginx/nimbus-error.log', str(cls.root/'error.log')),
        ):
            template = template.replace(source, target)
        conf = 'worker_processes 1;\npid nginx.pid;\nerror_log error.log crit;\nevents {}\nhttp {\n' + template + '\n}\n'
        (cls.root/'nginx.conf').write_text(conf)
        nginx = os.environ.get('NGINX_BINARY') or shutil.which('nginx') or '/usr/sbin/nginx'
        cls.command = [nginx, '-p', str(cls.root)+'/', '-c', str(cls.root/'nginx.conf')]
        subprocess.run(cls.command+['-t'], check=True, capture_output=True)
        cls.process = subprocess.Popen(cls.command+['-g', 'daemon off;'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(50):
            try:
                with socket.create_connection(('127.0.0.1', cls.backend), timeout=.2):
                    break
            except OSError:
                time.sleep(.1)
        else:
            raise AssertionError('Test Nginx did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.communicate(timeout=5)
        cls.echo.shutdown()
        cls.echo.server_close()
        cls.work.cleanup()

    def request(self, port, host, path='/', headers=None):
        if port == self.http:
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        else:
            context = ssl.create_default_context(cafile=str(self.root/'root.pem'))
            # Socket address is loopback; verify our disposable CA.
            context.check_hostname = False
            conn = http.client.HTTPSConnection('127.0.0.1', port, context=context, timeout=5)
        conn.request('GET', path, headers={'Host': host, **(headers or {})})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_canonical_entry_and_private_media(self):
        for host in ('cloud.nimbus.test', 'cloud.nimbus.test:443'):
            with self.subTest(host=host):
                status, headers, _ = self.request(self.backend, host)
                self.assertEqual(status, 302)
                self.assertEqual(headers['Location'], '/vault/')
                status, headers, _ = self.request(self.backend, host, '/vault/?next=a%2Fb')
                self.assertEqual(status, 200)
                self.assertNotIn('Location', headers)
                self.assertEqual(self.request(self.backend, host, '/media/private')[0], 404)

    def test_only_loopback_9443_is_configured(self):
        templates = '\n'.join(p.read_text() for p in (ROOT/'deploy').glob('nginx*.template'))
        listeners = re.findall(r'^\s*listen\s+([^;]+);', templates, re.MULTILINE)
        self.assertCountEqual(listeners, ['127.0.0.1:9443 ssl http2'])
        for port in (self.http, self.https):
            with self.subTest(port=port), self.assertRaises(OSError):
                socket.create_connection(('127.0.0.1', port), timeout=.2)

    def test_noncanonical_host_redirect_preserves_uri_without_port(self):
        for host in ('nimbus.test', 'nimbus.test:9443', 'untrusted.test'):
            with self.subTest(host=host):
                status, headers, _ = self.request(self.backend, host, '/vault/?next=a%2Fb')
                self.assertEqual(status, 308)
                self.assertEqual(headers['Location'], 'https://cloud.nimbus.test/vault/?next=a%2Fb')

    def test_direct_proxy_preserves_origin_and_replaces_untrusted_headers(self):
        status, _, body = self.request(self.backend, 'cloud.nimbus.test', '/api/cypher/session/',
                                      {'X-Forwarded-Proto':'http', 'X-Real-IP':'203.0.113.8',
                                       'X-Forwarded-For':'203.0.113.9'})
        self.assertEqual(status, 200)
        headers = json.loads(body)
        self.assertEqual(headers['Host'], 'cloud.nimbus.test')
        self.assertEqual(headers['X-Forwarded-Proto'], 'https')
        self.assertEqual(headers['X-Real-IP'], '127.0.0.1')
        self.assertEqual(headers['X-Forwarded-For'], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
