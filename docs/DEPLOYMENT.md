# Cloud Nimbus: подготовка развёртывания

Статус 2026-09-26: конфигурация подготовлена локально. Эта задача не подключалась
к серверу, не публиковала исходники, не меняла DNS/TLS/Telegram, не запускала
production migrations, backup или restore. Выполненные проверки указаны в конце.

Цель: `13.143.141.139`, основное приложение `https://nimbus.by:9443`.
Один сервер: 1 vCPU, 848 MiB RAM, 15 GiB disk. Подготовлен компактный контур
Nginx → Gunicorn (1 worker, 2 threads) → Django/PostgreSQL и приватный локальный
ciphertext storage. Go gateway не подключён. Это одна точка отказа, не HA.
Реальную вместимость/нагрузку и запас памяти нужно измерить до открытия регистрации.

## Состав

- `config/production.py`: DEBUG=0, PostgreSQL, persistent OPAQUE setup, точный
  HTTPS origin/RP, обязательные Telegram/OPAQUE/passkey/TOTP policy, запрет новых
  plaintext writes; SMTP не требуется. HSTS намеренно не включён, поскольку он
  действует на домен целиком, а не только :9443.
- `deploy/nimbus.service`: Gunicorn только `127.0.0.1:8000`.
- `deploy/nimbus-telegram.service`: один polling worker. Официальный Telegram Bot
  API [не поддерживает webhook на 9443](https://core.telegram.org/bots/api#setwebhook).
  Polling не работает одновременно с установленным webhook. Бот не создаёт ключи
  шифрования; его доступность нужна для onboarding.
- `deploy/nginx.conf.template`: HTTP :80 для ACME и redirect на HTTPS :9443;
  основной TLS listener :9443; `/media/` закрыт. Подстановка `DOMAIN=nimbus.by`
  делается оператором в копии файла. Произвольные proxy headers заменяются Nginx.
- `deploy/nginx-443-redirect.conf.template`: необязательный HTTPS :443 redirect
  на :9443 с тем же сертификатом, чтобы открытие домена без порта работало.
- maintenance timer каждые 10 минут; backup timer раз в сутки с коротким простоем.
- `nimbus-release`: фиксированный backend SHA и client gitlink, install зависимостей
  непривилегированным build-пользователем, security checks, остановка всех writers,
  согласованный backup, migrate, readiness, атомарная смена symlink, запуск/health.
- `.github/workflows/checks.yml`: тесты и будущий deployment после их успеха.

## Пути и права для будущей установки

Все перечисленные изменения на сервере требуют отдельного согласования.

| Путь/identity | Владелец и назначение |
| --- | --- |
| `nimbus` | system user; приложение, peer-доступ к своей PostgreSQL БД |
| `nimbus-build` | отдельный system user с writable home; сборка без доступа к secrets/storage/DB |
| `nimbus-deploy` | только SSH forced command; без обычного shell-доступа через deploy key |
| `/opt/nimbus/releases` | root:root 0755; готовые releases root-owned, приложение не меняет код |
| `/opt/nimbus/current` | атомарный symlink на проверенный release |
| `/etc/nimbus` | root:nimbus 0750 |
| `/etc/nimbus/runtime.env` | root:nimbus 0640; никогда не добавлять в репозиторий |
| `/var/lib/nimbus/media`, `/var/lib/nimbus/tmp` | nimbus:nimbus 0700; приватные ciphertext/temp files |
| `/var/backups/nimbus` | root:root 0700; локальные snapshots, содержат секреты |
| `/usr/local/sbin/nimbus-*` | root:root 0755, только скрипты без suffix `.service`/`.timer` |
| `/etc/systemd/system/nimbus*` | root:root 0644, unit/timer files |

У `nimbus-deploy` ключ в root-owned `authorized_keys` с
`restrict,command="/usr/local/sbin/nimbus-ssh-deploy"`. Запретить password login,
forwarding/PTY; forced wrapper принимает только 40 lowercase hex символов.
Sudoers разрешает только `/usr/local/sbin/nimbus-release *`, с обычным env_reset,
без SETENV; root-owned release script повторно проверяет один SHA. Проверить
sudoers через `visudo -cf` и отказ shell/лишних аргументов до выдачи CI key.
Ключ CI не имеет root login. Ключи приложения и OPAQUE setup не передаются CI.

PostgreSQL: отдельная роль `nimbus` с LOGIN, без SUPERUSER/CREATEDB/CREATEROLE;
владелец БД `nimbus`, Unix socket peer authentication только local OS user nimbus.
Сеть 5432 закрыта. CI использует другую disposable роль с правом создания test DB.
Для малого сервера предлагается начать с shared_buffers=32MB, work_mem=2MB,
maintenance_work_mem=32MB, max_connections=20 и измерить память/latency.
Это предлагаемые значения, ещё не проверенная настройка удалённого PostgreSQL.
MemoryMax в units ограничивает процессы, но не гарантирует, что суммарная нагрузка
поместится в 848 MiB; проверить одновременный upload/OPAQUE/polling/cleanup.

## Runtime configuration без секретов в Git

Оператор создаёт `/etc/nimbus/runtime.env` сам. Файл читают systemd и Bash:
использовать простые `NAME=value`, без подстановок/команд/`export`.
Длинные секреты генерировать вне исходников; не показывать их в отчётах.

```text
DJANGO_SETTINGS_MODULE=config.production
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=nimbus.by
DJANGO_SECRET_KEY=<persistent random secret at least 50 chars>
POSTGRES_DB=nimbus
POSTGRES_USER=nimbus
POSTGRES_HOST=/var/run/postgresql
POSTGRES_PORT=5432
DJANGO_MEDIA_ROOT=/var/lib/nimbus/media
OPAQUE_ENABLED=1
OPAQUE_NODE=/usr/bin/node
OPAQUE_SERVER_SETUP=<persistent setup generated once for empty database>
PASSKEY_RP_ID=nimbus.by
PASSKEY_ORIGIN=https://nimbus.by:9443
PASSKEY_REQUIRED=1
LOGIN_SECOND_FACTOR_REQUIRED=1
NIMBUS_LEGACY_WRITES_ENABLED=0
TELEGRAM_ENABLED=1
TELEGRAM_BOT_TOKEN=<private bot token>
TELEGRAM_BOT_USERNAME=<bot username without @>
```

Это перечень полей, не исполняемый файл: заменить placeholders реальными значениями.
`CYPHER_CLIENT_ROOT` и `OPAQUE_MODULE_PATH` не задавать: defaults относятся к
проверяемому release, а не к старому `/opt/nimbus/current`. Setup генерировать один
раз штатной командой в закрытый файл до первой регистрации. При работающей БД не
перегенерировать. Webhook secret не требуется polling-процессу; не регистрировать
webhook на :9443. Email verification/recovery отключены backend auth boundary.

## CI и публикация исходников

Родитель интегрирует изменения из workspace в backend publication mirror; этот
workspace сам не Git-репозиторий. В этой задаче mirror и клиент не менялись.
Сохранить `.gitmodules` и gitlink клиента: он должен указывать на точный отдельно
проверенный/опубликованный client commit. Не копировать секреты, local DB, media,
.venv, staticfiles и reports в публикационный репозиторий.

Workflow требует разрешения на изменение `.github/workflows`, production environment
с trusted known_hosts и выделенным deploy key, branch protection для `main` и
обязательных `verify`/`postgres`. До первого утверждённого deployment настроить
required reviewer. Подробности в [ci/README.md](../ci/README.md).

## Будущие внешние операции для отдельного одобрения

1. Опубликовать проверенные backend/client commits и workflow; создать GitHub
   production environment, secrets и branch restrictions. Риск: последующие
   разрешённые pushes main смогут запускать код на сервере через release entry point.
2. Проверить текущую DNS-зону Hoster и сохранить все записи. Если DNS hosting требует
   делегации, согласовать смену NS `ns1/ns2.hoster.by` на `u1/u2.hoster.by`, затем A
   `nimbus.by → 13.143.141.139`; AAAA публиковать только при рабочем IPv6. Риск:
   ошибочная смена NS/потеря MX/TXT повлияет на другие сервисы и почту домена.
3. На сервере проверить конфликты listeners, создать identities/права/БД,
   установить reviewed root-owned scripts/units и persistent secrets. Риск:
   ошибки прав/секретов или замена OPAQUE setup могут закрыть доступ к данным.
4. После DNS проверить ACME :80, выпустить cert для nimbus.by, установить renewal
   с reload только после успешного `nginx -t`. Установить Nginx templates, unmask
   и включить Nginx. Разрешить inbound :80/:9443 и при согласовании :443 redirect;
   сохранить доступ SSH, не открывать :8000/:5432. Риск: сетевые/TLS изменения могут
   затронуть другие listeners; :443 вариант устанавливается только после проверки.
5. Приватно проверить состояние Telegram webhook. Если webhook существует,
   отдельно удалить его для перехода на polling, не сбрасывая pending updates без
   отдельного решения. Запустить ровно один bot worker. Риск: смена режима влияет
   на существующий bot consumer и доставку сообщений.
6. Запустить **один явно выбранный** прошедший CI backend SHA через release entry
   point: установка release, остановка writers, локальный backup, миграции, start.
   Это отдельное разрешение на production DB changes и создание secret-containing
   backup. Проверить HTTPS origin/CSRF/private media, readiness, Telegram onboarding,
   TOTP и реальный passkey/PRF; тестовый authenticator не доказывает provider sync.
7. Включить maintenance/backup timers и контроль диска/памяти/expired cert/failed
   units/возраста cleanup. Настроить отдельно защищённую off-host backup destination
   и провести isolated restore drill до обещаний надёжного восстановления.

Никакой из этих шагов не выполнялся этой задачей. Первое server provisioning не
автоматизировано root shell script: список предназначен для конкретного review.

## Backup, отзыв и отказ deployment

Backup сериализован с release через flock, останавливает web, polling и maintenance,
сохраняет `pg_dump -Fc`, ciphertext tar, runtime secrets и release path с checksums.
Проверяет запас места, хранит три завершённых snapshots. Root-only локальные копии
**не зашифрованы дополнительно** и не защищают от потери сервера; secrets не должны
попасть в общедоступное хранилище. Off-host encrypted backup пока не настроен.

Dump включает текущие tombstones, revoked vaults/key envelopes и cleanup outbox.
Но snapshot не содержит отозваний, сделанных позже. Автоматического restore и
DB rollback нет: старую БД нельзя обслуживать публично до переноса всех более новых
отзывов/удалений/credential changes из достоверного актуального источника и проверки
в изоляции. Если такого источника нет, безопасное восстановление старого snapshot
для публичной выдачи **не подтверждено**; это открытый DR blocker, а не обещание.
Хранение ciphertext после логического удаления ограничено retention копий; это не
гарантия физического стирания всех исторических/offline копий.

Ошибка после остановки writers оставляет сервис в maintenance; persistent marker
`/etc/nimbus/maintenance` блокирует systemd start также после reboot. Удалять marker
вручную только после устранения причины и проверки схемы/релиза; изучить privately
journals и состояние миграций, исправить вперёд. Не стартовать старый release
автоматически и не откатывать DB. Смена symlink назад возможна лишь после проверки
совместимости схемы/credential formats и отдельного решения оператора. Failed
release directory остаётся для диагностики: повтор того же SHA намеренно отклоняется.
Nightly backup отказывается стартовать, если web уже остановлен, чтобы не снять
maintenance после неудачного deployment. После успешного backup сервисы запускаются.

## Локальная проверка этой подготовки

Выполнено в workspace, без root/remote операций:

- `ci/check_deployment.py`: Bash syntax всех 4 entry points; readiness с временной
  SQLite/storage и реально сгенерированным одноразовым OPAQUE setup; отказ при
  повреждённом setup/отсутствующем клиенте; production `check --deploy --fail-level
  WARNING` прошёл с выбранной HSTS policy; неверные DEBUG/DB/origin/auth flags и
  отсутствующие secrets отклонены.
- `ci/test_release.py`: 4 теста, включая subtests для backup/migration/readiness/health
  failure. Системные команды заменены mocks в временном каталоге: повтор SHA и
  build failure не останавливают приложение, все writers останавливаются перед
  snapshot, ошибки оставляют persistent maintenance, stale `.next` не используется,
  временная switch directory убирается, success продвигает правильный release.
  Это проверка controller flow, не доказательство Linux permissions/systemd behavior.
- `manage.py check`: ошибок нет; `makemigrations --check --dry-run`: изменений нет.
- YAML parse, зависимости deploy от обоих test jobs, 40-символьные action pins,
  равенство review-копии workflow и Python syntax прошли. Actionlint не запускался.

Не выполнено этой задачей: PostgreSQL runtime/tests (локально нет сервера/контейнера),
`nginx -t`, systemd unit verification, Linux ownership/SSH restrictions, реальные
migration/backup/restore, deploy и GitHub CI run. Backend/client/browser final suites
ведут соседние задачи; их результаты нужно приложить при интеграции.

Внешний статус со слов родительской задачи: отдельная DNS-задача уже сохранила
A `nimbus.by → 13.143.141.139` с TTL 3600; authoritative propagation ещё проверяется.
Поэтому DNS-шаг выше остаётся списком проверок и возможных недостающих изменений,
а не указанием повторно менять NS/A. Workflow authorization истекла без подтверждения;
CI/CD конфигурация пока существует только локально и не считается активной.
