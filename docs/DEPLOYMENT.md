# Cloud Nimbus: переключение публичного адреса

Публичный адрес после переключения 27 сентября 2026 года — `https://cloud.nimbus.by/` (стандартный HTTPS :443).
Физический маршрут на одном сервере: Nginx :443 → HTTPS 127.0.0.1:9443 →
Gunicorn 127.0.0.1:8000. Открытие `/` приводит к `/vault/` без порта.
Старые nimbus.by:443/:9443 и HTTP ссылки перенаправляются на cloud.nimbus.by
с сохранением пути/query. Приложение, данные и E2EE не переносятся на другой сервер.

## Фактический статус переключения

A cloud.nimbus.by → 13.143.141.139 (TTL 3600) добавлена в Hoster без изменения
apex/NS; 1.1.1.1 и 8.8.8.8 подтверждают запись. Сертификат Let's Encrypt покрывает
cloud.nimbus.by и nimbus.by, действует до 25 декабря 2026 года, renewal включён.
На сервере применены Nginx templates, production.py и два runtime-поля; RP=nimbus.by.
В установленном release controller исправлен только Host health запроса, ранее
внесённое исправление прав staticfiles сохранено. Web, Nginx и polling работают.

Это точечный hotfix поверх release 05f361793f546e580c2e9de0696761a446f226b8,
без полного релиза, DB migrations и смены ключей. Backup исходных
настроек: `/opt/nimbus/hotfix-backups/20260926T224856Z-cloud-domain` (root-only,
содержит runtime secrets, не копировать в Git). Первое переключение было возвращено
автоматически после неуспешного health; после настройки глубины проверки upstream
TLS=2 новая точка входа прошла проверку. Проверка сертификатов не отключалась.

Проверено снаружи по IP с правильными SNI/Host и полной проверкой TLS:
root → относительный /vault/, health/vault/session=200, files без сессии=401,
media=404; корректный CSRF с новым origin достигает проверки payload (400),
старый и посторонний origin получают 403; cookie Secure и host-only.
Оба старых HTTPS адреса и cloud.nimbus.by:9443 дают 308 на новый origin без порта.
SHA256 index.html остался 707bbb763b9820feba02bd02cde0b36939d7f09c6ea4eb11070fe34f4835714b.

Локально после интеграции с актуальной main прошли 147 backend tests, release tests,
production guards; исходный браузерный E2EE до rebase прошёл полностью. Изолированный
реальный Nginx проверен на сервере под nimbus-build. Локальный DNS/браузер ещё может
кешировать прежний NXDOMAIN; публичные DNS уже возвращают новый A. Реальный passkey
провайдера после смены origin и вход в пользовательский аккаунт не выполнялись.

### Клиентский RP после переключения

