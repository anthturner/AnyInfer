import type {ReactNode} from 'react';
import {MDXProvider} from '@mdx-js/react';

import Layout from '@theme/Layout';
import MDXContent from '@theme/MDXContent';
import HomeContent from '../../.generated/home.mdx';
import manifest from '../../.generated/manifest.json';

import styles from './index.module.css';

const features = [
  [
    'Typed events',
    'A generation is an ordered stream of typed events; non-streaming is just the drained stream.',
    '/concepts/events/',
  ],
  [
    'Routing & fallback',
    'Deterministic retries, failure-specific fallback chains, and health gating — fully traceable after the fact.',
    '/concepts/routing/',
  ],
  [
    'Local inference',
    'Hardware detection, tuning, verified downloads, and supervised llama-server — one target string.',
    '/concepts/local/',
  ],
  [
    'Structured output',
    'A schema is a contract: strongest native mechanism, always client-side validated, optional bounded repair.',
    '/concepts/structured-output/',
  ],
  [
    'Context budgets',
    'Estimate fit and cost before dispatch, then reduce approved context with an explicit record of what was omitted.',
    '/concepts/budgeting/',
  ],
  [
    'Confidentiality tiers',
    'Encrypted-at-rest templates, zero-retention orchestration, and one function that tells you if a box can run a model under hardware attestation — honestly tiered, nowhere else.',
    '/guides/confidentiality-tiers/',
  ],
] as const;

export default function Home(): ReactNode {
  return (
    <Layout>
      <main className={styles.home}>
        <section className={styles.hero}>
          <div className={styles.heroMark}>
            <span className={styles.eyebrow}>Application-owned hybrid inference</span>
            <h1 className={styles.wordmark}>
              <img className={styles.wordmarkLight} src="/assets/anyinfer-horizontal-light.svg" alt="AnyInfer" width="440" />
              <img className={styles.wordmarkDark} src="/assets/anyinfer-horizontal-dark.svg" alt="AnyInfer" width="440" />
            </h1>
          </div>
          <p>One typed inference layer for hosted APIs and a supervised local model — with a test
            kit for your failure paths, provenance on every number, and a confidentiality story
            no other BYOK library ships.</p>
          <div className={styles.actions}>
            <a className="button button--primary" href="/python/quickstart/">Python quickstart</a>
            <a className="button button--secondary" href="/csharp/">C# SDK (prerelease)</a>
            <a className="button button--secondary" href="/downloads/">Downloads</a>
          </div>
          <div className={styles.diagram} aria-hidden="true">
            <span>approved context</span><b>→</b><span>budget + route</span><b>→</b><span>cloud or local</span>
          </div>
        </section>
        <section aria-labelledby="runtime-capabilities">
          <div className={styles.featureHeading}>
            <h2 id="runtime-capabilities">Python runtime capabilities</h2>
            <a href="/concepts/foundation/#c-capability-map">C# capability map →</a>
          </div>
          <div className={styles.features}>
            {features.map(([title, text, href], index) => (
              <a href={href} key={title} className={styles.card}>
                <span className={styles.cardNumber} aria-hidden="true">0{index + 1}</span>
                <h3>{title}</h3><p>{text}</p>
              </a>
            ))}
          </div>
        </section>
        <article className="markdown">
          <MDXContent>
            <MDXProvider components={{h1: () => null}}><HomeContent /></MDXProvider>
          </MDXContent>
        </article>
        <section className={styles.footer}>
          <a className={styles.badge} href="/python/">Python 3.11+ · v{manifest.versions.python}</a>
          <a className={styles.badge} href="/csharp/">C# .NET 8 · v{manifest.versions.csharp} · prerelease</a>
          <a href="/reference/conformance-matrix/">Python conformance matrix →</a>
        </section>
      </main>
    </Layout>
  );
}
