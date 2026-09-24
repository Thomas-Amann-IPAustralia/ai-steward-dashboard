import React from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react-dom/test-utils';
import { MemoryRouter } from 'react-router-dom';
import NewsFeed from './NewsFeed';

global.IS_REACT_ACT_ENVIRONMENT = true;

const feed = {
  generated_at: new Date().toISOString(),
  window_days: 45,
  sources: { s: { kind: 'news' } },
  items: [
    {
      id: 'act',
      kind: 'news',
      title: 'Agency publishes AI transparency statement',
      url: 'https://example.com/act',
      source_name: 'Example',
      category: 'Australian Government',
      relevance: 3,
      tldr: 'Written by the model.',
      summary: 'From the publisher.',
      published: new Date().toISOString(),
      related_policies: ['Digital_gov_au_AI_Policy'],
    },
    {
      id: 'minor',
      kind: 'news',
      title: 'A model got slightly faster',
      url: 'https://example.com/minor',
      source_name: 'Example',
      category: 'AI providers',
      relevance: 1,
      summary: 'Publisher excerpt only.',
      published: new Date().toISOString(),
      related_policies: [],
    },
  ],
};

let container;
let root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const render = (path = '/news') =>
  act(() => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <NewsFeed
          feed={feed}
          loading={false}
          error={null}
          since={null}
          policyNames={{ Digital_gov_au_AI_Policy: 'Digital.gov.au AI Policy' }}
        />
      </MemoryRouter>
    );
  });

test('opens on the relevant items, with Everything one click away', () => {
  render();
  expect(container.textContent).toContain('Agency publishes AI transparency statement');
  expect(container.textContent).not.toContain('A model got slightly faster');

  const everything = [...container.querySelectorAll('button')].find((b) => b.textContent === 'Everything');
  act(() => everything.click());
  expect(container.textContent).toContain('A model got slightly faster');
});

test('an "act on it" story leads, linking to the original in a new tab', () => {
  render();
  const lead = container.querySelector('.top-story');
  const link = lead.querySelector('.top-story-title a');
  expect(link.getAttribute('href')).toBe('https://example.com/act');
  expect(link.getAttribute('target')).toBe('_blank');
  expect(link.getAttribute('rel')).toContain('noopener');
  expect(lead.querySelector('.top-story-blurb').textContent).toBe('Written by the model.');
});

test('searching lists every match as a row, without lead stories', () => {
  render('/news?q=transparency');
  expect(container.querySelector('.top-story')).toBeNull();
  expect(container.querySelector('.news-row-title a').textContent).toContain('transparency statement');
});

test('an item about a monitored policy links to it', () => {
  render();
  const related = container.querySelector('.policy-link');
  expect(related.textContent).toBe('Digital.gov.au AI Policy');
  expect(related.getAttribute('href')).toBe('/policy/Digital_gov_au_AI_Policy');
});

test('a category with nothing to show is disabled rather than a dead end', () => {
  render();
  const chips = [...container.querySelectorAll('.filter-chip')];
  const international = chips.find((chip) => chip.textContent.startsWith('International'));
  const government = chips.find((chip) => chip.textContent.startsWith('Australian Government'));
  expect(international.disabled).toBe(true);
  expect(government.disabled).toBe(false);
  expect(government.textContent).toContain('1');
});

test('a missing feed is a notice, not a crash', () => {
  act(() => {
    root.render(
      <MemoryRouter>
        <NewsFeed
          feed={{ items: [], sources: {} }}
          loading={false}
          error="The news and incident feed is not available yet."
          since={null}
          policyNames={{}}
        />
      </MemoryRouter>
    );
  });
  expect(container.textContent).toContain('not available yet');
});
