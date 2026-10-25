/**
 * Self-hosted brand typefaces. Webpack bundles the Latin woff2 files into the static
 * build, so the published site and the offline browser tests never contact a font CDN.
 *
 * Space Grotesk sets display type and headings, Inter sets body and interface text, and
 * JetBrains Mono sets code, provenance badges, and labels. Only the weights the brand kit
 * uses are loaded; characters outside the Latin subset fall back to the system stack.
 */
import '@fontsource/space-grotesk/latin-500.css';
import '@fontsource/space-grotesk/latin-600.css';
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/inter/latin-600.css';
import '@fontsource/jetbrains-mono/latin-400.css';
import '@fontsource/jetbrains-mono/latin-500.css';
