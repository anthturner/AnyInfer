import type {ReactNode} from 'react';
import {useActiveVersion, useVersions} from '@docusaurus/plugin-content-docs/client';
import DocsVersionDropdownNavbarItem from '@theme/NavbarItem/DocsVersionDropdownNavbarItem';

/** Keep version selection in the SDK being read, with independent version histories. */
export default function ActiveSdkVersion({mobile = false}: {mobile?: boolean}): ReactNode {
  const python = useActiveVersion('python');
  const csharp = useActiveVersion('csharp');
  const pythonVersions = useVersions('python');
  const csharpVersions = useVersions('csharp');
  const active = python ?? csharp;
  if (!active) return null;
  const versions = python ? pythonVersions : csharpVersions;
  return <DocsVersionDropdownNavbarItem
    docsPluginId={python ? 'python' : 'csharp'}
    mobile={mobile}
    className={`anyinfer-sdk-version anyinfer-sdk-badge anyinfer-sdk-badge--${python ? 'python' : 'csharp'}`}
    title={active.label}
    versions={Object.fromEntries(versions.map((version) => [version.name, {
      label: version.label.replace(/^(Python|C#) /, 'v').replace(' (prerelease)', ''),
    }]))}
    dropdownItemsBefore={[]}
    dropdownItemsAfter={[]}
    items={[]}
  />;
}
