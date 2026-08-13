import React from 'react';
import { hostOf } from '../utils/constants';

/**
 * A lettermark chip in place of a favicon.
 *
 * The previous implementation called google.com/s2/favicons on every render.
 * From a tool aimed at public servants that is a third-party request which
 * agency networks may block — leaving broken icons — and it discloses the list
 * of monitored sites to Google. This costs nothing and always renders.
 */

const PALETTE = [
  '#00529B', '#0f766e', '#7c3aed', '#b45309',
  '#be123c', '#15803d', '#0369a1', '#7e22ce',
];

const colorFor = (seed) => {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) % 100000;
  }
  return PALETTE[hash % PALETTE.length];
};

function Lettermark({ url, name, size = 18 }) {
  const host = hostOf(url);
  const seed = host || name || '?';
  const letter = (host || name || '?').charAt(0).toUpperCase();

  return (
    <span
      className="lettermark"
      style={{
        backgroundColor: colorFor(seed),
        width: size,
        height: size,
        fontSize: Math.round(size * 0.55),
      }}
      title={host || undefined}
      aria-hidden="true"
    >
      {letter}
    </span>
  );
}

export default Lettermark;
