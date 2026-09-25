import React from 'react';
import { hostOf } from '../utils/constants';

/**
 * A lettermark tile in place of a favicon.
 *
 * The previous implementation called google.com/s2/favicons on every render.
 * From a tool aimed at public servants that is a third-party request which
 * agency networks may block — leaving broken icons — and it discloses the list
 * of monitored sites to Google. This costs nothing and always renders.
 *
 * The letter comes from the name, not the host: a host-derived letter showed
 * Google's policies as "P" (policies.google.com) and Midjourney's as "D".
 */

const PALETTE = [
  '#3056d3', '#0f8a7e', '#7c3aed', '#c2410c',
  '#be185d', '#15803d', '#0369a1', '#9333ea',
];

/** A stable colour for a name, so a source or outlet is always the same tile. */
export const colorFor = (seed) => {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) % 100000;
  }
  return PALETTE[hash % PALETTE.length];
};

function Lettermark({ url, name, size = 18 }) {
  const host = hostOf(url);
  const seed = name || host || '?';
  const letter = ((name || host || '?').match(/[A-Za-z0-9]/)?.[0] || '?').toUpperCase();

  return (
    <span
      className="lettermark"
      style={{
        '--mark': colorFor(seed),
        width: size,
        height: size,
        fontSize: Math.round(size * 0.5),
        borderRadius: Math.max(4, Math.round(size * 0.28)),
      }}
      title={host || undefined}
      aria-hidden="true"
    >
      {letter}
    </span>
  );
}

export default Lettermark;
