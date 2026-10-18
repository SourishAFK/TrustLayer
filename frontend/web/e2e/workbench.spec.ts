import { expect, test, type Page } from '@playwright/test';

async function connect(page: Page) {
  await page.getByText('API access', { exact: true }).click();
  await page.getByLabel('TrustLayer API key').fill('tl_browser_fixture');
  await page.getByText('API access', { exact: true }).click();
}

test('real extraction endpoint, exact highlights, inspection and exports', async ({ page }) => {
  await page.goto('/workbench/');
  await connect(page);
  const source = '🚀 Acme was founded in 2015, has no competitors, and generates $50 billion annually.';
  await page.getByLabel('AI response', { exact: true }).fill(source);
  await page.getByRole('button', { name: 'Verify Response' }).click();
  await expect(page.getByText('3 statements.')).toBeVisible();
  await expect(page.getByText('None investigated yet.')).toBeVisible();
  await expect(page.getByLabel('Response with highlighted claims')).toContainText('🚀 Acme was founded in 2015');
  await page.getByRole('button', { name: 'Inspect c2: has no competitors' }).click();
  await expect(page.locator('blockquote')).toHaveText('has no competitors');
  await expect(page.getByText('No evidence retrieved', { exact: true })).toBeVisible();
  await expect(page.getByText('Sycophancy has not run in this report; the existing /score service remains separate.')).toBeVisible();
  const jsonDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'JSON', exact: true }).click();
  expect((await jsonDownload).suggestedFilename()).toBe('trustlayer-extraction.json');
  const reportDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Readable report', exact: true }).click();
  expect((await reportDownload).suggestedFilename()).toBe('trustlayer-extraction.txt');
  await page.getByRole('button', { name: 'Compose', exact: true }).click();
  await page.getByLabel('AI response', { exact: true }).fill('An edited response.');
  await expect(page.getByText(/Inputs changed/)).toBeVisible();
});

test('missing access and provider failures cannot appear as success', async ({ page }) => {
  await page.goto('/workbench/');
  await page.getByRole('button', { name: 'Load startup example' }).click();
  await page.getByRole('button', { name: 'Verify Response' }).click();
  await expect(page.getByRole('alert')).toContainText('TrustLayer key');
  await connect(page);
  await page.route('**/v1/claims/extract', route => route.fulfill({ status: 503, json: { detail: 'fixture outage' } }));
  await page.getByRole('button', { name: 'Verify Response' }).click();
  await expect(page.getByRole('alert')).toContainText('No verification was completed');
  await expect(page.getByText('None investigated yet.')).toHaveCount(0);
});

test('malformed response and timeout cancellation stay visible', async ({ page }) => {
  await page.goto('/workbench/');
  await connect(page);
  await page.getByRole('button', { name: 'Load startup example' }).click();
  await page.route('**/v1/claims/extract', route => route.fulfill({ json: { claims: [{ verification_status: 'SUPPORTED' }] } }));
  await page.getByRole('button', { name: 'Verify Response' }).click();
  await expect(page.getByRole('alert')).toContainText('invalid report');
  await page.unroute('**/v1/claims/extract');
  await page.route('**/v1/claims/extract', async route => { await new Promise(resolve => setTimeout(resolve, 1200)); await route.abort(); });
  await page.getByRole('button', { name: 'Verify Response' }).click();
  await page.getByRole('button', { name: 'Cancel request' }).click();
  await expect(page.getByRole('alert')).toContainText('cancelled or timed out');
});

test('mobile, reduced motion, deep limitations and safe untrusted text', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/workbench/');
  await connect(page);
  await page.getByLabel('AI response', { exact: true }).fill('Acme has no competitors. <script>alert("unsafe")</script>');
  await page.getByRole('radio', { name: /Deep Investigation/ }).check();
  await expect(page.getByText(/Deep research is not available yet/)).toBeVisible();
  await page.getByRole('button', { name: 'Verify Response' }).click();
  await expect(page.getByText('None investigated yet.')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await page.evaluate(() => document.querySelectorAll('script:not([src])').length)).toBe(0);
  expect(await page.evaluate(() => document.documentElement.classList.contains('lenis'))).toBe(false);
  await page.screenshot({ path: 'test-results/mobile-workbench.png', fullPage: true });
});

test('desktop visual smoke, keyboard access and empty results', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto('/workbench/');
  await page.getByRole('button', { name: 'Motion on' }).click();
  await page.screenshot({ path: 'test-results/desktop-workbench.png', fullPage: true });
  await connect(page);
  await page.getByLabel('AI response', { exact: true }).fill('What is revenue?');
  await page.getByRole('button', { name: 'Verify Response' }).click();
  await expect(page.getByText('0 statements.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'The verification report' })).toBeFocused();
  expect(errors).toEqual([]);
});
