import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import SafeMarkdown from './SafeMarkdown';

global.IS_REACT_ACT_ENVIRONMENT = true;

// react-markdown ships only as an ES module, which this test runner does not
// transform, so it is stood in for by a stub that shows how it was called.
// What it then does with those props was checked against the real library.
jest.mock('react-markdown', () => (props) => (
  <div
    data-disallowed={(props.disallowedElements || []).join(',')}
    data-unwrap={String(Boolean(props.unwrapDisallowed))}
  >
    {props.children}
  </div>
));

const render = (children) => {
  const container = document.createElement('div');
  act(() => {
    createRoot(container).render(<SafeMarkdown>{children}</SafeMarkdown>);
  });
  return container.firstChild;
};

test('links and images are removed, keeping a link’s text', () => {
  const node = render('See [the terms](https://phish.example) ![](https://tracker.example/p.png)');
  expect(node.dataset.disallowed.split(',')).toEqual(expect.arrayContaining(['a', 'img']));
  expect(node.dataset.unwrap).toBe('true');
});

test('an analysis that is not text renders nothing rather than crashing the page', () => {
  expect(render({ legacy: 'object' }).textContent).toBe('');
  expect(render(undefined).textContent).toBe('');
});
