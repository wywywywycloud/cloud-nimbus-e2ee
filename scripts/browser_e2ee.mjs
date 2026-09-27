// Synthetic browser integration tests. No real account/profile is used.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFile, writeFile, mkdir, readdir} from 'node:fs/promises';
import {join} from 'node:path';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const require = createRequire(import.meta.url);
const {chromium} = process.env.PLAYWRIGHT_MODULE ? require(process.env.PLAYWRIGHT_MODULE) : require('playwright');
const base = process.env.NIMBUS_TEST_BASE_URL;
const work = process.env.NIMBUS_TEST_WORK;
const reports = process.env.NIMBUS_TEST_REPORTS;
const username = 'browser_synthetic';
let totpSecret = '';
let previousCode = '';
const passwords = ['Synthetic password one 2026!', 'Synthetic password two 2026!', 'Recovered password three 2026!'];
const checks = [];
const errors = [];
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
const context = await browser.newContext({acceptDownloads: true, recordHar: {path: join(work, 'browser.har'), content: 'embed', mode: 'full', urlFilter: '**/vault/**'}});
const page = await context.newPage();
page.on('pageerror', error => errors.push(error.message));
const sentBodies = [];
page.on('request', request => { const body = request.postDataBuffer(); if (body) sentBodies.push(body); });
page.setDefaultTimeout(15000);
const cdp = await context.newCDPSession(page);
await cdp.send('WebAuthn.enable');
const {authenticatorId} = await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {
  protocol: 'ctap2', ctap2Version: 'ctap2_1', transport: 'usb', hasResidentKey: true,
  hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true,
  hasPrf: true, defaultBackupEligibility: true, defaultBackupState: true,
}});
function record(name, details = {}) { checks.push({name, status: 'passed', ...details}); console.log(`PASS ${name}`); }
function telegram(action, value) {
  return execFileSync(process.env.NIMBUS_TEST_PYTHON || 'python3', ['scripts/test_telegram.py', action, ...(value ? [value] : [])], {encoding: 'utf8'}).trim();
}
function totp() {
  return execFileSync(process.env.NIMBUS_TEST_PYTHON || 'python3', ['-c', 'import pyotp,sys;print(pyotp.TOTP(sys.stdin.read()).now())'], {input: totpSecret, encoding: 'utf8'}).trim();
}
async function nextTotp() {
  while (totp() === previousCode) await new Promise(resolve => setTimeout(resolve, 500));
  previousCode = totp();
  return previousCode;
}
async function otpIfNeeded(target = page, expectNoSession = false) {
  await target.locator('#otp-dialog').waitFor({state: 'visible'});
  const before = await target.evaluate(async () => (await fetch('/api/cypher/session/')).json());
  if (expectNoSession) assert.equal(before.authenticated, false);
  await target.locator('#otp-code').fill(await nextTotp());
  await target.locator('#otp-form button[type=submit]').click();
}
async function screenshots(label) {
  await mkdir(join(reports, 'screenshots'), {recursive: true});
  for (const theme of ['light', 'dark']) {
    if (await page.locator('html').getAttribute('data-theme') !== theme) {
      if (await page.locator('dialog[open]').count()) await page.locator('#theme-button').evaluate(button => button.click());
      else await page.locator('#theme-button').click();
    }
    for (const width of [1280, 390, 320]) {
      await page.setViewportSize({width, height: 900});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `layout overflow ${label}/${theme}/${width}`);
      await page.screenshot({path: join(reports, 'screenshots', `${label}-${theme}-${width}.png`), fullPage: true, mask: [page.locator('#totp-qr'), page.locator('#totp-secret')]});
    }
  }
  await page.setViewportSize({width: 1280, height: 900});
}
async function setupTotp() {
  await page.locator('#totp-step').waitFor({state: 'visible'});
  await page.locator('#totp-start-button').click();
  await page.locator('#totp-finish-form').waitFor({state: 'visible'});
  totpSecret = await page.locator('#totp-secret').inputValue();
  assert.equal(await page.locator('#totp-qr').isVisible(), true);
  assert.equal(await page.locator('#totp-secret').isVisible(), false);
  await screenshots('onboarding-totp-qr');
  // Disposable synthetic secret only, for an independent QR decoding check.
  await page.locator('#totp-qr').screenshot({path: join(reports, 'synthetic-totp-qr.png')});
  await writeFile(join(reports, 'synthetic-totp-qr-secret.txt'), totpSecret);
  previousCode = '';
  await page.locator('#totp-code').fill(await nextTotp());
  await page.locator('#totp-finish-button').click();
  await page.locator('#files-panel').waitFor({state: 'visible'});
}
async function login(password, target = page) {
  await target.goto(base + '/vault/');
  if (await target.locator('#locked-panel').isVisible()) {
    await target.locator('#unlock-password').fill(password);
    await target.locator('#unlock-button').click();
  } else {
    await target.locator('#login-link').click();
    await target.locator('#auth-username').fill(username);
    await target.locator('#auth-password').fill(password);
    await target.locator('#login-button').click();
  }
  await otpIfNeeded(target, true);
  await target.locator('#files-panel').waitFor({state: 'visible'});
}
async function download(target, name) {
  const event = target.waitForEvent('download');
  await target.getByRole('button', {name: `Скачать ${name}`, exact: true}).click();
  const file = await event;
  assert.equal(file.suggestedFilename(), name);
  return readFile(await file.path());
}
try {
  await page.goto(base + '/vault/');
  await page.locator('#public-panel').waitFor({state: 'visible'});
  assert.ok(await page.getByRole('link', {name: 'Как проверить', exact: true}).isVisible());
  await page.locator('#register-link').click();
  await page.locator('#register-username').fill(username);
  await page.locator('#register-password').fill(passwords[0]);
  await page.locator('#register-password-confirm').fill(passwords[0]);
  await page.locator('#register-button').click();
  await page.locator('#telegram-step').waitFor({state: 'visible'});
  assert.equal(await page.locator('#files-panel').isVisible(), false);
  const restricted = await page.evaluate(async () => (await fetch('/api/cypher/files/')).status);
  assert.equal(restricted, 403);
  await screenshots('onboarding-telegram');
  record('username-only OPAQUE registration yields restricted onboarding; files denied');
  await page.locator('#telegram-check-button').click();
  await page.waitForFunction(() => document.querySelector('#telegram-status').textContent.includes('пока'));
  await page.locator('#telegram-start-button').click();
  await page.locator('#telegram-link').waitFor({state: 'visible'});
  telegram('confirm', await page.locator('#telegram-link').getAttribute('href'));
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await page.locator('#passkey-step').waitFor({state: 'visible'});
  await page.waitForFunction(() => !document.querySelector('#enroll-passkey-button').disabled);
  assert.equal(await page.locator('#files-panel').isVisible(), false);
  await screenshots('onboarding-passkey');
  await page.locator('#skip-passkey-button').click();
  await page.locator('#skip-passkey-dialog').waitFor({state: 'visible'});
  await screenshots('skip-passkey-warning');
  await page.locator('#return-passkey-button').click();
  assert.equal(await page.locator('#passkey-step').isVisible(), true);
  assert.equal(await page.evaluate(async () => (await (await fetch('/api/cypher/session/')).json()).passkey_skipped), false);
  await page.locator('#skip-passkey-button').click();
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#skip-passkey-dialog').isVisible(), false);
  record('skip warning is cancellable without accepting risk');
  record('synthetic Telegram confirmation and return-to-tab advance to mandatory passkey');
  // Reload loses only local keys. Password proof resumes the same setup step.
  await page.reload();
  await page.locator('#unlock-password').fill(passwords[0]);
  await page.locator('#unlock-button').click();
  await page.locator('#passkey-step').waitFor({state: 'visible'});
  record('reload resumes incomplete onboarding after fresh OPAQUE proof');
  // Real server error codes must stay visible beside the passkey action.
  for (const [code, message] of [['synced_passkey_required', 'только для этого устройства'], ['passkey_backup_required', 'не подтвердил резервирование']]) {
    await page.route('**/api/passkeys/register/finish/', route => route.fulfill({status: 400, contentType: 'application/json', body: JSON.stringify({error: code})}));
    await page.locator('#enroll-passkey-button').click();
    await page.waitForFunction(text => document.querySelector('#onboarding-status').textContent.includes(text), message);
    assert.equal(await page.locator('#onboarding-status').isVisible(), true);
    assert.equal(await page.locator('#status-message').isVisible(), false);
    assert.equal(await page.locator('#files-panel').isVisible(), false);
    await page.unroute('**/api/passkeys/register/finish/');
  }
  await screenshots('onboarding-passkey-error');
  record('device-only and unbacked passkey errors remain visible in onboarding without unlocking files');
  await page.locator('#enroll-passkey-button').click();
  await page.locator('#totp-step').waitFor({state: 'visible'});
  assert.equal(await page.locator('#files-panel').isVisible(), false);
  assert.equal(await page.evaluate(async () => (await fetch('/api/cypher/files/')).status), 403);
  await screenshots('onboarding-totp');
  record('real browser WebAuthn registration and PRF activation still require TOTP before file access');
  const pendingContext = await browser.newContext();
  const pendingPage = await pendingContext.newPage();
  await pendingPage.goto(base + '/vault/');
  await pendingPage.locator('#login-link').click();
  await pendingPage.locator('#auth-username').fill(username);
  await pendingPage.locator('#auth-password').fill(passwords[0]);
  await pendingPage.locator('#login-button').click();
  await pendingPage.locator('#totp-step').waitFor({state: 'visible'});
  await setupTotp();
  await page.waitForFunction(() => !document.querySelector('#upload-button').disabled);
  assert.equal(await page.locator('#totp-qr').getAttribute('width'), '0');
  assert.equal(await page.locator('#totp-secret').inputValue(), '');
  record('mandatory TOTP enrollment completes onboarding and permits file access');
  const pendingSession = await pendingPage.evaluate(async () => (await fetch('/api/cypher/session/')).json());
  assert.equal(pendingSession.authenticated, false);
  assert.equal(await pendingPage.evaluate(async () => (await fetch('/api/cypher/files/')).status), 401);
  await pendingContext.close();
  record('another password-only onboarding session gains no access when setup completes elsewhere');
  const filename = 'личный-секрет-2026.txt';
  const plaintext = Buffer.from('NIMBUS_SYNTHETIC_PLAINTEXT_2026\nПриватный файл — 🗝️\n'.repeat(500));
  await page.locator('#file-input').setInputFiles({name: filename, mimeType: 'text/plain', buffer: plaintext});
  await page.getByRole('button', {name: `Скачать ${filename}`, exact: true}).waitFor();
  const downloaded = await download(page, filename);
  assert.equal(sha(downloaded), sha(plaintext));
  record('upload encrypts and download decrypts exact original bytes', {plaintext_sha256: sha(plaintext), bytes: plaintext.length});
  const pngName = 'preview.png';
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==', 'base64');
  await page.locator('#file-input').setInputFiles({name: pngName, mimeType: 'image/png', buffer: png});
  await page.getByRole('button', {name: `Просмотреть ${pngName}`, exact: true}).click();
  await page.locator('#preview-image').waitFor({state: 'visible'});
  assert.ok((await page.locator('#preview-image').getAttribute('src')).startsWith('blob:'));
  await page.locator('#close-preview-button').click();
  record('image preview uses browser-decrypted blob URL');
  await page.getByRole('button', {name: filename, exact: true}).click();
  await page.locator('#preview-text').waitFor({state: 'visible'});
  assert.equal(await page.locator('#preview-code').textContent(), plaintext.toString());
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#preview-code').textContent(), '');
  const codeName = 'preview.ts';
  const codeText = '// Пример кода\nconst message: string = "Привет";\nconsole.log(message);\n'.repeat(80);
  await page.locator('#file-input').setInputFiles({name: codeName, mimeType: 'application/octet-stream', buffer: Buffer.from(codeText)});
  await page.getByRole('button', {name: `Просмотреть ${codeName}`, exact: true}).click();
  await page.locator('#preview-text').waitFor({state: 'visible'});
  assert.equal(await page.locator('#preview-code').textContent(), codeText);
  assert.ok(await page.locator('#preview-code .hljs-keyword').count());
  await screenshots('text-preview');
  const scroll = await page.locator('#preview-text').evaluate(el => { el.scrollTop = el.scrollHeight; return el.scrollTop; });
  assert.ok(scroll > 0);
  await page.keyboard.press('Escape');
  const hostile = '<script>window.previewExecuted=true</script><img src=x onerror="window.previewExecuted=true">';
  await page.locator('#file-input').setInputFiles({name: 'hostile.html', mimeType: 'text/html', buffer: Buffer.from(hostile)});
  await page.getByRole('button', {name: 'Просмотреть hostile.html', exact: true}).click();
  await page.locator('#preview-text').waitFor({state: 'visible'});
  assert.equal(await page.locator('#preview-code').textContent(), hostile);
  assert.equal(await page.locator('#preview-code script, #preview-code img').count(), 0);
  assert.equal(await page.evaluate(() => Boolean(window.previewExecuted)), false);
  await page.evaluate(async () => (await import('/vault/app.js')).lockVault());
  assert.equal(await page.locator('#preview-code').textContent(), '');
  assert.equal(await page.locator('#preview-dialog').isVisible(), false);
  await page.locator('#passkey-unlock-button').click();
  await page.locator('#files-panel').waitFor({state: 'visible'});
  record('text/code previews preserve full text, highlight both themes, scroll, escape HTML and clear on lock');
  const apiFiles = await page.evaluate(async () => (await fetch('/api/cypher/files/')).json());
  const dataRecord = apiFiles.files.find(item => item.ciphertext_bytes === plaintext.length + 16);
  assert.ok(dataRecord);
  const wire = await page.evaluate(async id => Array.from(new Uint8Array(await (await fetch(`/api/cypher/files/${id}/download/`)).arrayBuffer())), dataRecord.id);
  assert.equal(Buffer.from(wire).includes(plaintext.subarray(0, 30)), false);
  assert.equal(JSON.stringify(apiFiles).includes(filename), false);
  record('HTTP API exposes encrypted bytes and encrypted filename metadata');
  await mkdir(join(reports, 'screenshots'), {recursive: true});
  for (const view of ['list', 'grid']) {
    await page.locator(`#view-${view}`).click();
    for (const theme of ['light', 'dark']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) {
      if (await page.locator('dialog[open]').count()) await page.locator('#theme-button').evaluate(button => button.click());
      else await page.locator('#theme-button').click();
    }
      for (const width of [1280, 390, 320]) {
        await page.setViewportSize({width, height: 900});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `layout overflow ${view}/${theme}/${width}`);
        await page.screenshot({path: join(reports, 'screenshots', `${view}-${theme}-${width}.png`), fullPage: true});
      }
    }
  }
  await page.setViewportSize({width: 1280, height: 900});
  record('list/grid, light/dark and widths 1280/390/320 have no horizontal overflow');
  await page.locator('#password-settings-button').click();
  await page.locator('#current-password').fill(passwords[0]);
  await page.locator('#new-password').fill(passwords[1]);
  await page.locator('#new-password-confirm').fill(passwords[1]);
  await page.locator('#change-password-button').click();
  await otpIfNeeded();
  await page.locator('#password-dialog').waitFor({state: 'hidden'});
  assert.equal(sha(await download(page, filename)), sha(plaintext));
  record('password change rewraps same vault and preserves file bytes');
  const fresh = await browser.newContext({acceptDownloads: true});
  const freshPage = await fresh.newPage();
  await login(passwords[1], freshPage);
  assert.equal(sha(await download(freshPage, filename)), sha(plaintext));
  await fresh.close();
  record('new isolated browser context opens same files using password, without prior device state');
  await context.clearCookies();
  await page.goto(base + '/vault/');
  await page.locator('#login-link').click();
  await page.locator('#auth-username').fill(username);
  await page.locator('#auth-password').fill(passwords[0]);
  await page.locator('#login-button').click();
  await page.locator('#login-dialog .dialog-error').waitFor({state: 'visible'});
  assert.equal(await page.locator('#files-panel').isVisible(), false);
  record('old password rejected after change');
  await page.locator('#passkey-login-button').click();
  await page.locator('#files-panel').waitFor({state: 'visible'});
  assert.equal(sha(await download(page, filename)), sha(plaintext));
  record('passkey + PRF opens files after browser session cookies are removed');
  const {credentials} = await cdp.send('WebAuthn.getCredentials', {authenticatorId});
  await cdp.send('WebAuthn.setCredentialProperties', {authenticatorId, credentialId: credentials[0].credentialId, backupState: false});
  await page.locator('#lock-button').click();
  await page.locator('#passkey-unlock-button').click();
  await page.locator('#files-panel').waitFor({state: 'visible'});
  assert.equal(await page.locator('#upload-button').isDisabled(), true);
  assert.equal(await page.locator('#upload-backup-note').isVisible(), true);
  assert.equal(sha(await download(page, filename)), sha(plaintext));
  record('signed BS=0 permits reading but blocks upload and explains how to confirm backup');
  await cdp.send('WebAuthn.setCredentialProperties', {authenticatorId, credentialId: credentials[0].credentialId, backupState: true});
  await page.locator('#backup-check-button').click();
  await page.waitForFunction(() => !document.querySelector('#upload-button').disabled);
  record('fresh signed BS=1 re-enables upload through passkey confirmation');
  await page.locator('#lock-button').click();
  await page.locator('#locked-forgot-button').click();
  await page.locator('#recovery-password').fill(passwords[2]);
  await page.locator('#recovery-password-confirm').fill(passwords[2]);
  await page.locator('#recovery-button').click();
  await page.locator('#recovery-dialog').waitFor({state: 'hidden'});
  assert.equal(sha(await download(page, filename)), sha(plaintext));
  record('forgotten password recovered through passkey without changing files');
  let downloads = 0;
  page.on('download', () => { downloads += 1; });
  await page.route(`**/api/cypher/files/${dataRecord.id}/download/`, async route => {
    const response = await route.fetch();
    const body = Buffer.from(await response.body());
    body[0] ^= 1;
    await route.fulfill({response, body});
  });
  await page.getByRole('button', {name: `Скачать ${filename}`, exact: true}).click();
  await page.waitForFunction(() => document.querySelector('#status-message').dataset.kind === 'error');
  assert.equal(downloads, 0);
  await page.unroute(`**/api/cypher/files/${dataRecord.id}/download/`);
  record('tampered encrypted download fails authentication and never produces a plaintext download');
  const stale = await browser.newContext({acceptDownloads: true});
  const stalePage = await stale.newPage();
  await login(passwords[2], stalePage);
  assert.equal(sha(await download(stalePage, filename)), sha(plaintext));
  record('password plus mandatory TOTP opens same files; no session before code verification');
  await page.locator('#reset-vault-button').click();
  await page.locator('#reset-username').fill(username);
  await page.locator('#reset-send-button').click();
  await page.locator('#reset-form').waitFor({state: 'visible'});
  await page.locator('#reset-code').fill(telegram('reset-code'));
  await page.locator('#reset-confirm').fill('DELETE ALL FILES');
  await page.locator('#confirm-reset-button').click();
  await page.locator('#new-password-dialog').waitFor({state: 'visible'});
  const afterReset = await page.evaluate(async () => (await fetch('/api/cypher/session/')).json());
  assert.equal(afterReset.vault, null);
  assert.equal(afterReset.passkey_ready, false);
  assert.equal(afterReset.password_setup_required, true);
  assert.equal(afterReset.onboarding_required, true);
  const oldAccess = await stalePage.evaluate(async () => (await fetch('/api/cypher/files/')).status);
  assert.equal(oldAccess, 401);
  await stale.close();
  const missingOldFile = await page.evaluate(async id => (await fetch(`/api/cypher/files/${id}/download/`)).status, dataRecord.id);
  assert.ok([403, 404].includes(missingOldFile));
  record('explicit Telegram reset destroys vault and passkey/TOTP bindings, invalidates other sessions and removes old file access');
  const resetPassword = 'After destructive reset 2026!';
  await page.locator('#after-reset-password').fill(resetPassword);
  await page.locator('#after-reset-confirm').fill(resetPassword);
  await page.locator('#after-reset-button').click();
  await page.locator('#new-password-dialog').waitFor({state: 'hidden'});
  assert.equal(await page.locator('.download-file').count(), 0);
  assert.equal(await page.locator('#upload-button').isDisabled(), true);
  await page.locator('#enroll-passkey-button').click();
  await setupTotp();
  await page.waitForFunction(() => !document.querySelector('#upload-button').disabled);
  await page.locator('#file-input').setInputFiles({name: filename, mimeType: 'text/plain', buffer: plaintext});
  await page.getByRole('button', {name: `Скачать ${filename}`, exact: true}).waitFor();
  assert.equal(sha(await download(page, filename)), sha(plaintext));
  record('after destructive reset, new password/passkey/TOTP protects a new empty vault and accepts new encrypted uploads');
  for (const value of [...passwords, resetPassword, filename, 'NIMBUS_SYNTHETIC_PLAINTEXT_2026']) {
    assert.equal(sentBodies.some(body => body.includes(Buffer.from(value))), false);
  }
  record('captured browser requests never contain plaintext passwords, file content or filename');
  assert.equal(await page.locator('input[type=email]').count(), 0);
  record('client has no email forms');
  assert.deepEqual(errors, []);
  record('no unhandled browser JavaScript errors');
  await writeFile(join(reports, 'browser-e2e.json'), JSON.stringify({status: 'passed', browser: await browser.version(), checks,
    limits: ['Synthetic Chrome virtual authenticator, not actual Apple/Google cloud synchronization.', 'No independent security audit or production load test.', 'Screenshots and input files contain synthetic data only.']}, null, 2) + '\n');
} catch (error) {
  await page.screenshot({path: join(reports, 'browser-failure.png'), fullPage: true, mask: [page.locator('#totp-qr'), page.locator('#totp-secret'), page.locator('#reset-code')]}).catch(() => {});
  console.error('BROWSER FAILURE', error.message, 'PAGE ERRORS', errors);
  throw error;
} finally {
  await context.close();
  await browser.close();
}
