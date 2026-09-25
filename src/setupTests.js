// The jsdom that ships with Create React App's Jest predates TextEncoder,
// which React Router 7 uses. Browsers and Node have had it for years.
import { TextDecoder, TextEncoder } from 'util';

Object.assign(global, { TextDecoder, TextEncoder });
