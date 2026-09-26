import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta

import pyotp
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from core.audit import allow_action, audit, client_ip

from .models import OtpChallenge, TotpCredential

SESSION_BINDING = "otp_exchange_nonce"


class OTPUnavailable(Exception):
    pass


class OTPRateLimited(Exception):
    pass


def session_digest(request, *, create=False):
    nonce = request.session.get(SESSION_BINDING)
    if not isinstance(nonce, str):
        if not create:
            return None
        nonce = secrets.token_urlsafe(32)
        request.session[SESSION_BINDING] = nonce
    return hashlib.sha256(nonce.encode()).hexdigest()


def rate(request, action, user_id, *, limit=10):
    return allow_action(f"otp_{action}_ip", client_ip(request), limit=60, window_seconds=900) and allow_action(f"otp_{action}_user", str(user_id), limit=limit, window_seconds=900)


def code_digest(identifier, code):
    return hmac.new(settings.SECRET_KEY.encode(), f"login-otp:{identifier}:{code}".encode(), hashlib.sha256).hexdigest()


@sensitive_variables()
def matching_counter(secret, code, *, after=-1):
    totp = pyotp.TOTP(secret, digits=6, interval=30)
    now = timezone.now()
    counters = []
    for offset in (-1, 0, 1):
        at = now + timedelta(seconds=offset * totp.interval)
        counter = totp.timecode(at)
        if counter > after and totp.verify(code, for_time=at, valid_window=0):
            counters.append(counter)
    return max(counters) if counters else None


@sensitive_variables()
def begin_login(request, user, credential):
    """Called only after a verified OPAQUE proof, while its user lock is held."""
    if settings.SESSION_ENGINE == "django.contrib.sessions.backends.signed_cookies":
        raise OTPUnavailable()
    if not rate(request, "login_start", user.pk):
        raise OTPRateLimited()
    totp = TotpCredential.objects.filter(user=user).first()
    method = "totp" if totp else "email"
    identifier = uuid.uuid4()
    code = f"{secrets.randbelow(1000000):06d}" if method == "email" else None
    payload = {
        "credential_id": credential.pk,
        "credential_version": credential.version,
        "auth_hash": user.get_session_auth_hash(),
        "totp_id": totp.pk if totp else None,
    }
    if code is not None:
        payload["code_digest"] = code_digest(identifier, code)
    challenge = OtpChallenge.objects.create(id=identifier, user=user, kind="login", method=method, session_digest=session_digest(request, create=True), payload=payload, expires_at=timezone.now() + timedelta(minutes=5))
    if code is not None:
        try:
            send_mail("cloud.nimbus: код входа", f"Код входа: {code}\n\nКод действует 5 минут. Если вы не входили в аккаунт, никому не сообщайте этот код.", settings.DEFAULT_FROM_EMAIL, [user.email])
        except Exception as exc:
            challenge.consumed_at = timezone.now()
            challenge.payload = {}
            challenge.save(update_fields=["consumed_at", "payload"])
            audit(request, "otp.email_delivery_failed", success=False, actor=user)
            raise OTPUnavailable() from exc
    return {"second_factor_required": True, "challenge": str(challenge.pk), "method": method}
