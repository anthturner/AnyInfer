import type {ReactNode} from 'react';

import clsx from 'clsx';

import styles from './styles.module.css';

const sections = [
  ['Integrate', 'Python SDK, command-line tool, sidecar, and shared configuration.', '/guides/'],
  ['Concepts', 'The mental model: events, routing, capabilities, credentials, telemetry.', '/concepts/'],
  ['Providers', 'Setup and quirks for every provider.', '/providers/'],
  ['Sidecar', 'The OpenAI-compatible HTTP service for non-Python integrations.', '/serve/'],
  ['Reference', 'SDK reference, error catalog, conformance matrix, glossary.', '/reference/'],
  ['Contributing', 'Architecture, writing an adapter, testing, releases.', '/contributing/'],
] as const;

type Props = {className?: string};

/** Keeps broken links useful by preserving the site's existing 404 navigation choices. */
export default function NotFoundContent({className}: Props): ReactNode {
  return <main className={clsx('container margin-vert--xl', styles.notFound, className)}>
    <h1>Page not found</h1>
    <p>The page you were looking for doesn&apos;t exist, or moved. Use the search box in the
      header, or pick a section below.</p>
    <section className={styles.cards} aria-label="Documentation sections">
      {sections.map(([title, description, href]) => <a href={href} key={title} className={styles.card}>
        <h2>{title}</h2><p>{description}</p>
      </a>)}
    </section>
    <p><a href="/">← Back to the homepage</a></p>
  </main>;
}
