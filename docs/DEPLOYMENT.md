# Cloud Nimbus: публичный HTTPS без порта, внутренний TLS на loopback

## Применено на сервере 27 сентября 2026 года, 00:35 UTC

Проверено: https://nimbus.by/ → 308 https://cloud.nimbus.by/ → 302 /vault/ → 200.
https://cloud.nimbus.by/vault/ открывается в реальном браузере без порта.
DNS Hoster.by уже содержит две A-записи на 13.143.141.139; изменения не требовались.

Фактическая схема:

```text
Браузер: https://nimbus.by или https://cloud.nimbus.by (стандартный HTTPS)
  → rw-core / VLESS REALITY :443 (действующая VPN-служба)
  → REALITY target 127.0.0.1:9443 (был настроен до исправления)
  → Nginx TLS/HTTP2, только 127.0.0.1:9443
  → Gunicorn 127.0.0.1:8000
```

Обычный TLS-трафик передаётся в target согласно механизму
[REALITY](https://xtls.github.io/en/config/transports/reality.html).
Nimbus не занимает 80/443, прямой внешний 9443 остаётся недоступен.
Основной origin — https://cloud.nimbus.by, RP ID — nimbus.by.

Точечно изменены `config/production.py` в активном release 4a522983a9ffef26fc019a08eabf0efe05d8cb07,
`/etc/nginx/sites-available/nimbus` и только PASSKEY_ORIGIN в `/etc/nimbus/runtime.env`.
Root-only backup: `/opt/nimbus/hotfix-backups/20260927T003453Z-origin-no-port`.
Сохранены остальные env/секреты, БД, пользовательские файлы и все клиентские байты,
включая server-only logout hotfix и manifest. Полный релиз не выполнялся; Git не
опубликован. Перед будущим релизом перенести оба server-only исправления в
согласованный код, не затереть logout hotfix.

Gunicorn перезапущен. Reload Nginx не смог заменить wildcard listener на loopback
(`bind: Address already in use`), поэтому после `nginx -t` выполнен restart только
Nginx. Подтверждён единственный listener 127.0.0.1:9443. Процесс rw-core с PID 11481
и контейнер remnanode не перезапускались и не перенастраивались. Это проверка
сохранности процесса и конфигурации, не отдельный end-to-end тест VPN-клиента.

В изолированной Linux-копии под nimbus-build с синтетическими данными прошли:
148 Django tests, 4 Nginx tests, 4 release-flow tests, полный ci/check_deployment.py,
makemigrations --check --dry-run и Django check. На live прошли production check
и deployment_check, public health/vault/session, private media 404, anonymous
files 401. Отдельная анонимная сессия подтвердила logout POST с новым origin,
отказ 403 для старого origin :9443 и чужого домена. SHA256 публичного app.js
совпал с сохранённым до изменения server-only hotfix. Реальный пользовательский
passkey и полный браузерный onboarding в этой задаче не выполнялись.

Продление сертификата не менялось: текущий срок подтверждён до 25 декабря 2026.
Нужен DNS-01 или отдельный внешний HTTP-01 обработчик; Nimbus не открывает 80/443.
Работоспособность сайта сейчас не означает исправленного автоматического renewal.


## Проектная схема и инструкция применения

Целевой адрес — https://cloud.nimbus.by/vault/. Nimbus Nginx слушает только
`127.0.0.1:9443`, Gunicorn — `127.0.0.1:8000`. Listener на 80/443 и IPv6 wildcard
в проекте отсутствуют. Внешняя служба на 443 должна передавать TLS на этот
loopback listener (или проксировать HTTPS с проверкой сертификата и SNI
cloud.nimbus.by). Это внешняя зависимость: текущий target подтверждён при live-проверке выше;
конфигурация VPN в этой задаче не менялась.

Nginx сравнивает `$host` с cloud.nimbus.by. Правильный домен без порта не получает
редирект на 9443; другой hostname получает 308 на https://cloud.nimbus.by с теми
же path/query. `/` возвращает относительный `/vault/`. Proxy задаёт Host без
порта и X-Forwarded-Proto=https, перезаписывает forwarded headers. CSRF и WebAuthn
проверяют один точный публичный origin. `config.production` требует HTTPS без
явно указанного порта (`urlsplit(...).port is None`), включая отказ старому :9443.

HTTP/2 включён параметром `listen ... ssl http2` для совместимости с Nginx 1.24
в Ubuntu 24.04 CI. На Nginx >=1.25.1 эквивалентны `listen 127.0.0.1:9443 ssl;`
и отдельное `http2 on;` ([документация Nginx](https://nginx.org/en/docs/http/ngx_http_v2_module.html)).

## Применение после отдельного решения о deployment

1. Проверить фактический release, Nginx, владельцев портов и внешний маршрут
   443 → 127.0.0.1:9443. Не останавливать чужую службу на 443. Сохранить backup
   текущей конфигурации вне Git. Сначала учесть server-only logout hotfix
   в app.js/manifest: полный релиз из Git может его затереть.
2. Подставить LEGACY_DOMAIN=nimbus.by, затем DOMAIN=cloud.nimbus.by в
   `deploy/nginx.conf.template`. Проверить весь `nginx -T`: Nimbus не должен
   добавлять listener на 80/443 или публичный 9443.
3. В существующем `/etc/nimbus/runtime.env` заменить только публичные параметры
   из `deploy/public-origin.env.example`:

   ```sh
   PASSKEY_ORIGIN=https://cloud.nimbus.by
   PASSKEY_RP_ID=nimbus.by
   DJANGO_ALLOWED_HOSTS=cloud.nimbus.by
   ```

   Сохранить OPAQUE setup, Django secret и остальные значения. Не заменять весь
   runtime.env коротким фрагментом. Миграции данных для этой правки не нужны.
4. Согласованно применить production.py, env и Nginx; проверить `nginx -t`, затем
   restart `nimbus.service` (Gunicorn). При смене wildcard listener на loopback
   нужен restart Nginx: одного reload может быть недостаточно. Проверить listener
   через `ss` и фактический HTTP 200, а не только успешный systemctl reload.
5. Снаружи проверить health/vault/session, отсутствие :9443 в Location,
   `/media/` → 404, регистрацию/CSRF и вход существующим passkey на новом origin.
   RP ID остаётся прежним; credentials и PRF input не меняются. Реальный passkey
   требует отдельной проверки, которую локальные тесты не заменяют.

## Сертификат без занятия 80/443 проектом

По историческому срезу сертификат действует до 25 декабря 2026 года; текущий
срок перед deployment нужно проверить. Старый HTTP-01/webroot renewal не
исправляется этой правкой. HTTP-01 требует внешнего порта 80; 9443 его не заменяет
([Let's Encrypt](https://letsencrypt.org/docs/challenge-types/)).

Нужны автоматизированный DNS-01 с доступом к DNS API либо отдельный внешний
обработчик HTTP-01 на 80, которым управляет другая служба. Nimbus не добавляет
блок `listen 80`, не запускает standalone certbot и не занимает 443 для ACME.
DNS API/внешний обработчик в этой задаче не настроены. После настройки выбранного
способа выполнить на сервере `certbot renew --dry-run` и проверить deploy hook
`nginx -t` + reload. Здесь dry-run и выпуск сертификата не выполнялись.

## Локальные проверки

`ci/test_nginx.py` проверяет единственный loopback listener, отсутствие редиректа
для публичного Host, redirect другого hostname без порта с сохранением URI,
закрытый media и замену forwarded headers. `ci/check_deployment.py` проверяет
origin без порта, parent RP и отказ неверным origin/host/RP. `ci/test_release.py`
проверяет health Host без порта. Результаты новой проверки не следует подменять
историческими результатами ниже.

---

## Результаты локальной проверки на Windows

- `manage.py makemigrations --check --dry-run` и `manage.py check` прошли.
- Production guards из `ci.check_deployment.check_production` прошли отдельно
  с синтетическим setup, без Linux readiness: HTTPS redirect без порта, CSRF
  для нового origin, отказ старому origin/чужому домену и настройки host/RP.
- `manage.py test passkeys`: 29 тестов прошли, включая регистрацию/активацию
  на origin с :9443 и вход тем же credential после удаления порта; assertion
  со старым origin отклоняется, прежний encrypted wrapper сохранён.
- Общий `manage.py test` до добавления нового passkey-теста: найдено 147,
  выполнено 118; 3 ошибки. Один legacy file-flow тест не может удалить открытый
  файл в Windows (WinError 32); setup классов OPAQUE и TOTP завершается
  OpaqueUnavailable из-за pipe/selectors bridge. Код этих компонентов не менялся.
- Полный `ci/check_deployment.py` не подтверждён: Bash отсутствует; при отдельном
  запуске Python-части readiness останавливается на том же OPAQUE bridge.
- `ci/test_nginx.py` не запустил сценарии: нет OpenSSL CLI и Nginx. Linux release
  fault tests не запускались без Bash. `scripts/test_e2ee.py` запустил временный
  Django стенд, но остановился на отсутствии Playwright Chromium.

Полный Linux CI, реальный Nginx, внешний ingress, вход с физическим passkey и
Certbot renewal этой локальной проверкой не подтверждены.

## История до локальной правки

Следующие записи сохранены как исторический срез, а не инструкция к применению.

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


## Публикация Git 27 сентября после исправлений :9443

Backend закрепляет клиент `113188a58d371d6f1e14e3bd950c68b8b34eb4b6`, включая
parent RP, добровольный passkey skip, TOTP QR, manifest и independent verifier.
[Свежие локальные результаты](../reports/publication-2026-09-27/README.md):
147 backend, 34 Node, 38 verifier/vendor tests и 26 браузерных сценариев прошли.
Workflow отдельного клиента активирован; автоматический deploy backend требует
явного `NIMBUS_DEPLOY_ENABLED=true` (переменная сейчас отсутствует).
Публикация Git не меняет работающий release. На момент независимой проверки сайт
ещё выдавал прежние app.js/index.html/style.css и не отдавал QR-модули, поэтому
проверка свежим Git manifest корректно вернула mismatch. Для синхронизации нужен
отдельный согласованный релиз backend/client и миграция accounts.0008; подмена
эталонного manifest скачанным с сайта недопустима.
