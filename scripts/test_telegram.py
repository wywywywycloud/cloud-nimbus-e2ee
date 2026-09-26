#!/usr/bin/env python3
"""Synthetic Telegram adapter for the disposable integration stand only."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['serve', 'confirm', 'reset-code'])
    parser.add_argument('value', nargs='?')
    args = parser.parse_args()
    work = Path(os.environ['NIMBUS_TEST_WORK']).resolve()
    database = Path(os.environ['DJANGO_DATABASE_PATH']).resolve()
    if os.environ.get('DJANGO_SETTINGS_MODULE') != 'config.integration_stand' or database.parent != work or not work.name.startswith('nimbus-e2ee-'):
        raise SystemExit('Only a disposable Nimbus integration stand is allowed')
    capture = work / 'telegram.jsonl'
    if args.action == 'reset-code':
        for line in reversed(capture.read_text().splitlines()):
            message = json.loads(line)
            match = re.search(r'\b[0-9]{6}\b', message['text'])
            if match:
                print(match.group())
                return
        raise SystemExit('No synthetic reset code')
    import django
    django.setup()

    def send(chat_id, text, **kwargs):
        with capture.open('a') as output:
            output.write(json.dumps({'chat_id': chat_id, 'text': text}) + '\n')
        capture.chmod(0o600)
        return {'message_id': 1}

    with patch('accounts.telegram.send_message', send):
        if args.action == 'serve':
            from django.core.management import execute_from_command_line
            execute_from_command_line(['manage.py', 'runserver', args.value, '--noreload'])
        else:
            from accounts.telegram import handle_update
            token = parse_qs(urlparse(args.value).query)['start'][0]
            user = {'id': 900000001, 'first_name': 'Synthetic', 'username': 'nimbus_synthetic'}
            message = {'from': user, 'chat': {'id': user['id'], 'type': 'private'}}
            assert handle_update({'message': {**message, 'text': '/start ' + token}})
            assert handle_update({'message': {**message, 'contact': {'user_id': user['id'], 'first_name': 'Synthetic', 'phone_number': '+10000000000'}}})


if __name__ == '__main__':
    main()
