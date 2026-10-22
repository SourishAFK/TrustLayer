import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

test.use({ reducedMotion: 'reduce' });

const recording = (name: string) =>
  JSON.parse(readFileSync(new URL(`../src/pages/demo/recorded/${name}.json`, import.meta.url), 'utf8'));
const ndjson = (lines: unknown[]) => lines.map(line => JSON.stringify(line)).join('\n') + '\n';

async function fillLead(page: Page) {
  await page.getByLabel('Your name').fill('Asha Rao');
  await page.getByLabel('Work email').fill('asha@bank.example');
  await page.getByLabel('What should we check?').fill('Our loan bot answers fee questions.');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: /Get my free check/ }).click();
}

test('home sends each audience to its own tagged check page, and lists its sources', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 }))
    .toContainText("Catch your AI's mistakes before your customers, clients or a judge do.");
  for (const tag of ['product-teams', 'documents', 'support-bots']) {
    await expect(page.locator(`#${tag} a[href="/check/?for=${tag}"]`)).toHaveCount(1);
  }
  await expect(page.locator('#sources li')).toHaveCount(8);
  await expect(page.locator('#sources a').first()).toHaveAttribute('href', /^https:\/\//);
});

test('a sign-up is sent with its audience and where the visitor came from', async ({ page }) => {
  let body: Record<string, unknown> | undefined;
  await page.route('**/v1/leads', async route => {
    body = route.request().postDataJSON();
    await route.fulfill({ status: 201, json: { ok: true } });
  });
  await page.goto('/check/?for=support-bots&utm_source=linkedin');
  await expect(page.getByRole('tab', { name: 'Support bot' })).toHaveAttribute('aria-selected', 'true');
  await fillLead(page);
  await expect(page.getByRole('status')).toContainText("You're on the list");
  expect(body).toMatchObject({
    audience: 'support-bots', name: 'Asha Rao', email: 'asha@bank.example', consent: true, website: '',
    source: { page: '/check/?for=support-bots&utm_source=linkedin', utm_source: 'linkedin' },
  });
});

test('switching audience re-tags the sign-up but keeps the page the visitor arrived on', async ({ page }) => {
  let body: Record<string, unknown> | undefined;
  await page.route('**/v1/leads', async route => {
    body = route.request().postDataJSON();
    await route.fulfill({ status: 201, json: { ok: true } });
  });
  await page.goto('/check/?for=documents');
  await page.getByRole('tab', { name: 'AI product team' }).click();
  await expect(page).toHaveURL(/for=product-teams/);
  await fillLead(page);
  await expect(page.getByRole('status')).toBeVisible();
  expect(body).toMatchObject({ audience: 'product-teams', source: { page: '/check/?for=documents' } });
});

test('a refused sign-up explains itself and keeps what was typed', async ({ page }) => {
  await page.route('**/v1/leads', route => route.fulfill({ status: 429, json: { detail: 'slow down' } }));
  await page.goto('/check/');
  await fillLead(page);
  await expect(page.getByRole('alert')).toContainText('Too many sign-ups');
  await expect(page.getByLabel('Your name')).toHaveValue('Asha Rao');
});

test('the demo streams a check and shows each verdict with its proof', async ({ page }) => {
  await page.route('**/v1/demo/verify/stream', route =>
    route.fulfill({ status: 200, contentType: 'application/x-ndjson', body: ndjson(recording('answer').lines) }));
  await page.goto('/demo/?preset=answer');
  await page.getByRole('button', { name: /Check it/ }).click();
  await expect(page.locator('.claim-card').first()).toContainText('Contradicted');
  await expect(page.getByText('12 × 20 = 240', { exact: false }).first()).toBeVisible();
  await expect(page.getByText(/Showing a recorded run/)).toHaveCount(0);
});

test('when the live demo is off, a clearly labelled recording plays instead', async ({ page }) => {
  await page.route('**/v1/demo/verify/stream', route => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/demo/?preset=support');
  await page.getByRole('button', { name: /Check it/ }).click();
  await expect(page.getByText(/switched off right now\. Showing a recorded run/)).toBeVisible();
  await expect(page.locator('.claim-card').first()).toBeVisible({ timeout: 15_000 });
});

test('an edited answer never gets a recording passed off as its result', async ({ page }) => {
  await page.route('**/v1/demo/verify/stream', route => route.fulfill({ status: 404, json: { detail: 'Not Found' } }));
  await page.goto('/demo/?preset=answer');
  await page.getByLabel('AI answer').fill('The moon is made of cheese.');
  await page.getByRole('button', { name: /Check it/ }).click();
  await expect(page.getByRole('alert')).toContainText('switched off');
  await expect(page.locator('.claim-card')).toHaveCount(0);
});

test('the sample report says it is a sample and prints as a plain document', async ({ page }) => {
  await page.goto('/report/sample/');
  await expect(page.getByText(/Acme Finance is fictional/).first()).toBeVisible();
  await expect(page.getByText('not a compliance certification', { exact: false })).toBeVisible();
  await page.emulateMedia({ media: 'print' });
  await expect(page.locator('.toolbar')).toBeHidden();
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeHidden();
  await expect(page.getByRole('heading', { name: 'Every wrong answer, with proof' })).toBeVisible();
});

test('with motion on, the intro curtain lifts and the headline stays readable', async ({ browser }) => {
  const page = await browser.newPage({ reducedMotion: 'no-preference' });
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect.poll(() => page.evaluate(() => [...document.querySelectorAll('.half-top')]
    .every(el => el.getBoundingClientRect().bottom <= 0 || getComputedStyle(el.parentElement!).display === 'none')),
  { timeout: 8000 }).toBe(true);
  await page.close();
});

test('no text runs off the side of a phone screen', async ({ browser }) => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
  await page.route('**/v1/demo/verify/stream', route =>
    route.fulfill({ status: 200, contentType: 'application/x-ndjson', body: ndjson(recording('document').lines) }));
  const offscreen = () => page.evaluate(() =>
    [...document.querySelectorAll('main :is(p, h1, h2, h3, li, button, input, textarea, blockquote)')]
      .filter(el => !el.closest('[aria-hidden="true"], .marquee-wrap') && el.getBoundingClientRect().width > 0)
      .filter(el => el.getBoundingClientRect().right > window.innerWidth + 1 || el.getBoundingClientRect().left < -1)
      .map(el => (el.textContent ?? '').trim().slice(0, 50)));
  for (const path of ['/', '/check/', '/report/sample/', '/demo/?preset=document']) {
    await page.goto(path);
    if (path.startsWith('/demo')) {
      await page.getByRole('button', { name: /Check it/ }).click();
      await expect(page.locator('.claim-card').first()).toBeVisible();
    }
    expect(await offscreen(), path).toEqual([]);
  }
  await page.close();
});
