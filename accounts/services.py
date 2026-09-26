import secrets
from datetime import timedelta

from django.core.mail import send_mail
from django.utils import timezone

from .models import OneTimeCode


def send_code(user, purpose):
    recent = OneTimeCode.objects.filter(user=user, purpose=purpose, created_at__gte=timezone.now() - timedelta(seconds=60)).exists()
    if recent:
        return None
    code = f"{secrets.randbelow(1_000_000):06d}"
    OneTimeCode.issue(user, purpose, code)
    subject = "Код подтверждения cloud.nimbus" if purpose == OneTimeCode.Purpose.VERIFY_EMAIL else "Код входа в cloud.nimbus"
    send_mail(subject, f"Ваш код: {code}\n\nОн действует 10 минут. Никому его не сообщайте.", None, [user.email])
    return code


def send_username_reminder(user):
    send_mail("Ваш логин cloud.nimbus", f"Логин вашего аккаунта: {user.username}", None, [user.email])
