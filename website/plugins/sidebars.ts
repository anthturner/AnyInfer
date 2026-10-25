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

type Manifest = {
  navigation: NavigationNode[];
  pages: Page[];
};

function documentItem(page: Page): SidebarItemDoc {
  return {type: 'doc', id: page.id, label: page.title};
}

function itemsFor(
  nodes: NavigationNode[],
  pagesBySource: Map<string, Page>,
): SidebarItem[] {
  const items: SidebarItem[] = [];
  for (const node of nodes) {
    if (typeof node === 'string') {
      const page = pagesBySource.get(node);
      if (page) items.push(documentItem(page));
      continue;
    }
    for (const [label, value] of Object.entries(node)) {
      if (typeof value === 'string') {
        const page = pagesBySource.get(value);
        if (page) items.push({type: 'doc', id: page.id, label});
        continue;
      }
      const children = Array.isArray(value) ? value : [value];
      const nested = itemsFor(children, pagesBySource);
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
  return itemsFor(manifest.navigation, pages);
}
