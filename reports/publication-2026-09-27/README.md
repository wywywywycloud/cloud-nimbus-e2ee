# Проверки согласованной публикации 27 сентября 2026

Клиент закреплён на `113188a58d371d6f1e14e3bd950c68b8b34eb4b6`.
Изолированный стенд использовал временные SQLite/storage/OPAQUE setup и
синтетические аккаунты; рабочие данные и аккаунты не использовались.

- unit-checks.json: 147 Django, 34 Node, 38 verifier/vendor tests; check и миграции прошли.
- browser-e2e.json: 26 сценариев прошли, включая OPAQUE, Telegram fixture, passkey/PRF,
  TOTP, шифрование/расшифрование, password change/reset и темы/мобильные размеры.
- delivery-url.json и delivery-browser.json: наблюдённые байты и заголовки совпали.
- delivery-tampered*.json: намеренная подмена обнаружена (mismatch — ожидаемый результат).
- delivery-restored.json: после восстановления исходных байтов проверка прошла.
- storage-inspection.json: проверены перечисленные маркеры синтетических данных.

Это локальная проверка с виртуальным аутентификатором, не production deployment
и не проверка физической синхронизации passkey. Отдельный опубликованный отчёт
live-delivery.json в репозитории клиента фиксирует отставание сайта от Git.
