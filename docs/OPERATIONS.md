# Эксплуатация cloud.nimbus E2EE

## Статус

Рабочий контур локальный; публичный production не развёрнут. Новый клиент — `/vault/`, backend — Django. Go gateway не подключён. Telegram выключен по умолчанию. Passkey/PRF и разрушительный email reset реализуются как рабочий прототип; реальная межустройственная синхронизация ещё не проверена. OPAQUE-вход дополнительно подтверждается email-кодом либо подключённым TOTP. TOTP не является ключом файлов.

## Зависимости и первый запуск

Требуются Python 3.11+, Node.js 22+ для серверного OPAQUE bridge и checkout зафиксированного [cloud-cypher](https://github.com/wywywywycloud/cloud-cypher). По умолчанию клиент находится в `cloud-cypher/web/` рядом с `manage.py`; другой путь задаётся явно.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Только при самом первом создании окружения с пустыми OPAQUE-данными:

```bash
mkdir -p ~/.config/cloud-nimbus
.venv/bin/python manage.py generate_opaque_setup --output ~/.config/cloud-nimbus/opaque.env
```

Команда создаёт новый файл с правами `0600`, не печатает setup и отказывается перезаписывать существующий файл. Не запускать её для «исправления входа» в работающем окружении: новый setup не открывает старые credential records. Файл хранится вне репозитория и резервируется как секрет.

При каждом старте загрузить уже существующий setup в окружение процесса:

```bash
set -a
. ~/.config/cloud-nimbus/opaque.env
set +a
export OPAQUE_NODE=node
export OPAQUE_MODULE_PATH="$PWD/cloud-cypher/web/vendor/opaque.js"
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py runserver 127.0.0.1:8017
```

Открыть `http://localhost:8017/vault/`. `localhost` выбран согласованно с локальными `PASSKEY_RP_ID` и `PASSKEY_ORIGIN`; замена на `127.0.0.1` или другой порт требует явной настройки origin/RP. WebCrypto и WebAuthn требуют secure context; localhost разрешён для разработки, production требует HTTPS.

Без `EMAIL_HOST` письма выводятся console email backend. Не размещать такие журналы в общедоступном месте. Для проверки поведения настоящих email-сценариев нужен SMTP либо изолированный тестовый mail backend.

## Конфигурация

| Переменная | Назначение / default |
| --- | --- |
| `OPAQUE_ENABLED` | `1`; OPAQUE auth endpoints |
| `OPAQUE_SERVER_SETUP` | Обязательный секрет протокола; без него операции возвращают unavailable |
| `OPAQUE_NODE` | Node binary, default `node`; можно задать абсолютный путь |
| `OPAQUE_MODULE_PATH` | Путь к зафиксированному vendored ESM OPAQUE; default путь относительно bridge |
| `CYPHER_CLIENT_ROOT` | Каталог статического клиента, default `cloud-cypher/web` |
| `NIMBUS_LEGACY_WRITES_ENABLED` | `0`; не включать plaintext fallback для E2EE |
| `TELEGRAM_ENABLED` | `0`; Telegram сейчас не обязательный контур |
| `PASSKEY_REQUIRED` | `1`; upload требует активного passkey-конверта текущего vault с подписанными `BE=1`, `BS=1` |
| `LOGIN_SECOND_FACTOR_REQUIRED` | `1`; OPAQUE proof дополняется email/TOTP challenge до выдачи Django session |
| `PASSKEY_RP_ID` | Локально `localhost`; production требует явного значения |
| `PASSKEY_ORIGIN` | Локально `http://localhost:8017`; точное совпадение origin |
| `DJANGO_SECRET_KEY` | Обязательный уникальный секрет вне DEBUG |
| `DJANGO_DATABASE_PATH` | Путь локальной SQLite БД; production требует PostgreSQL |
| `DJANGO_MEDIA_ROOT` | Приватный каталог blobs; default `media/` |
| `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | Development/host policy |
| `EMAIL_*` | SMTP; без `EMAIL_HOST` используется console backend |

Настройки через environment не загружаются из произвольного `.env` автоматически. Node bridge получает только необходимые переменные; ни server setup, ни пароль не должны попадать в аргументы процесса, access logs, отчёты или Git. Django exception filter скрывает OPAQUE setup и отмеченные секретные переменные также при DEBUG; это не делает development server подходящим для публичной эксплуатации. `.env.telegram`, БД, media, виртуальные окружения, private setup files и generated reports с секретами не являются исходниками.

## Проверки и воспроизводимый стенд

```bash
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py check
.venv/bin/python manage.py test
.venv/bin/python scripts/test_e2ee.py --report-dir reports
```

Стенд должен запускаться с отдельными временными БД/storage/setup и явно писать, какие сценарии и браузеры проверены. Отчёт не означает production deployment, криптографическую сертификацию или физическую синхронизацию passkey в iCloud/Google/другом провайдере. WebAuthn fixtures и виртуальный аутентификатор проверяют протокол, но не внешний сервис резервирования ключей.

Детальная проверка клиентских файлов и HTTP/HAR описана в отдельном проекте cloud-cypher. Доверенный manifest/release должен быть получен независимо от проверяемого сайта. Verifier проверяет наблюдённую поставку, не блокирует исполнение и не защищает пользователя задним числом.

## Регламентные команды

| Команда | Назначение |
| --- | --- |
| `cleanup_cipher_blobs` | Повторяет удаление ciphertext, собирает брошенные staging blobs; запуск каждые 5–15 минут |
| `cleanup_opaque_challenges` | Удаляет использованное и просроченное серверное OPAQUE state |
| `cleanup_otp_challenges` | Удаляет использованные и просроченные email/TOTP challenges и незавершённые TOTP enrollment secrets |
| `cleanup_rate_buckets` | Удаляет устаревшие rate-limit buckets |
| `purge_deleted_accounts` | Физическое удаление аккаунтов после существующего 30-дневного периода; ciphertext cleanup через outbox |
| `cleanup_uploads` | Только оставшиеся legacy resumable sessions |
| `rescan_files` | Только legacy plaintext; не проверка содержимого E2EE |

Повтор физического удаления после ошибки назначается через 5 минут; брошенный staging upload становится кандидатом очистки через 24 часа. В production scheduler и monitoring должны контролировать размер/возраст очереди, ошибки storage и незавершённые задачи. Логическое удаление может завершиться раньше физического; нельзя выдавать это за гарантированное уничтожение всех backup-копий.

## Диагностика

- `opaque_unavailable`: проверить наличие setup, путь Node, версию runtime и путь vendored ESM без вывода секретов. Не генерировать новый setup поверх работающих данных.
- `authentication_failed`: неверное доказательство, истёкший/использованный challenge, другая сессия или изменившиеся credentials. Весь обмен нужно начать заново.
- `vault_rewrap_required`: при смене пароля активный vault требует новый encrypted wrapper в той же транзакции.
- `vault_changed`: vault изменился между началом и завершением операции; старый обмен не публикуется.
- `passkey_required`: нет активного конверта для текущего vault; нельзя обходить это передачей plaintext или серверного ключа.
- Ошибка PRF/UV/backup state: активация требует подписанные `BE=1`, `BS=1`. Последующий вход с `BS=0` разрешает чтение, но upload блокируется до новой успешной assertion с `BS=1`. Эти флаги не являются независимой проверкой синхронизации у провайдера.
- Ошибка расшифрования: не подменять её автоматическим созданием нового vault или стиранием существующего ключа.

Legacy `readyz`/ClamAV проверки относятся к старому контуру, пока monitoring не разделён. Успешный scanner readiness не означает способность просканировать E2EE-содержимое.

## Backup и восстановление

Нужны согласованные snapshots metadata DB и ciphertext storage, OPAQUE setup, Django secrets и проверенный клиентский релиз. Setup хранить отдельно от публичного backup и обслуживать через secret manager. Не считать эти серверные backup набором пользовательских ключей: ни PRF-результат, ни OPAQUE export key серверу не передаются.

Restore проверяется в изолированном окружении: целостность ciphertext, metadata, counters, доступ своего/чужого пользователя, отозванные поколения и очередь удалений. Tombstones и сведения об отзыве должны переживать восстановление старой копии; иначе старый vault может ошибочно снова стать доступным для выдачи. Исторические plaintext backups сохраняют исторический риск утечки.

Сохранившийся passkey позволяет сменить забытый пароль с сохранением файлов. Потеря всех passkey и пароля не устраняется одним email/TOTP-кодом: разрушительный email reset удаляет все CipherFile и конверты шифрованного хранилища, после чего создаётся новый пустой vault. Legacy plaintext не входит в этот endpoint; новые plaintext-записи выключены. Не описывать этот сброс как восстановление прежних файлов.

## Перед production

Проверить recovery-модель на реальных аутентификаторах; провести security review приложения и независимой поставки клиента; перейти на PostgreSQL; настроить TLS, SMTP, proxy limits, private storage, monitoring, scheduler и backup/restore. Проверить реальные браузеры и аутентификаторы, для passkey/PRF-прототипа. Go gateway не объявлять активным без полноценного adapter и тестов. Запуск development server и успешные локальные тесты не являются production-развёртыванием.

## Исторический Telegram-контур

Bot API, одноразовые deep links, `request_contact`, polling/webhook и проверка своего contact ID сохранены в legacy-коде. Они не генерируют секретные ключи и не запускаются для текущего E2EE по умолчанию. Старый runbook «Telegram обязателен для upload» больше не определяет поведение нового контура.
