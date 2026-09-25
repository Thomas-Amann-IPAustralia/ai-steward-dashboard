import React from 'react';
import ReactMarkdown from 'react-markdown';

/**
 * Markdown the model wrote about a change, rendered without links or images.
 *
 * The model reads text from third-party pages, so its output can carry what
 * those pages planted. react-markdown already refuses raw HTML and
 * javascript: URLs; this also keeps a planted image from loading in every
 * reader's browser (it would log who read the page) and a planted link from
 * appearing as a clickable, official-looking instruction. A link's text is
 * kept as plain text. No analysis written so far contains either.
 */
const DISALLOWED = ['a', 'img'];

function SafeMarkdown({ children }) {
  return (
    <ReactMarkdown disallowedElements={DISALLOWED} unwrapDisallowed>
      {typeof children === 'string' ? children : ''}
    </ReactMarkdown>
  );
}

export default SafeMarkdown;
