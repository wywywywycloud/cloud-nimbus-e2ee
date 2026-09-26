#!/usr/bin/env python3
"""Fault-inject the release controller in a sandbox; no services/root/network used."""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40
MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['EVENTS'], 'a') as out:
    out.write(json.dumps([name, *args]) + '\n')
fail = os.environ.get('FAIL', '')
if name == 'install':
    pathlib.Path(args[-1]).mkdir(parents=True, exist_ok=True)
elif name == 'runuser':
    command = args[args.index('--') + 1:]
    if command[0] == 'git':
        if 'rev-parse' in command:
            print(('b' if 'HEAD:cloud-cypher' in command else 'a') * 40)
        elif 'clone' in command:
            pathlib.Path(command[-1]).mkdir(parents=True, exist_ok=True)
    elif '-m' in command and 'venv' in command:
        pathlib.Path(command[-1], 'bin').mkdir(parents=True)
    elif 'collectstatic' in command:
        # Match production's private upload modes inherited by collectstatic.
        directory = pathlib.Path('staticfiles/admin')
        directory.mkdir(mode=0o700)
        asset = directory / 'asset.css'
        asset.write_text('body {}')
        asset.chmod(0o600)
    elif ('pip' in command[0] and fail == 'build') or ('migrate' in command and fail == 'migrate') or ('deployment_check' in command and fail == 'readiness'):
        sys.exit(1)
elif name == 'mv':
    os.replace(args[-2], args[-1])
elif name == 'curl' and fail == 'health':
    sys.exit(1)
elif name == 'nimbus-backup-data' and fail == 'backup':
    sys.exit(1)
'''


class ReleaseFailures(unittest.TestCase):
    def exercise(self, fail='', existing=False):
        temporary = tempfile.TemporaryDirectory(prefix='nimbus-release-test-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for path in ('bin', 'opt/nimbus/releases', 'etc/nimbus', 'run/lock'):
            (root / path).mkdir(parents=True)
        (root / 'etc/nimbus/runtime.env').write_text('PASSKEY_RP_ID=nimbus.by\nPASSKEY_ORIGIN=https://cloud.nimbus.by:9443\n')
        # A stale old controller link must never be followed or overwritten.
        (root / 'opt/nimbus/.next').symlink_to('/nonexistent-old-release')
        release = root / 'opt/nimbus/releases' / SHA
        if existing:
            release.mkdir()
        mock = root / 'bin/mock'
        mock.write_text(MOCK)
        mock.chmod(0o755)
        for command in ('install', 'chown', 'runuser', 'flock', 'systemctl', 'curl', 'sleep', 'mv', 'nimbus-backup-data'):
            (root / 'bin' / command).symlink_to(mock)
        script = (ROOT / 'deploy/nimbus-release').read_text()
        for prefix in ('/opt/nimbus', '/etc/nimbus', '/run/lock'):
            script = script.replace(prefix, str(root) + prefix)
        script = script.replace('/usr/local/sbin/nimbus-backup-data', str(root / 'bin/nimbus-backup-data'))
        controller = root / 'release'
        controller.write_text(script)
        env = dict(os.environ, PATH=str(root / 'bin') + ':' + os.environ['PATH'],
                   EVENTS=str(root / 'events'), FAIL=fail)
        result = subprocess.run(['bash', str(controller), SHA], env=env, capture_output=True, timeout=15)
        events = [json.loads(line) for line in (root / 'events').read_text().splitlines()]
        self.assertEqual(os.readlink(root / 'opt/nimbus/.next'), '/nonexistent-old-release')
        self.assertFalse(list((root / 'opt/nimbus').glob('.switch.*')))
        return root, result, events

    def test_build_failure_does_not_stop_existing_application(self):
        root, result, events = self.exercise('build')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(e[0] == 'systemctl' for e in events))
        self.assertFalse((root / 'etc/nimbus/maintenance').exists())

    def test_existing_sha_requires_review_without_stopping_service(self):
        _, result, events = self.exercise(existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(e[0] == 'systemctl' for e in events))

    def test_failures_after_shutdown_remain_closed(self):
        for failure in ('backup', 'migrate', 'readiness', 'health'):
            with self.subTest(failure=failure):
                root, result, events = self.exercise(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue((root / 'etc/nimbus/maintenance').exists())
                service_events = [e for e in events if e[0] == 'systemctl']
                self.assertEqual(service_events[-1][1], 'stop')
                self.assertFalse(any('restore' in str(e) for e in events))

    def test_success_stops_all_writers_and_promotes_release(self):
        root, result, events = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertFalse((root / 'etc/nimbus/maintenance').exists())
        self.assertEqual((root / 'opt/nimbus/current').resolve(), (root / 'opt/nimbus/releases' / SHA).resolve())
        static_dir = root / 'opt/nimbus/current/staticfiles/admin'
        # Root-owned generated files must remain readable to the app's group,
        # with directory traversal, and without group write or public access.
        self.assertEqual(stat.S_IMODE(static_dir.stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE((static_dir / 'asset.css').stat().st_mode), 0o640)
        health = next(e for e in events if e[0] == 'curl')
        self.assertIn('Host: cloud.nimbus.by:9443', health)
        stop = next(i for i, e in enumerate(events) if e[:2] == ['systemctl', 'stop'])
        self.assertIn('nimbus-telegram.service', events[stop])
        self.assertIn('nimbus-maintenance.service', events[stop])
        backup = next(i for i, e in enumerate(events) if e[0] == 'nimbus-backup-data')
        migration = next(i for i, e in enumerate(events) if 'migrate' in e)
        self.assertLess(stop, backup)
        self.assertLess(backup, migration)
        for event in events:
            if event[0] == 'runuser':
                self.assertIn(event[2], ('nimbus', 'nimbus-build'))


if __name__ == '__main__':
    unittest.main()
