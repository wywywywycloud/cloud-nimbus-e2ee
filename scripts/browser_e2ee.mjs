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
const email = 'browser@example.invalid';
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
await cdp.send('WebAuthn.addVirtualAuthenticator', {options: {
  protocol: 'ctap2', ctap2Version: 'ctap2_1', transport: 'internal', hasResidentKey: true,
  hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true,
  hasPrf: true, defaultBackupEligibility: true, defaultBackupState: true,
}});
function record(name, details = {}) { checks.push({name, status: 'passed', ...details}); console.log(`PASS ${name}`); }
async function newestCode() {
  return execFileSync(process.env.NIMBUS_TEST_PYTHON || 'python3', ['scripts/read_test_mail.py', process.env.NIMBUS_TEST_EMAIL_DIR], {encoding: 'utf8'}).trim();
}
async function otpIfNeeded(target = page) {
  await target.locator('#otp-dialog').waitFor({state: 'visible'});
  await target.locator('#otp-code').fill(await newestCode());
  await target.locator('#otp-form button[type=submit]').click();
}
async function login(password, target = page) {
  await target.goto(base + '/vault/');
  if (await target.locator('#locked-panel').isVisible()) {
    await target.locator('#unlock-password').fill(password);
    await target.locator('#unlock-button').click();
  } else {
    await target.locator('#login-link').click();
    await target.locator('#auth-username').fill(email);
    await target.locator('#auth-password').fill(password);
    await target.locator('#login-button').click();
  }
  await otpIfNeeded(target);
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
  await page.locator('#register-email').fill(email);
  await page.locator('#register-password').fill(passwords[0]);
  await page.locator('#register-password-confirm').fill(passwords[0]);
  await page.locator('#register-button').click();
  await page.waitForURL('**/auth/verify-email/');
  await page.locator('input[name=code]').fill(await newestCode());
  await page.locator('button[type=submit]').first().click();
  await page.waitForURL('**/vault/');
  await login(passwords[0]);
  record('email registration, OPAQUE password login and email confirmation');
  assert.equal(await page.locator('#upload-button').isDisabled(), true);
  record('upload blocked until passkey recovery is enrolled');
  await page.locator('#enroll-passkey-button').click();
  await page.locator('#enroll-password').fill(passwords[0]);
  await page.locator('#enroll-confirm-button').click();
  await otpIfNeeded();
  await page.waitForFunction(() => !document.querySelector('#upload-button').disabled);
  record('real browser WebAuthn registration, PRF and verified activation');
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
      if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme-button').click();
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
  await page.locator('#auth-username').fill(email);
  await page.locator('#auth-password').fill(passwords[0]);
  await page.locator('#login-button').click();
  await page.locator('#login-dialog .dialog-error').waitFor({state: 'visible'});
  assert.equal(await page.locator('#files-panel').isVisible(), false);
  record('old password rejected after change');
  await page.locator('#passkey-login-button').click();
  await page.locator('#files-panel').waitFor({state: 'visible'});
  assert.equal(sha(await download(page, filename)), sha(plaintext));
  record('passkey + PRF opens files after browser session cookies are removed');
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
  await page.locator('#totp-settings-button').click();
  await page.locator('#totp-password').fill(passwords[2]);
  await page.locator('#totp-start-form button[type=submit]').click();
  await otpIfNeeded();
  await page.locator('#totp-finish-form').waitFor({state: 'visible'});
  const totpSecret = await page.locator('#totp-secret').inputValue();
  const totp = () => execFileSync(process.env.NIMBUS_TEST_PYTHON || 'python3', ['-c', 'import pyotp,sys;print(pyotp.TOTP(sys.argv[1]).now())', totpSecret], {encoding: 'utf8'}).trim();
  await page.locator('#totp-code').fill(totp());
  await page.locator('#totp-finish-form button[type=submit]').click();
  await page.locator('#totp-dialog').waitFor({state: 'hidden'});
  record('TOTP enrollment requires password proof and a valid generator code');
  // TOTP enrollment consumes this time step; do not replay its code at login.
  const previousCode = totp();
  while (totp() === previousCode) await new Promise(resolve => setTimeout(resolve, 500));
  const stale = await browser.newContext({acceptDownloads: true});
  const stalePage = await stale.newPage();
  await stalePage.goto(base + '/vault/');
  await stalePage.locator('#login-link').click();
  await stalePage.locator('#auth-username').fill(email);
  await stalePage.locator('#auth-password').fill(passwords[2]);
  await stalePage.locator('#login-button').click();
  await stalePage.locator('#otp-dialog').waitFor({state: 'visible'});
  assert.match(await stalePage.locator('#otp-description').innerText(), /TOTP/);
  const preOtp = await stalePage.evaluate(async () => (await fetch('/api/cypher/session/')).json());
  assert.equal(preOtp.authenticated, false);
  await stalePage.locator('#otp-code').fill(totp());
  await stalePage.locator('#otp-form button[type=submit]').click();
  await stalePage.locator('#files-panel').waitFor({state: 'visible'});
  assert.equal(sha(await download(stalePage, filename)), sha(plaintext));
  record('password plus TOTP replaces email code and opens same files; no session before code verification');
  await page.locator('#reset-vault-button').click();
  await page.locator('#reset-email').fill(email);
  await page.locator('#reset-send-button').click();
  await page.locator('#reset-form').waitFor({state: 'visible'});
  await page.locator('#reset-code').fill(await newestCode());
  await page.locator('#reset-confirm').fill('DELETE ALL FILES');
  await page.locator('#confirm-reset-button').click();
  await page.locator('#new-password-dialog').waitFor({state: 'visible'});
  const afterReset = await page.evaluate(async () => (await fetch('/api/cypher/session/')).json());
  assert.equal(afterReset.vault, null);
  assert.equal(afterReset.passkey_ready, false);
  assert.equal(afterReset.otp_method, 'email');
  const oldAccess = await stalePage.evaluate(async () => (await fetch('/api/cypher/files/')).status);
  assert.equal(oldAccess, 401);
  await stale.close();
  const missingOldFile = await page.evaluate(async id => (await fetch(`/api/cypher/files/${id}/download/`)).status, dataRecord.id);
  assert.equal(missingOldFile, 404);
  record('explicit email reset destroys vault and passkey/TOTP bindings, invalidates other sessions and removes old file access');
  const resetPassword = 'After destructive reset 2026!';
  await page.locator('#after-reset-password').fill(resetPassword);
  await page.locator('#after-reset-confirm').fill(resetPassword);
  await page.locator('#after-reset-button').click();
  await page.locator('#new-password-dialog').waitFor({state: 'hidden'});
  assert.equal(await page.locator('.download-file').count(), 0);
  assert.equal(await page.locator('#upload-button').isDisabled(), true);
  await page.locator('#enroll-passkey-button').click();
  await page.locator('#enroll-password').fill(resetPassword);
  await page.locator('#enroll-confirm-button').click();
  await otpIfNeeded();
  await page.waitForFunction(() => !document.querySelector('#upload-button').disabled);
  await page.locator('#file-input').setInputFiles({name: filename, mimeType: 'text/plain', buffer: plaintext});
  await page.getByRole('button', {name: `Скачать ${filename}`, exact: true}).waitFor();
  assert.equal(sha(await download(page, filename)), sha(plaintext));
  record('after destructive reset, new password/passkey protects a new empty vault and accepts new encrypted uploads');
  for (const value of [...passwords, resetPassword, filename, 'NIMBUS_SYNTHETIC_PLAINTEXT_2026']) {
    assert.equal(sentBodies.some(body => body.includes(Buffer.from(value))), false);
  }
  record('captured browser requests never contain plaintext passwords, file content or filename');
  assert.deepEqual(errors, []);
  record('no unhandled browser JavaScript errors');
  await writeFile(join(reports, 'browser-e2e.json'), JSON.stringify({status: 'passed', browser: await browser.version(), checks,
    limits: ['Synthetic Chrome virtual authenticator, not actual Apple/Google cloud synchronization.', 'No independent security audit or production load test.', 'Screenshots and input files contain synthetic data only.']}, null, 2) + '\n');
} catch (error) {
  await page.screenshot({path: join(reports, 'browser-failure.png'), fullPage: true}).catch(() => {});
  console.error('BROWSER FAILURE', error.message, 'PAGE ERRORS', errors);
  throw error;
} finally {
  await context.close();
  await browser.close();
}
