const { test, expect } = require('@playwright/test');
const { once } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const { makeServer } = require('../.harness/runtime/build/server');

let server, base;
test.beforeAll(async () => {
  server = makeServer(); server.listen(0, '127.0.0.1');
  await once(server, 'listening'); base = `http://127.0.0.1:${server.address().port}`;
});
test.afterAll(async () => {
  if (server) {
    server.closeAllConnections();
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
});

test('save persists after reload', async ({ page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', entry => { if (entry.type() === 'error' || entry.type() === 'warning') errors.push(entry.text()); });
  const output = path.resolve('.harness/runtime/browser'); fs.mkdirSync(output, { recursive: true });
  await page.context().tracing.start({ screenshots: true, snapshots: true });
  try {
    await page.goto(base);
    await expect(page).toHaveURL(base + '/');
    await expect(page).toHaveTitle('ICM acceptance fixture');
    await expect(page.getByRole('heading', { name: 'Saved items' })).toBeVisible();
    await page.getByLabel('Item value').fill('Browser-saved item');
    await page.getByRole('button', { name: 'Save item' }).click();
    await expect(page.getByRole('status')).toHaveText('Saved');
    await expect(page.getByRole('listitem')).toHaveText('Browser-saved item');
    await page.reload();
    await expect(page.getByRole('listitem')).toHaveText('Browser-saved item');
    expect(await page.locator('body').evaluate(body => body.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  } finally {
    await page.screenshot({ path: path.join(output, testInfo.project.name + '.png'), fullPage: true });
    await page.context().tracing.stop({ path: path.join(output, testInfo.project.name + '.zip') });
  }
});