Дополнительно исправлена проверка RP в passkeys.js: точный hostname или родительский
RP по границе DNS-label. Без этого прежний клиент отклонял nimbus.by на cloud.nimbus.by.
Сервер по-прежнему проверяет точный origin, браузер — ограничения WebAuthn/public suffix.
Постоянный PRF input, derivation и существующие конверты не меняются.
[Client PR](https://github.com/wywywywycloud/cloud-cypher/pull/1), pinned commit
78fb206. Live изменены только passkeys.js и его запись manifest; SHA256
7f569713ec845fa96c87bd43d87fd3dc3042c7528ce9d1dabe288afbbe150a22. Backup:
`/opt/nimbus/hotfix-backups/20260926T225802Z-parent-rp`. 34 Node tests и 38 verifier
 tests прошли, включая parent RP для регистрации/входа и отказ чужим RP.
Реальный passkey провайдера не проверялся; это исправление сохраняет прежний RP,
а не переносит credentials на новый RP.

## Настройки и безопасное переключение

1. Добавить только A `cloud.nimbus.by → 13.143.141.139` в существующей зоне,
   сохранить apex A и NS. Проверить authoritative DNS; не создавать AAAA без рабочего IPv6.
2. Сохранить старые Nginx configs и runtime.env вне Git, с правами root-only.
   Выпустить сертификат с SAN **cloud.nimbus.by и nimbus.by** под именем
   `cloud.nimbus.by` через существующий ACME webroot `/var/lib/letsencrypt`.
   До переключения проверить доступность HTTP challenge для нового host.
3. Установить проверенный `config/production.py`, который поддерживает origin без
   порта и родительский RP. Задать только `DJANGO_ALLOWED_HOSTS=cloud.nimbus.by`,
   `PASSKEY_ORIGIN=https://cloud.nimbus.by`; **сохранить PASSKEY_RP_ID=nimbus.by**,
   OPAQUE setup, Django secret, DB, ciphertext и остальные runtime параметры.
   Прежний origin :9443 остаётся допустимым в коде для обратимого перехода.
4. Заменить оба Nginx шаблона с `LEGACY_DOMAIN=nimbus.by`, затем
   `DOMAIN=cloud.nimbus.by` (важен порядок замен). Они устанавливаются вместе;
   прежний redirect cloud/:443 → :9443 должен быть удалён из активной конфигурации.
   TLS :443 проксирует на :9443 с SNI и **проверкой upstream сертификата**.
   Backend получает канонический Host без порта и HTTPS scheme; внешний клиент
   не может подменить forwarded IP. Только loopback proxy доверен для real IP.
5. Под release lock выполнить production check, `nginx -t`, перезапустить web
   с новым environment и reload Nginx. Polling остаётся polling; webhook не менять.
   Обновить установленный release controller из PR: health Host берётся из origin,
   а не из RP, который теперь отличается от hostname приложения.
6. Проверить TLS без insecure-флагов, обе старые точки входа, новый `/vault/`,
   `/healthz/`, `/api/cypher/session/`, unauthenticated files=401, media=404,
   CSRF=403 для старого/чужого origin и CSRF с новым origin. Сверить manifest
   существующего клиента. Проверить вход и passkey на реальном устройстве отдельно.

Сессия и localStorage старого origin не переносятся браузером: нужен повторный вход.
RP `nimbus.by` остаётся валидным родительским доменом для `cloud.nimbus.by`, поэтому
сохранённые credentials и PRF-конверты не переписываются. Проверка WebAuthn origin
остаётся точной, без wildcard или одновременного принятия старого origin.
Другие поддомены nimbus.by должны оставаться под доверенным управлением владельца RP.
Не менять RP на cloud.nimbus.by у действующих credentials и не сбрасывать vault.

При ошибке вернуть сохранённые Nginx configs, public origin/allowed hosts и
предыдущий production.py, проверить `nginx -t` и перезапустить web/reload.
DB restore, смена setup, удаление файлов и миграции для этого переключения не нужны.
Кешированный 308 на старый :9443 учтён ответным редиректом на новый домен.

## Проверки PR

`ci/test_nginx.py` запускает реальные шаблоны Nginx на временных высоких портах
с одноразовым сертификатом и echo backend: проверяет два proxy hop, TLS trust,
редиректы без порта, сохранение URI, private media и перезапись forwarded headers.
`ci/check_deployment.py` проверяет новый/прежний origin, parent RP и отказ неверных
origin/host/RP. `ci/test_release.py` проверяет Host health запроса.

---

## История развёртывания до переключения домена


На 27 сентября 2026 года публичный экземпляр работает на
[https://nimbus.by:9443/vault/](https://nimbus.by:9443/vault/).
Развёрнут вручную по SSH по прямому указанию пользователя, без CI deploy key.

- Backend: `05f361793f546e580c2e9de0696761a446f226b8`.
- Client: `4722feb937ad64c288fad776696a605a3170ef39`.
- [CI run 36272922363](https://github.com/wywywywycloud/cloud-nimbus-e2ee/actions/runs/36272922363):
  verify и postgres прошли; автоматический deploy не прошёл из-за отсутствия
  `NIMBUS_DEPLOY_KEY` и `NIMBUS_KNOWN_HOSTS`. CI SSH-доступ не создавался.
- Установленный `/usr/local/sbin/nimbus-release` дополнительно содержит локальное
  исправление прав статики из workspace: root:nimbus и `u=rwX,g=rX,o=`.
  Исходники приложения в release не менялись; исправление контроллера ещё не опубликовано.

## Сервер и сеть

`13.143.141.139`, Ubuntu 26.04.1, 1 vCPU, 848 MiB RAM, 15 GiB disk,
без swap. После запуска: около 356 MiB RAM доступно, 13 GiB диска свободно.
Это замер без нагрузки, а не оценка максимальной вместимости.

DNS apex A указывает на этот IP; NS — u1.hoster.by/u2.hoster.by.
Nginx принимает HTTPS :9443, :80 и HTTPS :443 перенаправляют на :9443.
Сертификат Let's Encrypt действителен до 25 декабря 2026 года; certbot.timer
включён, deploy hook проверяет `nginx -t` перед reload. Renewal dry-run ещё не выполнялся.
Gunicorn доступен только на 127.0.0.1:8000, PostgreSQL — на loopback и Unix socket.
Публичного `/media/` нет. URL/capability access logging у сайта выключен.

## Службы и данные

- `nimbus.service`: Gunicorn, 1 worker / 2 threads, пользователь nimbus.
- `nimbus-telegram.service`: один polling worker для @validation_s_bot;
  перед запуском проверено отсутствие webhook и pending updates. Токен в runtime.env.
- `nimbus-maintenance.timer`: cleanup ciphertext/challenges/rate buckets/accounts
  раз в десять минут. Пробный запуск завершился успешно.
- `nimbus-backup.timer`: ежедневно около 03:30 UTC с jitter до пяти минут;
  согласованный backup кратко останавливает все writers, включая web/polling.
- PostgreSQL 18: роль/БД nimbus, Unix peer authentication; shared_buffers=32MB,
  work_mem=2MB, maintenance_work_mem=32MB, max_connections=20.
- Go gateway не подключён; ciphertext хранится через Django private storage.

| Путь | Права / назначение |
| --- | --- |
| `/opt/nimbus/releases/<sha>` | root-owned исходники и venv |
| `/opt/nimbus/current` | symlink на активный релиз |
| `current/staticfiles` | root:nimbus, dirs 0750/files 0640; app только читает |
| `/etc/nimbus/runtime.env` | root:nimbus 0640; persistent secrets, не в Git |
| `/var/lib/nimbus/media`, `/var/lib/nimbus/tmp` | nimbus:nimbus 0700 |
| `/var/backups/nimbus` | root:root 0700; локальные snapshots |
| `/usr/local/sbin/nimbus-*` | root:root 0755; release/backup/backup-data |
| `/etc/systemd/system/nimbus*` | root-owned units, timers и optional drop-ins |

`nimbus-build` собирает зависимости без доступа к runtime secrets/storage/DB.
Пользователь приложения не может изменять код. Отдельный nimbus-deploy не создавался.

IPv6 до Telegram на этом сервере давал timeout, IPv4 отвечал за ~0,03 секунды.
Только web и polling службы используют read-only mount `/etc/nimbus/gai.conf`
поверх своего `/etc/gai.conf`, с предпочтением IPv4. Шаблоны:
`deploy/gai-ipv4.conf` и `deploy/nimbus-ipv4.conf`; последний установлен как
`/etc/systemd/system/{nimbus,nimbus-telegram}.service.d/network.conf`.
Глобальный DNS, IPv6 и TLS verification не отключались.

## Runtime configuration

Production settings — `config.production`, DEBUG=0, allowed host/RP `nimbus.by`,
точный origin `https://nimbus.by:9443`. PostgreSQL socket `/var/run/postgresql`,
DB/user nimbus, media `/var/lib/nimbus/media`, Node `/usr/bin/node`.
OPAQUE, Telegram, passkey и TOTP включены; legacy plaintext writes выключены.
Email auth/verification/recovery выключены; SMTP не требуется.

Django secret и OPAQUE setup созданы один раз для пустой базы и переданы по SSH
без вывода в логи. Bot token взят из существующей приватной конфигурации.
Не перегенерировать OPAQUE setup у работающей БД: старые password records станут
непригодны. Не копировать runtime.env/backup/БД/media в Git или отчёты.
`CYPHER_CLIENT_ROOT` и `OPAQUE_MODULE_PATH` не заданы: defaults относятся к текущему
проверяемому release. Файл env совместим с Bash и systemd; без команд/подстановок.

## Следующий ручной релиз

1. Выполнить verify/postgres CI и выбрать полный backend SHA на main с pinned client.
2. Проверить свободное место, состояние служб и отсутствие maintenance marker.
3. Запустить как оператор `/usr/local/sbin/nimbus-release <40-character-sha>`.
4. Проверить HTTPS, клиентский manifest, auth boundary, polling и состояние timers.

Controller собирает код как nimbus-build, проверяет production settings,
собирает статику с read-only доступом nimbus, останавливает writers, сохраняет backup,
применяет миграции как nimbus, проверяет DB/storage/client/OPAQUE, атомарно меняет
symlink и проверяет health. Приложение и pip не запускаются под root.

При ошибке после остановки writers сохраняется `/etc/nimbus/maintenance`, который
запрещает автоматический restart даже после reboot. Проверить причину, схему,
readiness и WSGI, прежде чем снимать marker. Не откатывать БД автоматически:
старый snapshot может воскресить отозванные credentials и vaults.
Повторное использование уже созданного release directory требует ручного разбора.

Первый запуск выявил, что collectstatic наследует upload modes 0600/0700, после
chown root:root файлы стали недоступны приложению. Controller исправлен;
схема проверена через migrate --check, deployment_check и реальный WSGI startup,
права изменены только для generated staticfiles. Миграции не откатывались.

## Backup и восстановление

`nimbus-backup` сериализован с release через flock. При остановленных writers
сохраняет pg_dump, ciphertext tar, runtime secrets и release path с SHA256SUMS.
Требует запас места плюс 2 GiB, хранит три завершённых snapshots. Копии root-only,
не зашифрованы дополнительно, находятся на том же диске. Off-host encrypted backup
не настроен; это не защита от потери сервера.

Проверены checksums и PostgreSQL archive; второй snapshot успешно восстановлен
в отдельную временную БД: 38 migrations, 0 users, 0 cipherfiles. Временная БД удалена,
рабочая не изменялась. Это initial database restore, не проверка восстановления
реальных пользовательских ciphertext/ключей или более поздних отзывов.

Старые snapshots нельзя публиковать до переноса всех более новых tombstones,
revocations и credential changes из достоверного источника. Без него безопасное
публичное восстановление старого snapshot не подтверждено. Нет автоматического
DB rollback или обещания удаления всех исторических/offline копий.

## Проверки и границы

- CI verify/postgres прошли: 145 backend tests и 2 специфичных PostgreSQL проверки,
  клиентские/verifier/browser проверки из workflow.
- На сервере прошли migrate, deployment_check, WSGI initialization, systemd unit
  validation и nginx -t; приложение/polling работают без restart loop.
- Внешние health/vault/session — HTTP 200, unauthenticated files — 401,
  `/media/` — 404, cross-origin POST без CSRF — 403. :80/:443 приводят к :9443/vault/.
- Независимый локальный manifest совпал с 10 HTTPS-файлами клиента и headers.
- Реальный браузер открыл страницу и форму регистрации: login/password, далее
  Telegram → passkey → TOTP. Аккаунт пользователя не создавался за него.
- Telegram getMe/getWebhookInfo/getUpdates проверены без вывода сообщений/токенов;
  после IPv4 preference пять getMe подряд прошли за 0,02–0,08 секунды.
- Maintenance и согласованный backup отработали; initial isolated restore прошёл.
- После исправления controller локально прошли 4 release-flow теста и
  ci/check_deployment.py (syntax/readiness/production guards).

Полный live onboarding с настоящим Telegram contact, реальный passkey provider sync,
нагрузка/одновременный upload, off-host DR и внешние alerts ещё не проверены/не настроены.
Один сервер — единая точка отказа. Публичное развёртывание не является security audit.
CI работает; автоматический CD отсутствует по выбору пользователя обойтись без CI keys.


## 27 сентября: точечное обновление выбора внешнего passkey

В работающий release `05f361793f546e580c2e9de0696761a446f226b8` вручную внесён клиентский hotfix: только `cloud-cypher/web/passkeys.js`, текст шага passkey в `index.html` и соответствующие две записи `release-manifest.json`. Это рабочие отличия от первоначального client SHA, а не новый опубликованный Git-релиз. Источник исправления сохранён в workspace и publication checkout. Новые регистрация, активация и вход запрашивают внешнее устройство, с hybrid/телефоном в приоритете; явно локальный ответ отклоняется. Серверная policy, DB и ключи не менялись. Добровольный skip из другой задачи этим hotfix не публиковался.

Перед заменой проверены прежние SHA256 и release path, взят release lock; файлы заменены через временные файлы с сохранением прав. Исходные два файла и manifest сохранены в `/opt/nimbus/hotfix-backups/20260926T222643Z-external-passkey`. Для отката этого UI восстанавливаются только эти файлы; DB restore не требуется. Следующий полный релиз должен включать это исправление.

Публичный HTTPS подтвердил новые байты и CSP/no-store/nosniff: `passkeys.js` — `f33872b77a2c1f7106a6a9c5b89872876eb04c5d7951f880bef9a74b6e849e51`, `index.html` — `707bbb763b9820feba02bd02cde0b36939d7f09c6ea4eb11070fe34f4835714b`. Web и Telegram services active; health/session 200, файлы без сессии 401, media 404. Локально прошли 147 Django tests, 26 клиентских tests, полный browser E2EE с внешним виртуальным USB-аутентификатором и проверки доставки/подмены. Обе темы и ширины 1280/390/320 проверены. Реальные QR/Bluetooth/телефон и provider sync не проверены.
