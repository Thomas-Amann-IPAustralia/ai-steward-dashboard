import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ReviewsProvider } from '../hooks/useReviews';
import PoliciesOverview from './PoliciesOverview';

global.IS_REACT_ACT_ENVIRONMENT = true;

const set = (setName, category) => ({
  setName,
  category,
  file_id: setName.replace(/\W+/g, '_'),
  urls: [{ url: `https://example.com/${setName.length}` }],
  last_checked: new Date().toISOString(),
});

const policySets = [
  set('Digital.gov.au AI Policy', 'Australian Government'),
  set('NSW Government AI Guidance', 'State Government'),
  set('Anthropic Legal Policies', 'Private Sector'),
];

let container;
let root;

beforeEach(() => {
  global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 404 }));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const render = async (path = '/policies') => {
  await act(async () => {
    root.render(
      <ReviewsProvider>
        <MemoryRouter initialEntries={[path]}>
          <PoliciesOverview policySets={policySets} health={null} loading={false} />
        </MemoryRouter>
      </ReviewsProvider>
    );
  });
};

const cards = () => [...container.querySelectorAll('.policy-card h3')].map((h) => h.textContent);
const sectorButton = (label) =>
  [...container.querySelectorAll('[aria-label="Sector"] button')].find((b) => b.textContent.startsWith(label));

test('the sector filter separates government from private-sector policies', async () => {
  await render();
  expect(cards()).toHaveLength(3);
  expect(sectorButton('Government').textContent).toContain('2');

  act(() => sectorButton('Private sector').click());
  expect(cards()).toEqual(['Anthropic Legal Policies']);

  act(() => sectorButton('Government').click());
  expect(cards().sort()).toEqual(['Digital.gov.au AI Policy', 'NSW Government AI Guidance']);
});

test('a filtered view can be shared, and opening a policy keeps the sector', async () => {
  await render('/policies?sector=private');
  expect(cards()).toEqual(['Anthropic Legal Policies']);
  expect(container.querySelector('.policy-card').getAttribute('href')).toContain('?sector=private');
});
