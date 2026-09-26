// Capture the actual response bodies received by a clean, synthetic browser.
import {createRequire} from 'node:module';
import {join} from 'node:path';
const require = createRequire(import.meta.url);
const {chromium} = process.env.PLAYWRIGHT_MODULE ? require(process.env.PLAYWRIGHT_MODULE) : require('playwright');
const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
try {
  const context = await browser.newContext({recordHar: {path: join(process.env.NIMBUS_TEST_WORK, 'tampered-browser.har'), content: 'embed', mode: 'full', urlFilter: '**/vault/**'}});
  const page = await context.newPage();
  await page.goto(process.env.NIMBUS_TEST_BASE_URL + '/vault/');
  await page.locator('#public-panel').waitFor({state: 'visible'});
  await context.close();
} finally { await browser.close(); }
