[Проверки актуальной публикации 27 сентября](publication-2026-09-27/README.md).

Ниже сохранены результаты предыдущего прогона.

# Локальные проверки Telegram onboarding — 26 сентября 2026

Проверено на синтетических данных в изолированных временных БД, storage и браузерном профиле. Telegram замокан: реальные сообщения не отправлялись. Это отчёт о выполненных проверках, а не независимый security audit или проверка физической синхронизации passkey.

| Проверка | Результат | Отчёт |
| --- | --- | --- |
| Django check и согласованность миграций | Прошли | [unit-checks.json](unit-checks.json) |
| Backend: авторизация, onboarding, TOTP, WebAuthn, storage и legacy regression | 144 теста прошли | [unit-checks.json](unit-checks.json) |
| WebCrypto и клиентская авторизация | 20 тестов прошли | [unit-checks.json](unit-checks.json) |
| Verifier и инструменты vendor | 38 тестов прошли | [unit-checks.json](unit-checks.json) |
| Chrome: сквозные сценарии | 24 проверки прошли | [browser-e2e.json](browser-e2e.json) |
| Отсутствие открытого содержимого и имени файла в БД/blobs | Прошло | [storage-inspection.json](storage-inspection.json) |
| HTTP-поставка клиента и наблюдённые браузером байты | Совпали с локальным эталоном | [delivery-url.json](delivery-url.json), [delivery-browser.json](delivery-browser.json) |
| Контролируемая подмена app.js | Ожидаемый mismatch обнаружен | [delivery-tampered.json](delivery-tampered.json), [delivery-tampered-browser.json](delivery-tampered-browser.json) |
| Восстановление исходного app.js | Совпадение | [delivery-restored.json](delivery-restored.json) |

Браузерные сценарии проверили регистрацию по логину и OPAQUE-паролю, обязательную последовательность Telegram → passkey/PRF → TOTP, возвращение из Telegram и продолжение после reload, запрет файлов для незавершённой сессии, межсессионную гонку завершения onboarding, encrypted upload/download/preview, смену пароля, вход и восстановление прежних файлов сохранённым passkey, отказ при повреждении ciphertext, подписи BS=0/BS=1 и соответствующий upload gate, разрушительный Telegram reset и отзыв старых сессий. Email verification/login/reset больше не являются текущим сценарием.

Подготовлены и просмотрены репрезентативные снимки из 30 вариантов актуального интерфейса: шаги onboarding и list/grid, light/dark, ширины 1280/390/320 px. Они находятся только в локальном ignored каталоге `reports/telegram-onboarding/screenshots/`. Старый каталог [screenshots](screenshots/) — архив предыдущего интерфейса, не доказательство текущего UI.

[Deployment-конфигурация](../docs/DEPLOYMENT.md) прошла локальные guards, syntax checks и четыре теста отказов release. PostgreSQL runtime, Linux units/права, Nginx, реальный GitHub workflow, TLS/сервер и восстановление off-host backup ещё не проверены. `vendor-integrity.json` — архив прежней сверки npm-архива; текущий запуск не повторял его загрузку.

## Воспроизведение

Из backend checkout с закреплённым клиентом:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r deploy/requirements.txt
# Node.js 22+ и pnpm 11.19.0 в PATH.
(cd cloud-cypher && pnpm install --frozen-lockfile --ignore-scripts && pnpm exec playwright install chromium)
.venv/bin/python scripts/run_checks.py --report-dir ci-reports
PLAYWRIGHT_MODULE="$PWD/cloud-cypher/node_modules/playwright" .venv/bin/python scripts/test_e2ee.py --report-dir ci-reports
```

`OPAQUE_NODE` задаёт путь к Node; `PLAYWRIGHT_CHANNEL=chrome` позволяет использовать установленный Chrome. Browser stand создаёт disposable setup/SQLite/storage и использует test-only Telegram helper; никакие пользовательские данные, production secrets, HAR, cookies или runtime logs не входят в публикуемый набор отчётов.
