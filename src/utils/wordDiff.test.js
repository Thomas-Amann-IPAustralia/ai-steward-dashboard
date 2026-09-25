import { diffWords, pairChangedLines, tokenize } from './wordDiff';
import { parseDiff } from '../components/DiffView';

const changed = (segments) => segments.filter((s) => s.changed).map((s) => s.text);

describe('word-level diff', () => {
  test('marks only the words that differ', () => {
    const words = diffWords('We keep your data for 30 days.', 'We keep your data for 90 days.');
    expect(changed(words.before)).toEqual(['30']);
    expect(changed(words.after)).toEqual(['90']);
    expect(words.after.map((s) => s.text).join('')).toBe('We keep your data for 90 days.');
  });

  test('lines with little in common are left whole', () => {
    expect(diffWords('Governing law is New South Wales.', 'Contact us by email at any time.')).toBeNull();
  });

  test('tokens keep their whitespace, so the text reassembles exactly', () => {
    expect(tokenize('a  b\tc').join('')).toBe('a  b\tc');
  });

  test('pairs the n-th removed line with the n-th added line of a block', () => {
    const lines = pairChangedLines([
      { type: 'context', text: 'Heading' },
      { type: 'remove', text: 'Email: privacy@old.example' },
      { type: 'add', text: 'Email: privacy@new.example' },
      { type: 'add', text: 'Telephone: +61 2 0000 0000' },
    ]);
    expect(changed(lines[1].segments)).toEqual(['privacy@old.example']);
    expect(changed(lines[2].segments)).toEqual(['privacy@new.example']);
    expect(lines[3].segments).toBeUndefined();
    expect(lines[0].segments).toBeUndefined();
  });

  test('a parsed diff carries word marks through to its hunks', () => {
    const files = parseDiff(
      ['===== Privacy =====', '--- a', '+++ b', '@@ -1,2 +1,2 @@', ' Intro', '-Retained for 30 days.', '+Retained for 90 days.'].join('\n')
    );
    expect(files).toHaveLength(1);
    expect(files[0].label).toBe('Privacy');
    const [, removed, added] = files[0].hunks[0].lines;
    expect(changed(removed.segments)).toEqual(['30']);
    expect(changed(added.segments)).toEqual(['90']);
  });
});
