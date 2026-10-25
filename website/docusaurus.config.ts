import type {Config} from '@docusaurus/types';
import type {Options as DocsOptions} from '@docusaurus/plugin-content-docs';
import {existsSync, readFileSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import type {PrismTheme} from 'prism-react-renderer';

import {sidebarFromManifest} from './plugins/sidebars';

const manifestPath = new URL('./.generated/manifest.json', import.meta.url);
const sourceManifest = existsSync(manifestPath)
  ? JSON.parse(readFileSync(manifestPath, 'utf8')) as {versions?: Record<string, string>}
  : {};

/** Versions archived by `scripts/build_docs.py snapshot`, newest first; each SDK has its own. */
function archivedVersions(id: 'python' | 'csharp'): string[] {
  const file = new URL(`./${id}_versions.json`, import.meta.url);
  return existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) as string[] : [];
}

function docsInstance(
  id: 'shared' | 'python' | 'csharp',
  routeBasePath: string,
  versionLabel?: string,
): [string, DocsOptions] {
  const language = id === 'python' ? 'Python' : 'C#';
  return [
    '@docusaurus/plugin-content-docs',
    {
      id,
      path: `.generated/${id}`,
      routeBasePath,
      sidebarPath: './sidebars.json',
      ...(id === 'shared'
        ? {}
        : {
            lastVersion: 'current',
            versions: {
              current: {path: '', label: versionLabel ?? 'Current', badge: true},
              ...Object.fromEntries(archivedVersions(id).map((name) => [
                name, {label: `${language} ${name}`, banner: 'unmaintained' as const, badge: true},
              ])),
            },
          }),
      async sidebarItemsGenerator({docs, version}) {
        // An archived version keeps the navigation and pages it was published with.
        const source = version.versionName === 'current'
          ? manifestPath
          : join(version.contentPath, 'manifest.json');
        const manifest = JSON.parse(await readFile(source, 'utf8'));
        return sidebarFromManifest(manifest, id).filter((item) => {
          if (item.type !== 'doc') return true;
          return docs.some((doc) => doc.id === item.id);
        });
      },
      editUrl: ({docPath, version}) => version === 'current'
        ? `https://github.com/anthturner/AnyInfer/edit/main/docs/${docPath.replace(/\.mdx$/, '.md')}`
        : undefined,
    },
  ];
}

const socialCardAlt = 'AnyInfer: Any model. Any provider. Expertise built in.';

