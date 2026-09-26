from django import forms
from django.utils import timezone

from .models import FileGrant, ShareLink


class ShareLinkForm(forms.Form):
    access_mode = forms.ChoiceField(choices=ShareLink.AccessMode.choices, label="Кому доступна ссылка")
    password = forms.CharField(
        required=False,
        min_length=8,
        max_length=128,
        widget=forms.PasswordInput(render_value=False),
        label="Пароль ссылки",
    )
    expires_at = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        label="Срок действия",
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)

    def clean_expires_at(self):
        value = self.cleaned_data.get("expires_at")
        if value and value <= timezone.now():
            raise forms.ValidationError("Срок действия должен быть в будущем.")
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("access_mode") == ShareLink.AccessMode.PASSWORD:
            has_existing_password = bool(self.instance and self.instance.password_hash)
            if not cleaned.get("password") and not has_existing_password:
                self.add_error("password", "Задайте пароль ссылки.")
        return cleaned


class ShareLinkUpdateForm(ShareLinkForm):
    invalidate_existing = forms.BooleanField(
        required=False,
        label="Закрыть доступ во всех уже подтверждённых сессиях",
    )


class SharePasswordForm(forms.Form):
    password = forms.CharField(
        min_length=8,
        max_length=128,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        label="Пароль ссылки",
    )


class FileGrantForm(forms.Form):
    email = forms.EmailField(label="Почта пользователя")
    # Editor is reserved in the data model for the next milestone. Until shared
    # write operations exist, accepting it here would promise permissions that
    # the product cannot enforce consistently.
    role = forms.ChoiceField(choices=((FileGrant.Role.VIEWER, FileGrant.Role.VIEWER.label),), label="Роль")
