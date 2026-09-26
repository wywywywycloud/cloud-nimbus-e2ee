import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import TelegramLinkAttempt, User


class TelegramAPIError(RuntimeError):
    pass


def api_call(method, payload=None, *, timeout=10):
    if not settings.TELEGRAM_ENABLED:
        raise TelegramAPIError("Telegram integration is disabled")
    if not settings.TELEGRAM_BOT_TOKEN:
        raise TelegramAPIError("Telegram bot is not configured")
    request = Request(
        f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise TelegramAPIError("Telegram API request failed") from exc
    if not body.get("ok"):
        raise TelegramAPIError("Telegram API rejected the request")
    return body.get("result")


def send_message(chat_id, text, *, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return api_call("sendMessage", payload)


def _send_contact_request(chat_id):
    return send_message(
        chat_id,
        "Подтвердите привязку cloud.nimbus. Нажмите кнопку ниже: Telegram отправит контакт только вашего текущего аккаунта. Номер телефона мы не сохраняем.",
        reply_markup={
            "keyboard": [[{"text": "Поделиться аккаунтом", "request_contact": True}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
            "input_field_placeholder": "Подтвердите свой Telegram",
        },
    )


def _handle_start(message, sender, chat_id, text):
    parts = text.split(maxsplit=1)
    token = parts[1].strip() if len(parts) == 2 else ""
    now = timezone.now()
    with transaction.atomic():
        attempt = TelegramLinkAttempt.objects.select_for_update().filter(
            token_digest=TelegramLinkAttempt.digest_token(token), used_at__isnull=True, expires_at__gt=now,
        ).first() if token else None
        if not attempt or attempt.telegram_sender_id is not None:
            return False
        attempt.telegram_chat_id = chat_id
        attempt.telegram_sender_id = sender["id"]
        attempt.save(update_fields=["telegram_chat_id", "telegram_sender_id"])
    _send_contact_request(chat_id)
    return True


def _handle_contact(message, sender, chat_id, contact):
    now = timezone.now()
    sender_id = sender.get("id")
    if not sender_id or contact.get("user_id") != sender_id:
        send_message(chat_id, "Можно подтвердить только собственный Telegram-аккаунт.", reply_markup={"remove_keyboard": True})
        return False

    candidate = TelegramLinkAttempt.objects.filter(telegram_chat_id=chat_id, telegram_sender_id=sender_id, used_at__isnull=True, expires_at__gt=now).order_by('-created_at').first()
    if candidate is None:
        return False
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=candidate.user_id)
            attempt = TelegramLinkAttempt.objects.select_for_update().filter(
                pk=candidate.pk,
                telegram_chat_id=chat_id,
                telegram_sender_id=sender_id,
                used_at__isnull=True,
                expires_at__gt=now,
            ).order_by("-created_at").first()
            if not attempt:
                send_message(chat_id, "Сначала откройте свежую ссылку из настроек cloud.nimbus.", reply_markup={"remove_keyboard": True})
                return False
            if not user.is_active or user.scheduled_deletion_at or user.telegram_user_id:
                return False
            if User.objects.exclude(pk=user.pk).filter(telegram_user_id=sender_id).exists():
                send_message(chat_id, "Этот Telegram уже привязан к другому аккаунту cloud.nimbus.", reply_markup={"remove_keyboard": True})
                return False
            user.telegram_user_id = sender_id
            user.telegram_username = (sender.get("username") or "")[:64]
            user.telegram_first_name = (sender.get("first_name") or contact.get("first_name") or "")[:128]
            user.telegram_linked_at = now
            user.save(update_fields=["telegram_user_id", "telegram_username", "telegram_first_name", "telegram_linked_at"])
            attempt.used_at = now
            attempt.save(update_fields=["used_at"])
    except IntegrityError:
        send_message(chat_id, "Этот Telegram уже привязан к другому аккаунту cloud.nimbus.", reply_markup={"remove_keyboard": True})
        return False

    send_message(
        chat_id,
        "Telegram подтверждён. Вернитесь в cloud.nimbus и завершите настройку passkey и TOTP.",
        reply_markup={"remove_keyboard": True},
    )
    return True


def handle_update(update):
    if not settings.TELEGRAM_ENABLED:
        return False
    message = update.get("message") or {}
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or chat.get("type") != "private" or not sender.get("id"):
        return False
    text = (message.get("text") or "").strip()
    if text == "/start" or text.startswith("/start "):
        return _handle_start(message, sender, chat_id, text)
    if message.get("contact"):
        return _handle_contact(message, sender, chat_id, message["contact"])
    send_message(chat_id, "Начните привязку по ссылке из настроек cloud.nimbus.", reply_markup={"remove_keyboard": True})
    return False
