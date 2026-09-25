import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, useLocation } from 'react-router-dom';
import CommandPalette from './CommandPalette';

global.IS_REACT_ACT_ENVIRONMENT = true;

const policySets = [
  { setName: 'Anthropic Legal Policies', file_id: 'Anthropic_Legal_Policies', category: 'Private Sector', urls: [{ url: 'https://anthropic.com' }] },
  { setName: 'NSW Government AI Guidance', file_id: 'NSW_Government_AI_Guidance', category: 'State Government', urls: [{ url: 'https://nsw.gov.au' }] },
];
const feed = {
  items: [{ id: 'x', kind: 'news', title: 'Senate inquiry into AI procurement', url: 'https://example.com/x', publisher: 'ABC', relevance: 3 }],
};

let container;
let root;
let onClose;

function Where() {
  return <output data-testid="where">{useLocation().pathname}</output>;
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  onClose = jest.fn();
  global.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  act(() => {
    root.render(
      <MemoryRouter>
        <CommandPalette open onClose={onClose} policySets={policySets} feed={feed} actions={[]} />
        <Where />
      </MemoryRouter>
    );
  });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const type = (value) => {
  const input = container.querySelector('.palette-input input');
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  return input;
};

const press = (input, key) =>
  act(() => {
    input.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  });

test('finds a policy by any word and opens it with Enter', () => {
  const input = type('nsw guidance');
  const options = [...container.querySelectorAll('[role="option"]')];
  expect(options.map((o) => o.textContent)).toEqual([expect.stringContaining('NSW Government AI Guidance')]);
  press(input, 'Enter');
  expect(container.querySelector('[data-testid="where"]').textContent).toBe('/policy/NSW_Government_AI_Guidance');
  expect(onClose).toHaveBeenCalled();
});

test('searches news headlines too, and says so when nothing matches', () => {
  type('senate');
  expect(container.querySelector('.palette-group-label').textContent).toBe('News');
  type('zzzz');
  expect(container.querySelector('.palette-empty').textContent).toContain('Nothing matches');
});

test('arrow keys move the selection', () => {
  const input = type('policies');
  const selected = () => container.querySelector('[aria-selected="true"]').textContent;
  const first = selected();
  press(input, 'ArrowDown');
  expect(selected()).not.toBe(first);
  press(input, 'ArrowUp');
  expect(selected()).toBe(first);
});
