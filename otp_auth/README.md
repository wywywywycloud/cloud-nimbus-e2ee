# Password login confirmation

With `LOGIN_SECOND_FACTOR_REQUIRED=1` (default), a successful OPAQUE password
proof does not create an authenticated Django session. It returns
`{second_factor_required:true,challenge,method}`. The browser retains its OPAQUE
export key locally while the user completes `/api/otp/login/finish/` with the
challenge UUID and a six-digit code. Successful confirmation returns
`{username}`, logs the user in, and sets the recent OPAQUE-authentication marker.
Neither the password nor its export key enters the OTP protocol or database.

The method is `email` until TOTP is enrolled, then `totp`. Enrollment requires
a logged-in session with recent OPAQUE or passkey authentication. POST
`/api/otp/setup/start/` with `{}` returns `{challenge,secret,otpauth_uri}`. The
browser displays the secret/QR locally; it must never send this URI to a remote
QR-rendering service. POST `/api/otp/setup/finish/` with `{challenge,code}`
confirms possession of the authenticator and activates TOTP.

TOTP uses pinned `pyotp==2.10.0`, a random 160-bit base32 secret, six digits,
30-second steps, and a ±1-step clock window. The highest accepted counter is
persisted under the user/credential lock, so a used code cannot authenticate
another session. The setup code is also consumed; wait for the next code before
using it to log in. An active TOTP configuration cannot be silently replaced.

**The server stores the shared TOTP secret and can generate these login codes.**
TOTP is an authentication factor only. It is never a vault encryption key,
recovery key, or input used to wrap the vault master key. Admin-resistant file
confidentiality depends on the client-side password/OPAQUE or passkey/PRF path,
as described by the main storage protocol. A six-digit code alone does not
recover encrypted files. Passkey login with user verification is a separate
cryptographic login path and does not require another OTP code.

Login and setup challenges are session-bound, expire in five minutes, allow
five code attempts, and are consumed once. Email codes are stored as keyed
HMAC digests; setup secrets are cleared when the challenge is consumed. Rate
limits apply to account and IP. Django CSRF validation is required on all
endpoints and all responses disable caching. Credential ID/version and Django
session-authentication hash snapshots reject proof started before password
replacement or account reset. A newer TOTP enrollment invalidates old email
challenges and login never falls back to email once TOTP is enrolled.

Loss of TOTP can be handled using the passkey login path. The explicit destructive
email passkey-reset flow also clears TOTP and all pending OTP challenges, after
revoking and clearing all encrypted vaults. Email is not an implicit bypass
that preserves files during a second-factor reset.

Run `python manage.py cleanup_otp_challenges` regularly to remove expired setup
secrets and consumed login challenges. For example, include it with existing
authentication challenge cleanup in the scheduled operations job.

Tests run real OPAQUE client/server exchanges and PyOTP verification; they check
that a valid password alone does not log in, export-key isolation, replay and
counter checks, wrong/expired/session-bound codes, credential changes, no email
fallback for TOTP, and destructive reset of the configuration.

References: [PyOTP documentation](https://pyauth.github.io/pyotp/),
[PyOTP 2.10.0](https://pypi.org/project/PyOTP/2.10.0/),
[TOTP specification](https://www.rfc-editor.org/rfc/rfc6238).
