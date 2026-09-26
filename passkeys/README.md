# Passkey backend

WebAuthn verification uses `webauthn==3.0.0` (Duo Labs), including the RP hash,
exact origin, challenge, user-presence and user-verification flags, signature,
and signature-counter rules. A zero counter on a synced credential is accepted
by the library; a positive counter must advance.

Set `PASSKEY_RP_ID` and `PASSKEY_ORIGIN` explicitly in production. An origin
includes the scheme and port, for example `https://cloud.example`. RP ID is the
hostname without a scheme or port. Development defaults are `localhost` and
`http://localhost:8017`; non-debug defaults are empty and endpoints fail closed.
Origin is never inferred from a request's Host header. RP ID and origin changes
can make existing credentials unusable, so they are deployment invariants.

All endpoints are POST JSON with Django CSRF protection and no-store responses.
Start returns `{challenge, publicKey}`; finish receives the challenge UUID and
a sanitized credential. Challenges expire in 120 seconds, are session-bound,
and are consumed once even when cryptographic verification fails. Client PRF
output is rejected; it must remain exclusively in the browser. The public PRF
input is SHA-256 of `cloud-cypher:passkey-prf:v1`, encoded as base64url in options.

Registration requires recent OPAQUE authentication (including its current
credential version), or a recent completed reset. It creates a pending
credential. Activation requires a second, verified assertion and an encrypted
wrapper of the currently active vault key. A pending credential cannot log in
or permit uploads. Only one active credential is allowed per account; copies
of that synced credential can work on multiple devices. Replacement follows
the destructive reset flow. The server cannot check that the encrypted wrapper
contains the correct vault key; the browser must verify its own wrap/unwrap.

Registration requires backup eligibility (BE). Activation additionally requires
the signed assertion's backup state (BS) to be true. Upload checks require both
flags. If a later verified login reports BS=false, reading existing files remains
available, but `passkey_ready` becomes false and uploads stop until a later signed
assertion reports backup again. **These flags are the authenticator/provider's
assertion, not independent proof that another physical device can recover the
credential or that provider-account recovery works.**
PRF support and cross-device recovery depend on browser, authenticator, and
provider. Users need a provider that supports both synced passkeys and stable
PRF output on their devices. A device-only credential is rejected. No promise
of universal browser support is made.

Passkey login returns the recovery wrapper for the same active vault; its PRF
output lets the browser unlock the key and change a forgotten password through
OPAQUE. The backend stores a public verification key and an encrypted vault
key, and cannot derive PRF output from either.

Email reset requires a session-bound, HMAC-protected six-digit code (10-minute
expiry, five guesses maximum, account and IP rate limits), plus the exact
confirmation `DELETE ALL FILES`. It revokes all of that user's encrypted vaults,
clears their wrappers, deletes all CipherFile records, schedules blob removal
using the durable deletion queue, removes passkeys and outstanding authentication
challenges, and invalidates other Django sessions. Vault UUID tombstones remain
so stale IDs cannot be reused. The OPAQUE credential is preserved, while the
email-verified session can establish a new password for an empty vault.
As elsewhere in the cypher API, legacy `StoredFile` data is outside this encrypted
storage protocol; legacy writes are disabled in the new deployment.

`PASSKEY_REQUIRED` defaults to true. Ciphertext upload checks that an active
passkey recovery wrapper with BE=true and BS=true exists for the current vault before storage I/O and
again while holding the user/vault publication locks. Existing sessions may
create an empty vault first, enroll a passkey next, and only then upload files.
The older authenticated vault-wipe endpoint also removes its passkey wrapper
and credential because they refer to the revoked vault.

Neither WebAuthn nor PRF protects plaintext from a compromised browser or a
modified application script after the client unlocks it. Byte verification and
independent client trust remain separate requirements. Email proves authority
to reset an account; it cannot recover previously encrypted data.

Validation: `python manage.py test passkeys vaults`. Fixtures create real P-256
keys, CBOR attestation data, and signed assertions, including failure cases;
they do not replace the verification library with mocks. Actual provider sync
must be validated separately on supported devices.
