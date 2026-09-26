# cloud.nimbus E2EE

[Опубликованные результаты и воспроизведение проверок](reports/README.md)

A local encrypted-drive implementation with a Django backend and a separately released browser client. Files and their names are encrypted before upload. The backend stores ciphertext, encrypted metadata and wrapped keys; new plaintext uploads are disabled by default.

Source repositories: [cloud-nimbus-e2ee backend](https://github.com/wywywywycloud/cloud-nimbus-e2ee) and [cloud-cypher client](https://github.com/wywywywycloud/cloud-cypher). This is a local MVP, not a deployed production service.

## Authentication and encryption

Password authentication uses OPAQUE from the pinned `@serenity-kit/opaque` implementation. Django receives protocol messages rather than the password. An email code or enrolled TOTP factor confirms the password login before Django issues a session. The client's OPAQUE export key protects a randomly generated vault key; files use independent random AES-256-GCM keys through WebCrypto. Password changes atomically replace the OPAQUE record and rewrap the same vault key, preserving files.

A working WebAuthn passkey/PRF prototype provides the alternative cryptographic login and another wrapper for the same vault key. A retained passkey can authorize setting a forgotten password while preserving files. Losing the passkey instead requires email confirmation and `DELETE ALL FILES`, which destroys all encrypted-vault files and starts a new empty vault. It does not restore old files or migrate/delete historical legacy plaintext.

TOTP replaces the email code as an additional factor for password login; it is not a standalone decryption key. Its shared seed is known to the backend. No separate recovery-code workflow is used. Losing both the password and every available passkey copy cannot be repaired into access to old files using email/TOTP alone.

The prototype requires signed backup eligibility and backup-state flags (`BE=1`, `BS=1`) before activating a passkey or permitting upload. These authenticator claims do not independently prove provider synchronization across physical devices; that behavior has not been tested. Telegram is disabled by default. Encrypted sharing, folders and server-side plaintext previews are not supported by the new API.

## Run locally

Python 3.11+, Node.js 22+ and the pinned cloud-cypher client checkout are required. Follow [OPERATIONS.md](docs/OPERATIONS.md) to create the OPAQUE setup once in a private file outside Git, load it into the process environment, and configure the client path.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py runserver 127.0.0.1:8017
```

Open `http://localhost:8017/vault/`. Without SMTP configuration, verification emails go to the development console. OPAQUE operations require `OPAQUE_SERVER_SETUP`; do not regenerate this setup for an existing database. `PASSKEY_REQUIRED=1` gates upload until an active passkey wrapper exists for the current vault. `LOGIN_SECOND_FACTOR_REQUIRED=1` requires email/TOTP after the OPAQUE proof.

## Validation

```bash
.venv/bin/python manage.py test
.venv/bin/python scripts/test_e2ee.py --report-dir reports
```

The test report describes executed checks; it is not a production security certification or proof of physical passkey synchronization.

## Security boundary

A database/storage copy does not directly expose plaintext without client secrets. An active operator who can replace the browser's executable code may steal those secrets on the next visit. WebCrypto, OPAQUE, CSP and a separate repository do not by themselves prevent malicious client delivery. The independent cloud-cypher verifier checks observed files and headers against a separately trusted release; it does not prevent execution or guarantee future delivery. Compromise of the OPAQUE server setup and records can also permit guessing weak passwords.

Ciphertext cannot be scanned by the server as plaintext and is never presented as antivirus-clean. Downloads still require owner authorization. Revocation cannot erase copies or keys already downloaded elsewhere.

## Documentation and layout

- [PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md): current state, constraints and recovery limits and prototype status.
- [INFRASTRUCTURE.md](docs/INFRASTRUCTURE.md): protocols, data model, API, storage and limitations.
- [OPERATIONS.md](docs/OPERATIONS.md): setup, secrets, tests, cleanup and restore.
- [DECISIONS.md](docs/DECISIONS.md): current decisions and explicitly separated legacy history.
- `vaults/`: encrypted objects, shared quota accounting, generation fencing and deletion outbox.
- `opaque_auth/`: OPAQUE state, server bridge and password changes.
- `passkeys/`: WebAuthn/PRF prototype and destructive encrypted-vault reset.
- `otp_auth/`: email/TOTP confirmation of password login.
- `cloud-cypher/`: separately licensed client and delivery verifier.
- `accounts/`, `drive/`, `sharing/`: account lifecycle and legacy plaintext features. Their presence does not imply E2EE support.
- `services/storage-gateway/`: separately prepared Go data plane, not connected to Django.

The quota is 50 MiB and includes ciphertext tags plus any legacy-file usage. SQLite and private local storage are development defaults. Production still requires PostgreSQL, TLS, SMTP, secret management, scheduling, backup/restore, validated recovery behavior and independent security review.

## License

The existing Django backend remains GNU LGPL v3.0 or later; see [LICENSE](LICENSE). The separate cloud-cypher client is Apache-2.0. Vendored dependencies retain their own licenses and notices.
