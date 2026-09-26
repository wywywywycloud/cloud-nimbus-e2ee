from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="Почта")

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")
        labels = {"username": "Логин"}

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Эта почта уже используется.")
        return email


class IdentifierForm(forms.Form):
    identifier = forms.CharField(label="Логин или почта", max_length=254)

    def clean_identifier(self):
        value = self.cleaned_data["identifier"].strip()
        user = User.objects.filter(Q(username__iexact=value) | Q(email__iexact=value)).first()
        if not user or not user.email_verified:
            raise ValidationError("Аккаунт не найден или почта ещё не подтверждена.")
        self.user = user
        return value


class PasswordLoginForm(IdentifierForm):
    password = forms.CharField(label="Пароль", widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        if hasattr(self, "user"):
            password = cleaned.get("password")
            if password:
                user = authenticate(username=self.user.username, password=password)
                if not user:
                    raise ValidationError("Неверный пароль.")
                self.user = user
        return cleaned


class CodeForm(forms.Form):
    code = forms.CharField(label="Код", min_length=6, max_length=6, widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "pattern": "[0-9]{6}"}))

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit():
            raise ValidationError("Введите шесть цифр.")
        return code


class UsernameReminderForm(forms.Form):
    email = forms.EmailField(label="Почта")


class AuthModeForm(forms.ModelForm):
    current_password = forms.CharField(label="Текущий пароль", widget=forms.PasswordInput, help_text="Нужен для изменения параметров безопасности.")

    class Meta:
        model = User
        fields = ("auth_mode",)
        widgets = {"auth_mode": forms.RadioSelect}

    def clean_current_password(self):
        password = self.cleaned_data["current_password"]
        if not self.instance.check_password(password):
            raise ValidationError("Неверный пароль.")
        return password


class PreferencesForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("ui_theme", "language", "default_view_mode", "display_density", "default_file_sort", "folders_first", "show_image_previews")
        labels = {
            "ui_theme": _("Тема"),
            "language": _("Язык интерфейса"),
            "default_view_mode": "Вид файлов по умолчанию",
            "display_density": "Плотность интерфейса",
            "default_file_sort": "Сортировка по умолчанию",
            "folders_first": "Показывать папки выше файлов",
            "show_image_previews": "Показывать превью изображений",
        }
        widgets = {
            "ui_theme": forms.RadioSelect,
            "language": forms.Select,
            "default_view_mode": forms.RadioSelect,
            "display_density": forms.RadioSelect,
            "default_file_sort": forms.Select,
        }


class NotificationPreferencesForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("email_share_notifications",)
        labels = {"email_share_notifications": "Присылать email, когда со мной делятся файлом или папкой"}


class DeleteAccountForm(forms.Form):
    username = forms.CharField(label="Введите логин")
    password = forms.CharField(label="Текущий пароль", widget=forms.PasswordInput)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("username") != self.user.username or not self.user.check_password(cleaned.get("password") or ""):
            raise ValidationError("Логин или пароль не совпадает.")
        return cleaned


class VerifiedPasswordResetForm(PasswordResetForm):
    def get_users(self, email):
        return (user for user in super().get_users(email) if user.email_verified and not user.scheduled_deletion_at)
