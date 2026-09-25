/**
 * Word-level highlighting inside a changed line.
 *
 * A unified diff marks a whole paragraph of terms of service as removed and
 * re-added when one clause moved, which leaves the reader to play
 * spot-the-difference across two walls of text. Pairing each removed line with
 * the added line that replaced it, and marking only the words that differ,
 * puts the eye straight on the edit. Pure, and bounded: a pair too large to
 * compare cheaply, or too different to be the same sentence, is left whole.
 */

const MAX_CELLS = 400000;
const MIN_SHARED = 0.35;

export const tokenize = (text) => (text || '').match(/\s+|[^\s]+/g) || [];

const merge = (parts) =>
  parts.reduce((out, part) => {
    const last = out[out.length - 1];
    if (last && last.changed === part.changed) last.text += part.text;
    else out.push({ ...part });
    return out;
  }, []);

/**
 * The two sides of a changed line, each as runs of `{ text, changed }`, or
 * null when the lines are not similar enough for word marks to help.
 */
export function diffWords(before, after) {
  const a = tokenize(before);
  const b = tokenize(after);
  if (a.length === 0 || b.length === 0 || a.length * b.length > MAX_CELLS) return null;

  // Longest common subsequence over tokens, filled from the end so the walk
  // below can go forwards.
  const rows = a.length + 1;
  const cols = b.length + 1;
  const table = new Uint32Array(rows * cols);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i * cols + j] =
        a[i] === b[j]
          ? table[(i + 1) * cols + j + 1] + 1
          : Math.max(table[(i + 1) * cols + j], table[i * cols + j + 1]);
    }
  }

  const words = (tokens) => tokens.filter((t) => /\S/.test(t)).length || 1;
  const sharedWords = (() => {
    let count = 0;
    let i = 0;
    let j = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) {
        if (/\S/.test(a[i])) count += 1;
        i += 1;
        j += 1;
      } else if (table[(i + 1) * cols + j] >= table[i * cols + j + 1]) i += 1;
      else j += 1;
    }
    return count;
  })();
  if (sharedWords / Math.max(words(a), words(b)) < MIN_SHARED) return null;

  const left = [];
  const right = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      left.push({ text: a[i], changed: false });
      right.push({ text: b[j], changed: false });
      i += 1;
      j += 1;
    } else if (j >= b.length || (i < a.length && table[(i + 1) * cols + j] >= table[i * cols + j + 1])) {
      left.push({ text: a[i], changed: /\S/.test(a[i]) });
      i += 1;
    } else {
      right.push({ text: b[j], changed: /\S/.test(b[j]) });
      j += 1;
    }
  }
  return { before: merge(left), after: merge(right) };
}

/**
 * Attaches `segments` to paired remove/add lines within one hunk: the n-th
 * line of a run of removals is paired with the n-th line of the additions
 * that immediately follow it.
 */
export function pairChangedLines(lines) {
  const out = lines.map((line) => ({ ...line }));
  let index = 0;
  while (index < out.length) {
    if (out[index].type !== 'remove') {
      index += 1;
      continue;
    }
    const removeStart = index;
    while (index < out.length && out[index].type === 'remove') index += 1;
    const addStart = index;
    while (index < out.length && out[index].type === 'add') index += 1;
    const pairs = Math.min(addStart - removeStart, index - addStart);
    for (let n = 0; n < pairs; n += 1) {
      const removed = out[removeStart + n];
      const added = out[addStart + n];
      const words = diffWords(removed.text, added.text);
      if (words) {
        removed.segments = words.before;
        added.segments = words.after;
      }
    }
  }
  return out;
}
