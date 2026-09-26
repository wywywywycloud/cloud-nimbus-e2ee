from pathlib import Path
from django import forms

from .models import Folder

MAX_USER_BYTES = 50 * 1024 * 1024


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        clean_one = super().clean
        if isinstance(data, (list, tuple)):
            return [clean_one(item, initial) for item in data]
        return [clean_one(data, initial)]


class UploadForm(forms.Form):
    files = MultipleFileField(label="Файлы", required=False)
    folder = forms.ModelChoiceField(queryset=Folder.objects.none(), required=False, widget=forms.HiddenInput)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["folder"].queryset = Folder.objects.filter(owner=user)

    def clean(self):
        cleaned = super().clean()
        files = self.files.getlist("files") if self.files else []
        if not files:
            raise forms.ValidationError("Выберите хотя бы один файл.")
        total = sum(file.size for file in files)
        if any(file.size > MAX_USER_BYTES for file in files):
            raise forms.ValidationError("Один файл не может быть больше 50 MiB.")
        quota = self.user.quota_bytes if self.user else MAX_USER_BYTES
        if self.user and not self.user.telegram_user_id:
            raise forms.ValidationError("Подтвердите Telegram в настройках, чтобы загружать файлы.")
        if self.user and self.user.used_bytes + total > quota:
            remaining = max(0, quota - self.user.used_bytes)
            raise forms.ValidationError(f"Недостаточно места. Свободно {remaining / 1024 / 1024:.1f} MiB.")
        cleaned["uploaded_files"] = files
        return cleaned


class RenameForm(forms.Form):
    name = forms.CharField(label="Новое имя", max_length=255)

    def clean_name(self):
        name = Path(self.cleaned_data["name"].strip()).name
        if not name or name in {".", ".."}:
            raise forms.ValidationError("Введите корректное имя.")
        return name


class FolderNameForm(forms.Form):
    name = forms.CharField(label="Название папки", max_length=255)

    def __init__(self, *args, owner, parent=None, instance=None, **kwargs):
        self.owner = owner
        self.parent = parent
        self.instance = instance
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name or name in {".", ".."} or any(character in name for character in ("/", "\\", "\x00")):
            raise forms.ValidationError("Введите корректное имя папки.")
        siblings = Folder.objects.filter(owner=self.owner, parent=self.parent, name__iexact=name)
        if self.instance is not None:
            siblings = siblings.exclude(pk=self.instance.pk)
        if siblings.exists():
            raise forms.ValidationError("Папка с таким именем уже существует здесь.")
        return name
