import type {
  SidebarItem,
  SidebarItemCategory,
  SidebarItemDoc,
} from '@docusaurus/plugin-content-docs/lib/sidebars/types.js';

type Page = {
  source: string;
  sdk: string;
  id: string;
  title: string;
};

type NavigationNode = string | {readonly [label: string]: NavigationNode | NavigationNode[]};

type GeneratedSection = {
  sdk: string;
  label: string;
  index: string;
  namespaces: {label: string; items: {id: string; label: string}[]}[];
};

type Manifest = {
  navigation: NavigationNode[];
  pages: Page[];
  generated?: Record<string, GeneratedSection>;
};

const GENERATED_PREFIX = 'generated:';

function documentItem(page: Page): SidebarItemDoc {
  return {type: 'doc', id: page.id, label: page.title};
}

/** Expands a generated section, such as the C# API reference, into nested categories. */
function generatedItem(section: GeneratedSection, label: string): SidebarItemCategory {
  return {
    type: 'category',
    label,
    collapsed: true,
    collapsible: true,
    link: {type: 'doc', id: section.index},
    items: section.namespaces.map((namespace) => ({
      type: 'category',
      label: namespace.label,
      collapsed: true,
      collapsible: true,
      items: namespace.items.map(
        (item): SidebarItemDoc => ({type: 'doc', id: item.id, label: item.label}),
      ),
    }) satisfies SidebarItemCategory),
  };
}

function itemsFor(
  nodes: NavigationNode[],
  pagesBySource: Map<string, Page>,
  generated: Map<string, GeneratedSection>,
): SidebarItem[] {
  const items: SidebarItem[] = [];
  for (const node of nodes) {
    if (typeof node === 'string') {
      const page = pagesBySource.get(node);
      if (page) items.push(documentItem(page));
      continue;
    }
    for (const [label, value] of Object.entries(node)) {
      if (typeof value === 'string' && value.startsWith(GENERATED_PREFIX)) {
        const section = generated.get(value.slice(GENERATED_PREFIX.length));
        if (section) items.push(generatedItem(section, label));
        continue;
      }
      if (typeof value === 'string') {
        const page = pagesBySource.get(value);
        if (page) items.push({type: 'doc', id: page.id, label});
        continue;
      }
      const children = Array.isArray(value) ? value : [value];
      const nested = itemsFor(children, pagesBySource, generated);
      if (nested.length > 0) {
        items.push({
          type: 'category', label, collapsed: true, collapsible: true, items: nested,
        } satisfies SidebarItemCategory);
      }
    }
  }
  return items;
}

/** Builds each SDK sidebar from the one preserved MkDocs navigation source. */
export function sidebarFromManifest(manifest: Manifest, sdk: string): SidebarItem[] {
  const pages = new Map(
    manifest.pages
      .filter((page) => page.sdk === sdk && page.source !== 'index.md')
      .map((page) => [page.source, page]),
  );
  const generated = new Map(
    Object.entries(manifest.generated ?? {}).filter(([, section]) => section.sdk === sdk),
  );
  return itemsFor(manifest.navigation, pages, generated);
}
