# Browser dependencies

Vendored from the npm registry so the buildless UI does not require a CDN at runtime:

- [Marked 18.1.3](https://www.npmjs.com/package/marked/v/18.1.3): `marked.umd.js`, MIT license.
- [DOMPurify 3.4.17](https://www.npmjs.com/package/dompurify/v/3.4.17): `purify.min.js`, Apache-2.0 or MPL-2.0 license.

The package tarballs were checked against their published SHA-512 integrity values before extraction.
Keep the corresponding license files when updating these assets. Answers pass through Marked, then DOMPurify
with a restricted set of Markdown elements; the resulting DOM fragment is inserted without reparsing HTML.
