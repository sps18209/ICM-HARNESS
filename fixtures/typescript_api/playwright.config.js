const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './browser', workers: 1, retries: 0, timeout: 15000,
  outputDir: '.harness/runtime/browser-results',
  reporter: [['junit', { outputFile: '.harness/runtime/browser.xml', includeProjectInTestName: true }]],
  use: { browserName: 'chromium', headless: true },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 800 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
});
