import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ReviewsProvider } from '../hooks/useReviews';
import { ToastProvider } from '../hooks/useToast';
import DashboardHome from './DashboardHome';

global.IS_REACT_ACT_ENVIRONMENT = true;

const daysAgo = (n) => new Date(Date.now() - n * 24 * 60 * 60 * 1000).toISOString();

const policySets = [
  {
    setName: 'Anthropic Legal Policies',
    file_id: 'Anthropic_Legal_Policies',
    category: 'Private Sector',
    urls: [{ url: 'https://www.anthropic.com/legal/privacy' }],
    last_checked: daysAgo(0),
    last_amended: daysAgo(3),
    last_priority: 'critical',
    last_verdict: 'material_change',
    last_change: { summary: 'The privacy policy now covers Korean residents.', changed_documents: ['Privacy'] },
  },
  {
    setName: 'Google AI Policies',
    file_id: 'Google_AI_Policies',
    category: 'Private Sector',
    urls: [{ url: 'https://policies.google.com/terms' }],
    last_checked: daysAgo(0),
    last_amended: daysAgo(90),
    last_priority: 'low',
  },
  {
    setName: 'Commonwealth AI Transparency Statement Register',
    file_id: 'Commonwealth_AI_Transparency_Statement_Register',
    category: 'Australian Government',
    kind: 'adoption',
    urls: [{ url: 'https://www.digital.gov.au/policy/ai/list-of-transparency-statements' }],
    last_checked: daysAgo(0),
    last_amended: daysAgo(2),
    last_priority: 'low',
    last_verdict: 'material_change',
    last_change: { summary: 'Three entities were added to the register.', changed_documents: ['Register'] },
  },
];

const feed = {
  generated_at: daysAgo(0),
  sources: {},
  items: [
    {
      id: 'n1',
      kind: 'news',
      title: 'Agency publishes AI transparency statement',
      url: 'https://example.com/n1',
      publisher: 'Example',
      category: 'Australian Government',
      relevance: 3,
      published: daysAgo(1),
      first_seen: daysAgo(1),
      related_policies: [],
    },
  ],
};

let container;
let root;

beforeEach(() => {
  localStorage.clear();
  // The history index and analysis files are supplementary; unavailable here.
  global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 404 }));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const render = async () => {
  await act(async () => {
    root.render(
      <ToastProvider>
        <ReviewsProvider>
          <MemoryRouter>
            <DashboardHome policySets={policySets} health={null} feed={feed} since={null} loading={false} />
          </MemoryRouter>
        </ReviewsProvider>
      </ToastProvider>
    );
  });
};

const button = (text) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(text));

test('a recent material change waits in the review queue; an old one does not', async () => {
  await render();
  const queue = container.querySelector('#review-queue');
  expect(queue.textContent).toContain('Anthropic Legal Policies');
  expect(queue.textContent).toContain('The privacy policy now covers Korean residents.');
  expect(queue.textContent).not.toContain('Google AI Policies');
  expect(container.querySelector('.narrative').textContent).toContain('1 policy change is waiting for your review');
});

test('marking a change reviewed empties the queue, remembers it, and can be undone', async () => {
  await render();
  act(() => button('Mark reviewed').click());

  expect(container.querySelector('#review-queue .empty-state').textContent).toContain('All caught up');
  expect(container.querySelector('.reviewed-disclosure').textContent).toContain('Reviewed (1)');
  expect(Object.keys(JSON.parse(localStorage.getItem('steward.reviewed')))).toEqual([
    `Anthropic_Legal_Policies@${policySets[0].last_amended}`,
  ]);
  expect(container.querySelector('.toast').textContent).toContain('Marked “Anthropic Legal Policies” as reviewed');

  act(() => container.querySelector('.toast-action').click());
  expect(container.querySelector('#review-queue .review-list').textContent).toContain('Anthropic Legal Policies');
});

test('an adoption register is shown across government, not queued for review', async () => {
  await render();
  const queue = container.querySelector('#review-queue');
  expect(queue.textContent).not.toContain('Transparency Statement Register');

  const across = container.querySelector('[aria-labelledby="adoption-title"]');
  expect(across.textContent).toContain('Commonwealth AI Transparency Statement Register');
  expect(across.textContent).toContain('Three entities were added to the register.');
  expect(across.textContent).toContain('Adoption update');
  expect(across.textContent).not.toMatch(/Mark reviewed|priority/i);
});

test('news is offered to read, never to review', async () => {
  await render();
  const stories = [...container.querySelectorAll('.card')].find((card) => card.textContent.includes('Top stories'));
  expect(stories.textContent).toContain('Agency publishes AI transparency statement');
  expect(stories.textContent).not.toMatch(/act on|review/i);
});
