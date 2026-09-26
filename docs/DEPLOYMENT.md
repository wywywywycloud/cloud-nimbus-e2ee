# Cloud Nimbus: HTTPS только на 9443

Текущий публичный адрес — [https://cloud.nimbus.by:9443/vault/](https://cloud.nimbus.by:9443/vault/).
По требованию владельца 27 сентября 2026 года схема с внешним :443 отменена.
Nginx слушает **только :9443**, IPv4 и IPv6, напрямую проксирует на Gunicorn
127.0.0.1:8000. Nginx не открывает :80 или :443, включая редиректы.
Старый `https://nimbus.by:9443` перенаправляется на новый домен **с :9443**,
сохраняя path/query. Корень возвращает относительный `/vault/`.

## Применённый серверный hotfix

Сервер 13.143.141.139, release symlink по-прежнему указывает на
05f361793f546e580c2e9de0696761a446f226b8 с последующими точечными исправлениями.
Из активной конфигурации Nginx удалены listener :80/:443 и промежуточный TLS proxy.
PASSKEY_ORIGIN изменён на `https://cloud.nimbus.by:9443`;
DJANGO_ALLOWED_HOSTS=cloud.nimbus.by, **PASSKEY_RP_ID=nimbus.by сохранён**.
OPAQUE setup, Django secret, БД, vault и пользовательские credentials не менялись.
После `nginx -t` выполнены reload Nginx и restart web; health на :9443 вернул 200.
`ss` подтвердил только :9443 у Nginx. На освобождённом :443 был обнаружен
отдельный процесс **rw-core**; его служба не изменялась.

Root-only backup предыдущего nginx/runtime.env:
`/opt/nimbus/hotfix-backups/20260926T230242Z-9443-only`.
В нём есть секреты; не копировать в Git. Возвращать старый конфиг целиком нельзя:
он снова займёт :443. При восстановлении сохранять правило единственного :9443.
DB restore или смена ключей для этой правки не нужны.

## DNS, TLS и продление сертификата

A cloud.nimbus.by → 13.143.141.139 (TTL 3600); apex A и NS не изменены.
Сертификат `/etc/letsencrypt/live/cloud.nimbus.by` покрывает cloud.nimbus.by и
nimbus.by, действителен до **25 декабря 2026 года**.
Certbot timer включён, но сохранённый HTTP-01/webroot способ продления больше
неработоспособен без :80. До истечения нужен DNS-01 или внешний обработчик
ACME challenge; такая автоматизация пока не настроена. Нельзя возвращать
listener :80/:443 или standalone certbot ради renewal без нового решения владельца.

## Повторное применение конфигурации

1. Подставить LEGACY_DOMAIN=nimbus.by, затем DOMAIN=cloud.nimbus.by в единственном
   `deploy/nginx.conf.template`. Сохранить текущие секреты и backup вне Git.
2. Заменить активный Nimbus config; удалить прежние Nimbus blocks на :80/:443,
   в том числе старый nginx-443-redirect. Проверить весь `nginx -T`, не только шаблон.
3. Установить PASSKEY_ORIGIN=https://cloud.nimbus.by:9443 и
   DJANGO_ALLOWED_HOSTS=cloud.nimbus.by. Сохранить PASSKEY_RP_ID=nimbus.by.
4. Проверить `nginx -t`, reload Nginx, restart web. Production settings требуют
   HTTPS :9443 и RP, равный hostname либо его родительскому DNS-домену.
5. Проверить владельцев listener через `ss`, HTTPS health/root/vault/media,
   редирект apex с портом, точный origin/CSRF. Другие службы на :443 не останавливать.

До выдачи страницы Nginx проверяет полный входящий Host, включая :9443.
Если другая служба пересылает TLS с :443 на :9443, Host без порта также получает
редирект на канонический origin: иначе форма открывается, а CSRF отклоняет POST.

Proxy фиксирует Host=cloud.nimbus.by:9443 и HTTPS scheme, перезаписывает forwarded
headers без доверия входящему X-Real-IP. Gunicorn остаётся на loopback.
Release controller берёт health Host из PASSKEY_ORIGIN, включая порт.
Реальный вход/passkey на новом origin требует отдельной пользовательской проверки;
тестовый аутентификатор не подтверждает физическую синхронизацию provider.

## Проверки конфигурации

`ci/test_nginx.py` запускает настоящий Nginx из шаблона на изолированном высоком
порту с временным TLS: проверяет единственный listener, прямой proxy, точный Host,
редирект apex с :9443, private media и замену поддельных forwarded headers.
`ci/check_deployment.py` проверяет origin :9443, parent RP, отказ :443/без порта
и неверных origin/host/RP. `ci/test_release.py` проверяет health Host с :9443.
Все четыре Nginx теста (изолированно под nimbus-build), четыре release теста
и production guards прошли после изменения.

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


---

Следующие разделы — история; их старые port/origin настройки заменены инструкцией выше.

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
