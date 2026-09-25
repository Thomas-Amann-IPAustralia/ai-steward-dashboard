import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import TransparencyView from './TransparencyView';

global.IS_REACT_ACT_ENVIRONMENT = true;

const daysAgo = (n) => new Date(Date.now() - n * 24 * 60 * 60 * 1000).toISOString();

const data = {
  generated_at: daysAgo(0),
  register: {
    url: 'https://www.digital.gov.au/policy/ai/list-of-transparency-statements',
    status: 'ok',
    page_updated: '2026-06-23',
    counts: { mandatory: 2, voluntary: 1 },
  },
  statements: [
    {
      id: 'ip-australia',
      agency: 'IP Australia',
      portfolio: 'Industry, Science and Resources',
      obligation: 'mandatory',
      url: 'https://www.ipaustralia.gov.au/ai',
      statement_date: daysAgo(30).slice(0, 10),
      status: 'ok',
      first_seen: daysAgo(40),
      last_change: { timestamp: daysAgo(2), verdict: 'material_change', summary: 'Added prior-art search.' },
      document: { last_success: daysAgo(0) },
    },
    {
      id: 'geoscience-australia',
      agency: 'Geoscience Australia',
      portfolio: 'Industry, Science and Resources',
      obligation: 'mandatory',
      url: 'https://www.ga.gov.au/ai',
      statement_date: daysAgo(500).slice(0, 10),
      status: 'ok',
      first_seen: daysAgo(40),
      document: { last_success: daysAgo(0) },
    },
    {
      id: 'asio',
      agency: 'Australian Security Intelligence Organisation',
      portfolio: 'Home Affairs',
      obligation: 'voluntary',
      url: 'https://www.asio.gov.au/ai',
      status: 'failing',
      first_seen: daysAgo(40),
      document: { last_error: 'ReadTimeout: timed out' },
    },
  ],
  events: [
    { type: 'updated', timestamp: daysAgo(2), id: 'ip-australia', agency: 'IP Australia', summary: 'Added prior-art search.' },
    { type: 'reworded', timestamp: daysAgo(3), id: 'geoscience-australia', agency: 'Geoscience Australia', summary: 'Contact email updated.' },
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

const render = async (props = {}, path = '/transparency') => {
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <TransparencyView data={data} loading={false} error={null} since={null} {...props} />
      </MemoryRouter>
    );
  });
};

const button = (text) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(text));
const listed = () => [...container.querySelectorAll('.statement-item .review-name')].map((el) => el.textContent);

test('statements are grouped by portfolio, each with its date and last change', async () => {
  await render();
  const groups = [...container.querySelectorAll('.statement-group h2')].map((h) => h.textContent);
  expect(groups).toEqual(['Home Affairs', 'Industry, Science and Resources']);
  const ip = [...container.querySelectorAll('.statement-item')].find((el) => el.textContent.includes('IP Australia'));
  expect(ip.textContent).toContain('Added prior-art search.');
  expect(ip.textContent).toContain('Statement dated');
  const asio = [...container.querySelectorAll('.statement-item')].find((el) => el.textContent.includes('Security Intelligence'));
  expect(asio.textContent).toContain('Voluntary');
  expect(asio.textContent).toContain('ReadTimeout');
});

test('the obligation filter is kept in the URL', async () => {
  await render({}, '/transparency?obligation=voluntary');
  expect(listed()).toEqual(['Australian Security Intelligence Organisation']);
  act(() => button('All').click());
  expect(listed()).toHaveLength(3);
});

test('the dated tile narrows the list to statements over a year old', async () => {
  await render();
  act(() => container.querySelector('.stat-tile.as-button').click());
  expect(listed()).toEqual(['Geoscience Australia']);
});

test('rewording stays out of recent activity unless asked for', async () => {
  await render();
  const activity = () => container.querySelector('[aria-labelledby="transparency-activity-title"]').textContent;
  expect(activity()).toContain('Statement updated');
  expect(activity()).not.toContain('Contact email updated.');
  act(() => container.querySelector('.toggle-label input').click());
  expect(activity()).toContain('Contact email updated.');
});

test('an unreadable register is said plainly, and the known statements are still shown', async () => {
  await render({
    data: { ...data, register: { ...data.register, status: 'failing', last_error: 'register read rejected: found 0 statement link(s)' } },
  });
  expect(container.querySelector('.callout-critical').textContent).toContain('The register could not be read');
  expect(listed()).toHaveLength(3);
});
