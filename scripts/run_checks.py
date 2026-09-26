#!/usr/bin/env python3
"""Run all unit/contract suites and publish a secret-free machine-readable summary."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports')
    args = parser.parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    node = os.environ.get('OPAQUE_NODE', 'node')
    steps = [
        ('django-check', [sys.executable, 'manage.py', 'check'], ROOT),
        ('migration-drift', [sys.executable, 'manage.py', 'makemigrations', '--check', '--dry-run'], ROOT),
        ('django-tests', [sys.executable, 'manage.py', 'test', '--verbosity', '1'], ROOT),
        ('browser-crypto-auth-tests', [node, '--test', *[str(p.relative_to(ROOT / 'cloud-cypher')) for p in sorted((ROOT / 'cloud-cypher/tests').glob('*.test.mjs'))]], ROOT / 'cloud-cypher'),
        ('verifier-vendor-tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py'], ROOT / 'cloud-cypher'),
    ]
    results = []
    for name, command, cwd in steps:
        result = subprocess.run(command, cwd=cwd, env=os.environ, capture_output=True, text=True)
        output = result.stdout + result.stderr
        entry = {'name': name, 'status': 'passed' if result.returncode == 0 else 'failed', 'exit_code': result.returncode}
        match = re.search(r'Ran (\d+) tests?', output) or re.search(r'(?:#|ℹ) tests (\d+)', output)
        if match: entry['tests'] = int(match.group(1))
        results.append(entry)
        print(f"{entry['status'].upper()} {name}" + (f" ({entry['tests']} tests)" if 'tests' in entry else ''), flush=True)
        if result.returncode:
            # Diagnostic output stays local/CI logs; the published JSON only contains status.
            print(output, file=sys.stderr)
    report = {'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'steps': results,
              'status': 'passed' if all(r['exit_code'] == 0 for r in results) else 'failed'}
    (args.report_dir / 'unit-checks.json').write_text(json.dumps(report, indent=2) + '\n')
    raise SystemExit(0 if report['status'] == 'passed' else 1)

if __name__ == '__main__': main()
