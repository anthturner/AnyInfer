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

const config: Config = {
  title: 'AnyInfer',
  tagline: 'Application-owned hybrid inference',
  favicon: 'assets/anyinfer-icon-512.png',
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
      {property: 'og:image', content: 'https://anyinfer.dev/assets/anyinfer-social-card.png'},
    ],
    navbar: {
      logo: {
        alt: 'AnyInfer home',
        src: 'assets/anyinfer-horizontal-light.svg',
        srcDark: 'assets/anyinfer-horizontal-dark.svg',
        width: 148,
        height: 29,
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

function codeTheme(dark: boolean): PrismTheme {
  return {
    plain: {color: dark ? '#f0f6fc' : '#0b3b3c', backgroundColor: dark ? '#151b23' : '#f6f8fa'},
    styles: [
      {types: ['comment', 'prolog', 'doctype', 'cdata'], style: {color: dark ? '#9198a1' : '#59636e'}},
      {types: ['keyword', 'selector', 'tag', 'builtin'], style: {color: dark ? '#4fbfa8' : '#1f6f63'}},
      {types: ['string', 'char', 'attr-value', 'regex'], style: {color: dark ? '#f0c86a' : '#805015'}},
      {types: ['function', 'class-name', 'attr-name'], style: {color: dark ? '#7fd8c4' : '#2c7a6f'}},
      {types: ['number', 'boolean', 'constant', 'symbol'], style: {color: dark ? '#e8963c' : '#805015'}},
      {types: ['operator', 'punctuation'], style: {color: dark ? '#bdcbd0' : '#59636e'}},
    ],
  };
}

export default config;
