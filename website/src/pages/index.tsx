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
    'Encrypted templates, a caller-operated relay, and attestation-readiness detection, with explicit guarantees and limits.',
    '/guides/confidentiality-tiers/',
  ],
] as const;

export default function Home(): ReactNode {
  return (
    <Layout>
      <main className={styles.home}>
        <section className={styles.hero}>
          <div className={styles.heroCopy}>
            <span className={styles.eyebrow}>Application-owned hybrid inference</span>
            <h1 className={styles.wordmark}>
              <img className={styles.onLight} src="/assets/anyinfer-wordmark-on-light.svg" alt="AnyInfer" width="671" height="200" />
              <img className={styles.onDark} src="/assets/anyinfer-wordmark-on-dark.svg" alt="AnyInfer" width="671" height="200" />
            </h1>
            <p className={styles.lead}>One typed inference layer for hosted APIs and supervised local models — with a test
              kit for your failure paths, provenance-tagged capabilities, and explicit
              confidentiality controls.</p>
            <div className={styles.actions}>
              <a className="anyinfer-button anyinfer-button-primary" href="/python/quickstart/">Python quickstart</a>
              <a className="anyinfer-button anyinfer-button-secondary" href="/csharp/">C# SDK (prerelease)</a>
              <a className="anyinfer-button anyinfer-button-text" href="/downloads/">Downloads</a>
            </div>
            <div className={styles.diagram} aria-hidden="true">
              <span>approved context</span><b>→</b><span>budget + route</span><b>→</b><span>cloud or local</span>
            </div>
          </div>
          <div className={styles.heroMark} aria-hidden="true">
            <img className={styles.onLight} src="/assets/anyinfer-icon-512.svg" alt="" width="512" height="512" />
            <img className={styles.onDark} src="/assets/anyinfer-mark-on-dark.svg" alt="" width="512" height="512" />
          </div>
        </section>
        <section className={styles.capabilities} aria-labelledby="runtime-capabilities">
          <div className={styles.featureHeading}>
            <h2 id="runtime-capabilities">Python runtime capabilities</h2>
            <a className="anyinfer-button anyinfer-button-text" href="/concepts/foundation/#c-capability-map">C# capability map</a>
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
          <a className="anyinfer-sdk-badge anyinfer-sdk-badge--python" href="/python/">Python 3.11+ · v{manifest.versions.python}</a>
          <a className="anyinfer-sdk-badge anyinfer-sdk-badge--csharp" href="/csharp/">C# .NET 8 · v{manifest.versions.csharp} · prerelease</a>
          <a className="anyinfer-button anyinfer-button-text" href="/reference/conformance-matrix/">Python conformance matrix</a>
        </section>
      </main>
    </Layout>
  );
}
