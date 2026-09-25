/**
 * Adds a Content-Security-Policy to the built index.html. Runs as `postbuild`.
 *
 * GitHub Pages cannot send response headers, so the policy goes in a <meta>
 * tag. It is added to the build rather than to public/index.html because the
 * development server needs eval and injected scripts that the policy forbids,
 * and because the build minifies the inline theme script: the hash has to be
 * of the bytes that ship, so it is computed here, after minification.
 *
 * The dashboard only ever talks to its own origin, so everything else is
 * refused. A planted image, script or connection in model-written text, or in
 * any future injection bug, has nowhere to go.
 */
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const INDEX = path.join(__dirname, '..', 'build', 'index.html');

const hashOf = (source) => `'sha256-${crypto.createHash('sha256').update(source, 'utf8').digest('base64')}'`;

function policyFor(html) {
  const inline = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
  return [
    "default-src 'self'",
    `script-src 'self' ${inline.map(hashOf).join(' ')}`.trim(),
    // React sets style attributes (tile colours, chart widths); stylesheets
    // themselves come only from this origin.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join('; ');
}

function addPolicy(html) {
  if (html.includes('http-equiv="Content-Security-Policy"')) {
    throw new Error('index.html already has a Content-Security-Policy');
  }
  const tags =
    `<meta http-equiv="Content-Security-Policy" content="${policyFor(html)}">` +
    '<meta name="referrer" content="strict-origin-when-cross-origin">';
  // Straight after the charset, so the policy is in force before any script.
  const charset = /<meta charset="utf-8"\s*\/?>/i;
  if (!charset.test(html)) throw new Error('index.html has no <meta charset="utf-8"> to anchor the policy after');
  return html.replace(charset, (match) => match + tags);
}

if (require.main === module) {
  const html = fs.readFileSync(INDEX, 'utf8');
  fs.writeFileSync(INDEX, addPolicy(html));
  console.log(`Content-Security-Policy added to ${path.relative(process.cwd(), INDEX)}`);
}

module.exports = { addPolicy, policyFor };
