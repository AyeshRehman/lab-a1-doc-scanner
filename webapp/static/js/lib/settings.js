// User preferences, kept in this browser's localStorage.

const KEY = 'docscan.settings';

export const DEFAULTS = {
  theme: 'system',          // system | light | dark
  mode: 'color',            // default look for new scans
  aspect: 'auto',           // auto | a4 | letter | legal | free
  deskew: false,
  holes: false,
  resolution: '1080',       // requested camera height
  autoCapture: false,
  steadiness: 'normal',     // quick | normal | careful
  deviceId: '',
  showDebug: false,
  librarySort: 'new',
};

export const STEADINESS = { quick: 8, normal: 15, careful: 25 };

let state = load();
const listeners = new Set();

function load() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch { return { ...DEFAULTS }; }
}

export const settings = {
  get: (key) => state[key],
  all: () => ({ ...state }),
  set(key, value) {
    state = { ...state, [key]: value };
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* private mode */ }
    listeners.forEach((fn) => fn(key, value));
  },
  reset() {
    state = { ...DEFAULTS };
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
    listeners.forEach((fn) => fn('*'));
  },
  onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  /** Options sent to the server for a new scan. */
  scanOptions: () => ({ mode: state.mode, aspect: state.aspect, deskew: state.deskew, holes: state.holes }),
};
