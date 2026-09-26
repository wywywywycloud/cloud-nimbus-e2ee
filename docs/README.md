# Документация cloud.nimbus

Документы описывают локальную E2EE/OPAQUE-интеграцию, рабочий passkey/PRF-прототип, email/TOTP как второй фактор и ограничения восстановления и явно отделённую историю legacy MVP. Production не развёрнут.

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — короткая память проекта и точка входа для новой Codex-сессии.
- [IMPORT_MANIFEST.md](IMPORT_MANIFEST.md) — происхождение перенесённого состояния и список сознательно исключённых runtime-артефактов.
- [INFRASTRUCTURE.md](INFRASTRUCTURE.md) — компоненты, данные, загрузка, хранение, безопасность, наблюдаемость и целевая production-схема.
- [OPERATIONS.md](OPERATIONS.md) — локальный запуск, OPAQUE setup, секреты, стенд, очистка, backup и ограничения развёртывания.
- [DECISIONS.md](DECISIONS.md) — журнал принятых продуктовых и технических решений, включая исправленные вопросы интерфейса.
- [SETTINGS_REQUIREMENTS.md](SETTINGS_REQUIREMENTS.md) — бизнес-требования и границы новой системы настроек.
- [E2EE_ARCHITECTURE_PROPOSAL.md](E2EE_ARCHITECTURE_PROPOSAL.md) — первоначальное предложение, superseded; сохранено для истории, не спецификация текущего кода.

Документация соответствует состоянию репозитория на 26 сентября 2026 года.
