import {expect, test} from '@playwright/test';

// Run against snapshots created only in an isolated acceptance checkout. A normal
// production build has no invented release history to exercise.
test.describe('independent SDK archive rehearsal', () => {
  test.skip(!process.env.DOCS_ARCHIVE_REHEARSAL, 'Requires the isolated snapshot rehearsal');

  test('keeps archived APIs, version links, search and exports tied to each SDK', async ({page}) => {
    const response = await page.request.get('/docs-manifest.json');
    expect(response.ok()).toBeTruthy();
    const manifest = await response.json() as {
      versions: Record<string, string>;
      archives: Record<string, {version: string; pages: {url: string}[]}[]>;
    };
    const browserErrors: string[] = [];
    page.on('pageerror', (error) => browserErrors.push(error.message));
    let checkedArchives = 0;

    for (const sdk of ['csharp', 'python']) {
      const archive = manifest.archives[sdk]?.[0];
      if (!archive) throw new Error(`The rehearsal is missing the ${sdk} archive`);
      checkedArchives += 1;
      const version = archive.version;
      const suffix = sdk === 'csharp' ? 'api/anyinfer.asyncclient/' : 'quickstart/';
      const current = `/${sdk}/${suffix}`;
      const historical = `/${sdk}/${version}/${suffix}`;
      expect(archive.pages.some((entry) => entry.url === historical)).toBeTruthy();

      await page.goto(current);
      const selector = page.locator('.navbar .anyinfer-sdk-version');
      await selector.hover();
      const historicalLink = page.locator(`.navbar .dropdown__menu a[href="${historical}"]`);
      await expect(historicalLink).toBeVisible();
      await historicalLink.click();
      await expect(page).toHaveURL(new RegExp(`${historical}$`));
      await expect(page.locator('.theme-doc-version-banner')).toBeVisible();
      await expect(page.locator('.theme-doc-markdown')).toContainText(
        sdk === 'csharp' ? 'GenerateAsync' : 'generate(',
      );

      // An archived reference's same-SDK links must keep the archived version.
      if (sdk === 'csharp') {
        const settings = page.locator(`.theme-doc-markdown a[href="/csharp/${version}/api/anyinfer.providersettings/"]`).first();
        await settings.click();
        await expect(page).toHaveURL(new RegExp(`/csharp/${version}/api/anyinfer.providersettings/$`));
      }
      await page.goto(`/${sdk}/${version}/`);
      await page.getByLabel('SDK scope').selectOption(sdk);
      await page.getByRole('searchbox', {name: 'Search documentation'}).fill(
        sdk === 'csharp' ? 'AsyncClient GenerateAsync' : 'Quickstart',
      );
      const hits = page.locator('.anyinfer-search__results a');
      await expect(hits.first()).toBeVisible();
      expect(await hits.evaluateAll((links) => links.map((link) => link.getAttribute('href'))))
        .toEqual(expect.arrayContaining([expect.stringContaining(`/${sdk}/${version}/`)]));

      // Reading another SDK uses that SDK's current history and metadata.
      const other = sdk === 'csharp' ? 'python' : 'csharp';
      await page.goto(`/${other}/`);
      await expect(page.locator('.navbar .anyinfer-sdk-version')).toContainText(manifest.versions[other]);
    }
    const exports = await page.request.get('/llms.txt');
    expect(exports.ok()).toBeTruthy();
    const text = await exports.text();
    const fullExport = await page.request.get('/llms-full.txt');
    expect(fullExport.ok()).toBeTruthy();
    const currentText = await fullExport.text();
    for (const [sdk, archives] of Object.entries(manifest.archives)) {
      for (const archive of archives) {
        expect(text).toContain(`/${sdk}/${archive.version}/`);
        expect(currentText).not.toContain(`https://anyinfer.dev/${sdk}/${archive.version}/`);
      }
    }
    expect(checkedArchives).toBe(2);
    expect(browserErrors).toEqual([]);
  });
});
