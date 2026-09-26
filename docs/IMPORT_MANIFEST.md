# Манифест переноса

Дата переноса: 26 сентября 2026 года.

## Источник

- Локальный рабочий каталог: `Documents/Codex/2026-09-26/jango/cloud-nimbus`.
- Ветка источника: `main`, tracking `origin/main`.
- Последний зафиксированный commit: `7aa952f` — `Polish sharing recipient and upload flows`.
- Предыдущие commits: `9bf87dd` — `Add folders, sharing dialog, themes and locales`; `1269315` — `Build cloud.nimbus local MVP`.
- Незакоммиченные изменения источника, включая Telegram, настройки, UI, документацию, миграции и иконки Adwaita, включены в перенесённое рабочее состояние.

## Что перенесено

- Django и Go исходники;
- миграции и тесты;
- templates, CSS, JavaScript и изображения;
- Adwaita assets с лицензией и атрибуцией;
- полная локальная документация;
- CI, packaging metadata, license и notices.

## Что не переносилось

- `.git/` — служебная область текущего Codex-проекта не разрешила вложить историю репозитория;
- `.env.telegram` — содержит действующий локальный секрет;
- `.venv/` — зависит от пути и пересоздаётся локально;
- `db.sqlite3` и `media/` — runtime-данные и пользовательский контент;
- `staticfiles/` — результат сборки, создаётся `collectstatic`;
- `*.egg-info`, bytecode и caches — воспроизводимые артефакты.

Исходный каталог не изменялся и остаётся локальной резервной копией с Git-историей и runtime-данными.
