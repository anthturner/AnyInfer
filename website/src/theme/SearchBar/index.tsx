import {useEffect, useId, useRef, useState, type JSX} from 'react';

import useBaseUrl from '@docusaurus/useBaseUrl';

type PagefindResult = {
  data: () => Promise<{
    url: string;
    meta: {title?: string; sdk?: string; version?: string};
    excerpt?: string;
  }>;
};
type SearchResult = {url: string; title: string; excerpt?: string; sdk?: string; version?: string};
type Pagefind = {
  search: (query: string, options?: {filters?: Record<string, string>}) => Promise<{results: PagefindResult[]}>;
};

/** A browser-only adapter for the Pagefind bundle generated from the final static site. */
export default function SearchBar(): JSX.Element {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [sdk, setSdk] = useState('all');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [state, setState] = useState<'idle' | 'loading' | 'empty' | 'error'>('idle');
  const inputId = useId();
  const container = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const pagefindUrl = useBaseUrl('pagefind/pagefind.js');

  useEffect(() => {
    function dismiss(event: PointerEvent): void {
      if (event.target instanceof Node && !container.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, []);

  useEffect(() => {
    if (!query.trim()) { setResults([]); setState('idle'); return; }
    let active = true;
    setState('loading');
    void import(/* webpackIgnore: true */ pagefindUrl).then(async (module: Pagefind) => {
      const response = await module.search(query, {
        filters: sdk === 'all' ? undefined : {sdk},
      });
      const pages = await Promise.all(response.results.slice(0, 8).map(async (result) => {
        const data = await result.data();
        return {
          url: data.url,
          title: data.meta.title ?? data.url,
          excerpt: data.excerpt,
          sdk: data.meta.sdk,
          version: data.meta.version,
        };
      }));
      if (active) {
        setResults(pages);
        setState(pages.length ? 'idle' : 'empty');
      }
    }).catch(() => {
      if (active) { setResults([]); setState('error'); }
    });
    return () => { active = false; };
  }, [pagefindUrl, query, sdk]);

  function close(): void {
    setOpen(false);
  }

  return <div ref={container} className="anyinfer-search" role="search" aria-label="Documentation search"
    onFocus={() => setOpen(true)}
    onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) close();
    }} onKeyDown={(event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      input.current?.focus();
      close();
    }
  }}>
    <label className="sr-only" htmlFor={inputId}>Search documentation</label>
    <input ref={input} id={inputId} type="search" placeholder="Search docs…" value={query} autoComplete="off"
      aria-expanded={Boolean(query) && open} aria-controls={`${inputId}-results`}
      onChange={(event) => { setQuery(event.target.value); setOpen(true); }} />
    <label className="sr-only" htmlFor={`${inputId}-sdk`}>SDK scope</label>
    <select id={`${inputId}-sdk`} value={sdk} onChange={(event) => setSdk(event.target.value)}>
      <option value="all">All SDKs</option><option value="shared">Shared</option>
      <option value="python">Python</option><option value="csharp">C#</option>
    </select>
    {query && open && <div id={`${inputId}-results`} className="anyinfer-search__results">
      <div role="status" aria-live="polite">
      {state === 'loading' && <p>Searching local documentation…</p>}
      {state === 'empty' && <p>No matching pages.</p>}
      {state === 'error' && <p>Search index is unavailable.</p>}
      {state === 'idle' && results.length > 0 && <p className="sr-only">{results.length} matching pages.</p>}
      </div>
      {results.length > 0 && <ul>
      {results.map((result) => <li key={result.url}><a href={result.url} onClick={close}>
        <span className="anyinfer-search__title">{result.title}</span>
        {(result.sdk || result.version) && <span className="anyinfer-search__scope">
          {[result.sdk, result.version].filter(Boolean).join(' ')}
        </span>}
        {result.excerpt && <small dangerouslySetInnerHTML={{__html: result.excerpt}} />}</a></li>)}
      </ul>}
    </div>}
  </div>;
}
