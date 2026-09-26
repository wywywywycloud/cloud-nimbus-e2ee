# Auth API: Telegram → passkey/PRF → TOTP

Актуальный контракт 26 сентября 2026 года. Все изменяющие запросы требуют CSRF, кроме Telegram webhook с отдельным secret header. Email не используется для регистрации, входа, подтверждения или восстановления. Username: 3–64 ASCII символа, `[a-z0-9][a-z0-9_.-]*`, canonical lowercase.

## Регистрация и ограниченная сессия

1. `POST /api/opaque/register/start/ {username, registrationRequest}` → `{challenge, username, registrationResponse}`. Пароль и export key остаются в клиенте.
2. `POST /api/opaque/register/finish/ {challenge, registrationRecord}` → `{ok:true, onboarding_required:true, next_step:"telegram", ...gates}`. Создаётся unusable Django password и ограниченная серверная сессия на 15 минут; OPAQUE exchange живёт 120 секунд, одноразовый и привязан к сессии.
3. `POST /auth/telegram/link/ {}` → `{url, expires_at}`. Deep link живёт не более 15 минут. Новая попытка отзывает старую. Первый `/start` атомарно связывает попытку с Telegram sender/chat; повторный start не переназначает её. Только private chat и собственный contact (`contact.user_id == from.id`) завершают проверку. Telegram ID уникален; перепривязка этим endpoint запрещена. Номер телефона не сохраняется.
4. `GET /auth/telegram/status/` → `{linked, telegram_user_id, linked_at, display_name, quota_bytes}`. После подтверждения клиент обновляет session.
5. `POST /api/cypher/vault/ {id,version:1,wrapped_key}` создаёт vault с ключом, обёрнутым клиентским OPAQUE export key. Затем существующие `/api/passkeys/register/{start,finish}/` и `/activate/{start,finish}/` сохраняют дополнительный PRF-конверт; активация требует подписанные BE=1 и BS=1.
6. `/api/otp/setup/start/ {}` → `{challenge,secret,otpauth_uri}`; `/setup/finish/ {challenge,code}` проверяет свежий TOTP и завершает настройку.

`GET /api/cypher/session/` выдаёт CSRF и статус. `authenticated:true` означает наличие сессии, а не завершённую настройку. Поля: `user:{username}`, `vault`, квота/использование, `onboarding_required`, `next_step` (`telegram`, `passkey`, `totp`, null), `telegram_ready`, `passkey_ready`, `totp_ready`, `upload_ready`, `password_setup_required`, `otp_method` (`totp` или null). До завершения настройки файлы недоступны, доступны текущий шаг, session/logout, новый криптографический вход и смена пароля с недавним криптографическим доказательством. Полный доступ отмечается отдельно для каждой сессии только после её собственного TOTP setup/login или passkey login/activation; завершение настройки в другой сессии не повышает password-only сессию. Session endpoint завершает такую сессию, прямые файловые endpoints возвращают 401. Marker связан с Django user/session auth hash; reset и смена пароля инвалидируют остальные сессии. После 15 минут требуется снова OPAQUE/passkey. Недавнее криптографическое доказательство для настройки credential ограничено 5 минутами.

## Вход

OPAQUE `/login/start/ {username,startLoginRequest}` и `/login/finish/ {challenge,finishLoginRequest}`: если TOTP уже подключён, всегда возвращается `{second_factor_required:true,method:"totp",challenge}`. `/api/otp/login/finish/ {challenge,code}` выдаёт сессию. Если настройка не завершена и TOTP ещё нет, OPAQUE возобновляет только onboarding. Старые email challenges отвергаются. TOTP counter одноразовый, challenge связан с сессией, credential version и auth hash; максимум пять попыток, срок пять минут.

Passkey `/login/start/ {}` использует discoverable credential; опционально `{username}`. `/login/finish/` требует WebAuthn UV, origin/RP/signature и user binding. PRF остаётся на клиенте. После потери BS=1 уже активный passkey разрешает чтение, но `upload_ready:false`. Upload повторно проверяет Telegram, TOTP, активный конверт текущего vault с BE=1/BS=1, owner и квоту внутри транзакции публикации. Флаги `PASSKEY_REQUIRED=0` и `LOGIN_SECOND_FACTOR_REQUIRED=0` не отключают эти проверки.

## Смена пароля и разрушительный сброс

Сохранившийся passkey даёт клиентский секрет для прежних файлов. `/api/opaque/change/{start,finish}/` атомарно меняет OPAQUE record и конверт активного vault, инвалидируя другие сессии.

`POST /api/passkeys/reset/start/ {username}` → нейтральный `{challenge}`. Код отправляется только привязанному Telegram. `reset/finish/ {challenge,code,confirmation:"DELETE ALL FILES"}` проверяет session binding, срок 10 минут, не более пяти попыток, auth hash и неизменный Telegram ID. Удаляются все CipherFile, vault wrappers, passkeys, OPAQUE record и TOTP; сессии отзываются, физическое удаление идёт через durable outbox. Legacy plaintext сюда не входит.

После reset session имеет `password_setup_required:true`, и разрешена только новая OPAQUE-регистрация пароля через change endpoints. Затем новый пустой vault, passkey и TOTP. Telegram-проверка не возвращает прежние файлы без клиентского секрета. Не обещать физическое удаление внешних копий или проверенную синхронизацию passkey провайдером.

## Эксплуатация

Нужен Telegram bot (`TELEGRAM_ENABLED=1`, token и username вне репозитория). Недоступный бот закрывает onboarding с 503; обхода через email нет. Polling и webhook используют тот же обработчик; webhook проверяет secret header. Локальные тесты заменяют отправку сообщений mocks; test-only capture нельзя включать в production.
