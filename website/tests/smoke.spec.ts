import {expect, test} from '@playwright/test';

test.describe('the static documentation artifact', () => {
  let browserProblems: string[];

  test.beforeEach(async ({page}) => {
    browserProblems = [];
    page.on('console', (message) => {
      if (message.type() === 'error') browserProblems.push(`console: ${message.text()}`);
    });
    page.on('pageerror', (error) => browserProblems.push(`pageerror: ${error.message}`));
  });

  test.afterEach(() => expect(browserProblems).toEqual([]));

  test('navigates SDK and shared documentation, changes theme, and renders converted content', async ({page}) => {
    await page.goto('/');
    await page.locator('.navbar').getByRole('link', {name: 'Python SDK', exact: true}).click();
    await expect(page).toHaveURL(/\/python\/$/);
    await expect(page.locator('.navbar .anyinfer-sdk-version')).toHaveCount(1);
    await expect(page.locator('.theme-doc-version-badge')).toContainText('Python');
    await page.locator('.navbar').getByRole('link', {name: 'C# SDK', exact: true}).click();
    await expect(page).toHaveURL(/\/csharp\/$/);
    await expect(page.locator('.theme-doc-version-badge')).toContainText('prerelease');

    await page.goto('/concepts/budgeting/');
    await expect(page.getByRole('link', {name: 'Shared Foundation'}).first()).toBeVisible();
    await expect(page.locator('.docusaurus-mermaid-container svg')).toBeVisible();
    await page.goto('/python/quickstart/');
    await expect(page.getByRole('link', {name: 'Edit this page'})).toHaveAttribute(
      'href', 'https://github.com/anthturner/AnyInfer/edit/main/docs/guides/quickstart.md',
    );
    await page.getByRole('tab', {name: 'Async', exact: true}).click();
    await expect(page.getByRole('tabpanel').locator('pre')).toContainText('async with ai.AsyncClient');
    await expect(page.getByText('Key Takeaways')).toBeVisible();

    await page.goto('/downloads/');
    await expect(page.locator('.anyinfer-card-grid')).toHaveCSS('display', 'grid');
    await page.goto('/reference/errors/');
    await expect(page.locator('.anyinfer-error-card').first()).toBeVisible();
    await expect(page.locator('.anyinfer-error-card pre').first()).toBeVisible();

    await page.goto('/');
    const html = page.locator('html');
    const initialTheme = await html.getAttribute('data-theme');
    await page.getByRole('button', {name: /switch between dark and light mode/i}).click();
    await expect(html).not.toHaveAttribute('data-theme', initialTheme ?? '');
  });

  test('searches the local Pagefind index within SDK scopes', async ({page}) => {
    await page.goto('/');
    const manifestResponse = await page.request.get('/docs-manifest.json');
    expect(manifestResponse.ok()).toBeTruthy();
    const manifest = await manifestResponse.json() as {versions: {python: string; csharp: string}};
    const search = page.getByRole('searchbox', {name: 'Search documentation'});
    const scope = page.getByLabel('SDK scope');

    await scope.selectOption('python');
    await search.fill('anyinfer.AsyncClient');
    const pythonResult = page.locator('.anyinfer-search__results a[href^="/python/"]').first();
    await expect(pythonResult).toBeVisible();
    await expect(page.locator('.anyinfer-search__scope').first()).toContainText(
      `python ${manifest.versions.python}`,
      {ignoreCase: true},
    );

    await scope.selectOption('csharp');
    await search.fill('AnyInferConfig.Loads');
    const csharpResult = page.locator('.anyinfer-search__results a[href^="/csharp/"]').first();
    await expect(csharpResult).toBeVisible();
    await expect(page.locator('.anyinfer-search__scope').first()).toContainText(
      `csharp ${manifest.versions.csharp}`,
      {ignoreCase: true},
    );

    await scope.selectOption('shared');
    await search.fill('Token Estimation and Context Budgets');
    await expect(page.locator('.anyinfer-search__results a[href="/concepts/budgeting/"]')).toBeVisible();
    await page.locator('.anyinfer-search__results a').first().focus();
    await page.keyboard.press('Escape');
    await expect(page.locator('.anyinfer-search__results')).toBeHidden();
    await expect(search).toBeFocused();
    await search.fill('AnyInfer');
    await expect(page.locator('.anyinfer-search__results a').first()).toBeVisible();
    await page.locator('main').click({position: {x: 10, y: 10}});
    await expect(page.locator('.anyinfer-search__results')).toBeHidden();
  });

  test('serves the brand typefaces itself and requests nothing off-site', async ({page}) => {
    const offsite: string[] = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (url.protocol !== 'data:' && url.hostname !== '127.0.0.1') offsite.push(request.url());
    });
    await page.goto('/python/quickstart/');
    await page.evaluate(() => document.fonts.ready);
    const loaded = await page.evaluate(() => [...document.fonts]
      .filter((font) => font.status === 'loaded')
      .map((font) => `${font.family.replace(/["']/g, '')} ${font.weight}`));
    expect(loaded).toEqual(expect.arrayContaining(['Inter 400', 'Space Grotesk 600', 'JetBrains Mono 400']));
    expect(offsite).toEqual([]);
  });

  test('keeps a legacy API fragment when the static redirect moves the route', async ({page}) => {
    await page.goto('/reference/api/client/#client');
    await expect(page).toHaveURL(/\/python\/api\/client\/#client$/);
  });

  test('offers a native C# documentation path from the homepage', async ({page}) => {
    await page.goto('/');
    const teaser = page.locator('.anyinfer-code-teaser');
    await teaser.getByRole('tab', {name: 'C# (prerelease)', exact: true}).click();
    await expect(teaser.getByRole('tabpanel')).toContainText('GenerateAsync');
    await expect(page.getByRole('heading', {name: 'Python runtime capabilities', exact: true})).toBeVisible();
    await page.locator('main').getByRole('link', {name: 'C# SDK (prerelease)', exact: true}).click();
    await expect(page).toHaveURL(/\/csharp\/$/);
    const application = page.getByRole('heading', {name: /^Use in a \.NET application/});
    await expect(application).toBeAttached();
    await page.goto('/csharp/#use-in-a-net-application');
    await expect(page.locator('.theme-doc-markdown')).toContainText('dotnet add');
    await expect(page.locator('.theme-doc-markdown')).toContainText('not published to NuGet');
  });

  test('keeps navigation and local search usable on a mobile viewport', async ({page}) => {
    await page.setViewportSize({width: 390, height: 844});
    await page.goto('/');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.locator('.navbar__toggle').click();
    expect((await page.locator('.navbar-sidebar').boundingBox())!.height).toBeGreaterThanOrEqual(844);
    await expect(page.locator('.navbar-sidebar').getByRole('link', {name: 'Python SDK', exact: true})).toBeVisible();
    await page.getByRole('button', {name: 'Close navigation bar'}).click();

    const search = page.getByRole('searchbox', {name: 'Search documentation'});
    await expect(search).toBeVisible();
    await search.fill('AnyInfer');
    await expect(page.locator('.anyinfer-search__results a').first()).toBeVisible();

    await page.goto('/python/quickstart/');
    await page.locator('.navbar__toggle').click();
    expect((await page.locator('.navbar-sidebar').boundingBox())!.height).toBeGreaterThanOrEqual(844);
    await expect(page.locator('.navbar-sidebar').getByRole('link', {name: 'Installation and Extras', exact: true})).toBeVisible();
  });

  test('gives each download option enough room for commands and platform choices', async ({page}) => {
    for (const width of [320, 390, 768, 1024, 1440]) {
      await page.setViewportSize({width, height: 1000});
      await page.goto('/downloads/');
      const cards = page.locator('.anyinfer-download-grid > .anyinfer-download-card');
      await expect(cards).toHaveCount(3);
      await expect(page.locator('.theme-doc-toc-desktop')).toHaveCount(0);
      let previousBottom = 0;
      for (const card of await cards.all()) {
        const box = (await card.boundingBox())!;
        expect(box.width).toBeGreaterThan(Math.min(width - 100, 850));
        expect(box.y).toBeGreaterThan(previousBottom);
        previousBottom = box.y + box.height;
      }
      for (const platforms of await page.locator('.anyinfer-platforms').all()) {
        await expect(platforms.getByRole('link')).toHaveCount(5);
        for (const link of await platforms.getByRole('link').all()) {
          const box = (await link.boundingBox())!;
          expect(box.x).toBeGreaterThanOrEqual(0);
          expect(box.x + box.width).toBeLessThanOrEqual(width);
        }
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      if (width < 600) {
        const logo = (await page.locator('.navbar__inner .navbar__logo').boundingBox())!;
        const search = (await page.getByRole('searchbox').boundingBox())!;
        expect(logo.x + logo.width).toBeLessThan(search.x);
      }
    }
  });

  test('contains wide reference content and respects an explicit light theme on a dark system', async ({page}) => {
    await page.emulateMedia({colorScheme: 'dark', reducedMotion: 'reduce'});
    await page.addInitScript(() => localStorage.setItem('theme', 'light'));
    for (const width of [390, 768, 1024]) {
      await page.setViewportSize({width, height: 844});
      for (const route of ['/', '/python/quickstart/', '/python/api/client/', '/csharp/', '/providers/all/', '/reference/conformance-matrix/', '/reference/errors/']) {
        await page.goto(route);
        await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
        await expect(page.locator('body')).toHaveCSS('background-color', 'rgb(255, 255, 255)');
        if (width === 1024 && route === '/python/quickstart/') {
          await expect(page.locator('.theme-doc-toc-desktop')).toBeHidden();
          await expect(page.locator('.theme-doc-toc-mobile')).toBeVisible();
          expect((await page.locator('.theme-doc-markdown').boundingBox())!.width).toBeGreaterThan(650);
        }
        if (route === '/') {
          await expect(page.getByRole('heading', {level: 1})).toHaveCount(1);
          await expect(page.locator('.anyinfer-code-teaser .theme-code-block')).toHaveCount(3);
          await expect(page.locator('.grid.cards')).toHaveCSS('display', 'grid');
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth), `${width}: ${route}`).toBeLessThanOrEqual(width);
      }
    }
  });
});
