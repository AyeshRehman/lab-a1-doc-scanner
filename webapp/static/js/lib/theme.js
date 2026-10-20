import { settings } from './settings.js';

const media = window.matchMedia('(prefers-color-scheme: dark)');

export function resolvedTheme() {
  const t = settings.get('theme');
  return t === 'system' ? (media.matches ? 'dark' : 'light') : t;
}

export function applyTheme() {
  document.documentElement.setAttribute('data-theme', resolvedTheme());
}

export function cycleTheme() {
  const order = ['system', 'light', 'dark'];
  settings.set('theme', order[(order.indexOf(settings.get('theme')) + 1) % order.length]);
}

export const THEME_META = {
  system: { label: 'System theme', icon: 'monitor' },
  light: { label: 'Light theme', icon: 'sun' },
  dark: { label: 'Dark theme', icon: 'moon' },
};

media.addEventListener('change', applyTheme);
settings.onChange((key) => { if (key === 'theme' || key === '*') applyTheme(); });