const config: Config = {
  title: 'AnyInfer',
  tagline: 'Application-owned hybrid inference',
  favicon: 'assets/favicon.ico',
  url: 'https://anyinfer.dev',
  baseUrl: '/',
  trailingSlash: true,
  organizationName: 'anthturner',
  projectName: 'AnyInfer',
  deploymentBranch: 'gh-pages',
  onBrokenLinks: 'throw',
  // The final HTML validator checks raw symbol anchors, which this Markdown-level
  // checker cannot see. Both the workspace gate and Pages build run that validator.
  onBrokenAnchors: 'ignore',
  markdown: {format: 'detect', mermaid: true, hooks: {onBrokenMarkdownLinks: 'throw'}},
  staticDirectories: ['static', '.generated/static'],
  // Brand typefaces are bundled from exact-pinned @fontsource packages: no font CDN.
  clientModules: ['./src/fonts.ts'],
  // The brand kit's favicon set: the 16 and 24 px images use the simple mark, which
  // drops the provider ports that would blur at that size.
  headTags: [
    {tagName: 'link', attributes: {rel: 'icon', type: 'image/png', sizes: '16x16', href: '/assets/favicon-16.png'}},
    {tagName: 'link', attributes: {rel: 'icon', type: 'image/png', sizes: '32x32', href: '/assets/favicon-32.png'}},
    {tagName: 'link', attributes: {rel: 'icon', type: 'image/png', sizes: '48x48', href: '/assets/favicon-48.png'}},
    {tagName: 'link', attributes: {rel: 'apple-touch-icon', sizes: '180x180', href: '/assets/anyinfer-app-icon-light-180.png'}},
  ],
  presets: [
    [
      'classic',
      {
        docs: false,
        blog: false,
        theme: {customCss: './src/css/custom.css'},
      },
    ],
  ],
  plugins: [
    docsInstance('shared', '/'),
    docsInstance('python', 'python', `Python ${sourceManifest.versions?.python ?? 'current'}`),
    docsInstance('csharp', 'csharp', `C# ${sourceManifest.versions?.csharp ?? 'current'} (prerelease)`),
  ],
  themes: ['@docusaurus/theme-mermaid'],
  themeConfig: {
    docs: {sidebar: {autoCollapseCategories: true}},
    image: 'assets/anyinfer-social-card.png',
    metadata: [
      {name: 'twitter:card', content: 'summary_large_image'},
      {name: 'twitter:image', content: 'https://anyinfer.dev/assets/anyinfer-social-card.png'},
      {name: 'twitter:image:alt', content: socialCardAlt},
      {property: 'og:image', content: 'https://anyinfer.dev/assets/anyinfer-social-card.png'},
      {property: 'og:image:width', content: '1200'},
      {property: 'og:image:height', content: '630'},
      {property: 'og:image:alt', content: socialCardAlt},
      {name: 'theme-color', content: '#FFFFFF', media: '(prefers-color-scheme: light)'},
      {name: 'theme-color', content: '#0A1A1B', media: '(prefers-color-scheme: dark)'},
    ],
    navbar: {
      logo: {
        alt: 'AnyInfer home',
        src: 'assets/anyinfer-horizontal-light.svg',
        srcDark: 'assets/anyinfer-horizontal-dark.svg',
        // The lockup's minimum is 24 px tall; 32 px keeps the name legible in the bar.
        width: 140,
        height: 32,
      },
      items: [
        {to: '/python/', label: 'Python SDK', position: 'left'},
        {to: '/csharp/', label: 'C# SDK', position: 'left'},
        {to: '/downloads/', label: 'Downloads', position: 'left'},
        {type: 'custom-activeSdkVersion', position: 'right'},
        {href: 'https://github.com/anthturner/AnyInfer', label: 'GitHub', position: 'right'},
      ],
    },
    footer: {
      style: 'dark',
      // The footer is the brand's ink ground in both themes, so it always takes the
      // on-dark lockup.
      logo: {
        alt: 'AnyInfer',
        src: 'assets/anyinfer-horizontal-dark.svg',
        srcDark: 'assets/anyinfer-horizontal-dark.svg',
        href: '/',
        width: 122,
        height: 28,
      },
      links: [
        {title: 'Documentation', items: [
          {label: 'Quickstart', to: '/python/quickstart/'},
          {label: 'Shared foundation', to: '/concepts/foundation/'},
          {label: 'Provider guides', to: '/providers/'},
        ]},
        {title: 'SDKs & downloads', items: [
          {label: 'Python SDK', to: '/python/'},
          {label: 'C# SDK (prerelease)', to: '/csharp/'},
          {label: 'Downloads', to: '/downloads/'},
        ]},
        {title: 'Project', items: [
          {label: 'GitHub', href: 'https://github.com/anthturner/AnyInfer'},
          {label: 'Releases', href: 'https://github.com/anthturner/AnyInfer/releases'},
          {label: 'Contributing', to: '/contributing/'},
        ]},
      ],
      copyright: `Copyright © ${new Date().getFullYear()} AnyInfer contributors.`,
    },
    prism: {theme: codeTheme(false), darkTheme: codeTheme(true), additionalLanguages: ['csharp']},
  },
};

/**
 * Brand code colors: keywords in the amber text tone, literals in the link teal, comments
 * muted, everything else in the body ink. Every token meets WCAG AA on the code surface.
 */
function codeTheme(dark: boolean): PrismTheme {
  const ink = dark
    ? {text: '#E8F0EE', surface: '#102627', muted: '#8FA6A4', signal: '#F5B266', literal: '#6FD0BA', danger: '#F07A6A', success: '#4CC38A'}
    : {text: '#0A1A1B', surface: '#F4F7F6', muted: '#4A6261', signal: '#9A5410', literal: '#24695F', danger: '#C0392B', success: '#1D7A4C'};
  return {
    plain: {color: ink.text, backgroundColor: ink.surface},
    styles: [
      {types: ['comment', 'prolog', 'doctype', 'cdata'], style: {color: ink.muted}},
      {types: ['keyword', 'builtin', 'selector', 'tag', 'atrule', 'important', 'decorator', 'annotation'], style: {color: ink.signal}},
      {types: ['string', 'char', 'attr-value', 'regex', 'url', 'number', 'boolean', 'constant', 'symbol'], style: {color: ink.literal}},
      {types: ['function', 'class-name', 'attr-name', 'property', 'namespace', 'variable', 'operator', 'punctuation'], style: {color: ink.text}},
      {types: ['deleted'], style: {color: ink.danger}},
      {types: ['inserted'], style: {color: ink.success}},
    ],
  };
}

export default config;
