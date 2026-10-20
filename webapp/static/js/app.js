// App shell: navigation, routing and theme.
//
// ADDING A PAGE: create js/views/<name>.js exporting `default { mount(root, ctx) }`
// (mount may return a cleanup function), then add one entry to PAGES below.
// `nav` decides where its link appears: 'main', 'tools', 'footer' or null (hidden).

import { applyTheme, cycleTheme, THEME_META } from './lib/theme.js';
import { settings } from './lib/settings.js';
import { h, icon, openMenu, toastError } from './lib/ui.js';

export const PAGES = [
  { path: 'scan', title: 'Scan', icon: 'scan', nav: 'main', load: () => import('./views/scan.js') },
  { path: 'live', title: 'Live camera', short: 'Live', icon: 'camera', nav: 'main', load: () => import('./views/live.js') },
  { path: 'library', title: 'Library', icon: 'library', nav: 'main', load: () => import('./views/library.js') },
  { path: 'align', title: 'Align to template', short: 'Align', icon: 'layers', nav: 'tools', load: () => import('./views/align.js') },
  { path: 'calibrate', title: 'Calibrate camera', short: 'Calibrate', icon: 'target', nav: 'tools', load: () => import('./views/calibrate.js') },
  { path: 'learn', title: 'How it works', short: 'Learn', icon: 'book', nav: 'tools', load: () => import('./views/learn.js') },
  { path: 'settings', title: 'Settings', icon: 'settings', nav: 'footer', load: () => import('./views/settings.js') },
  { path: 'doc', title: 'Edit scan', nav: null, parent: 'library', load: () => import('./views/editor.js') },
];

const view = document.getElementById('view');
let cleanup = null;
let renderToken = 0;

export function navigate(path) {
  const target = `#/${path.replace(/^#?\/?/, '')}`;
  if (location.hash === target) route();
  else location.hash = target;
}

function parseHash() {
  const [path = 'scan', ...params] = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  return { path, params: params.map(decodeURIComponent) };
}

async function route() {
  const { path, params } = parseHash();
  const page = PAGES.find((p) => p.path === path) || PAGES[0];
  const token = ++renderToken;
  if (typeof cleanup === 'function') { try { cleanup(); } catch (e) { console.error(e); } }
  cleanup = null;
  highlight(page.parent || page.path);
  document.title = `${page.title} · DocScan`;
  try {
    const mod = await page.load();
    if (token !== renderToken) return;
    view.replaceChildren();
    view.style.animation = 'none';
    void view.offsetWidth;          // restart the fade-in
    view.style.animation = '';
    window.scrollTo(0, 0);
    cleanup = await mod.default.mount(view, { params, navigate });
  } catch (err) {
    console.error(err);
    toastError(err);
  }
}

// ---------------------------------------------------------------- navigation UI
function navLink(page, cls = 'nav-item') {
  return h('a', { class: cls, href: `#/${page.path}`, dataset: { path: page.path } }, icon(page.icon), h('span', null, cls === 'nav-item' ? page.title : (page.short || page.title)));
}

function renderSidebar() {
  const sidebar = document.getElementById('sidebar');
  const themeBtn = h('button', { class: 'nav-item theme-btn', onClick: cycleTheme });
  const paintTheme = () => {
    const meta = THEME_META[settings.get('theme')];
    themeBtn.replaceChildren(icon(meta.icon), h('span', null, meta.label));
    themeBtn.title = 'Switch theme (System → Light → Dark)';
  };
  paintTheme();
  settings.onChange((k) => { if (k === 'theme' || k === '*') paintTheme(); });
  sidebar.replaceChildren(
    h('a', { class: 'brand', href: '#/scan' }, h('span', { class: 'brand-mark' }, icon('logo')), 'DocScan'),
    ...PAGES.filter((p) => p.nav === 'main').map((p) => navLink(p)),
    h('div', { class: 'nav-label' }, 'Tools'),
    ...PAGES.filter((p) => p.nav === 'tools').map((p) => navLink(p)),
    h('div', { class: 'sidebar-footer' }, ...PAGES.filter((p) => p.nav === 'footer').map((p) => navLink(p)), themeBtn),
  );

  const tabbar = document.getElementById('tabbar');
  const more = h('button', { type: 'button', dataset: { path: '__more' } }, icon('menu'), h('span', null, 'More'));
  more.addEventListener('click', () => openMenu(more, [
    ...PAGES.filter((p) => p.nav === 'tools' || p.nav === 'footer').map((p) => ({ label: p.title, icon: p.icon, onClick: () => navigate(p.path) })),
    '-',
    { label: THEME_META[settings.get('theme')].label, icon: THEME_META[settings.get('theme')].icon, hint: 'switch', onClick: cycleTheme },
  ]));
  tabbar.replaceChildren(...PAGES.filter((p) => p.nav === 'main').map((p) => navLink(p, '')), more);
}

function highlight(path) {
  document.querySelectorAll('[data-path]').forEach((el) => el.classList.toggle('active', el.dataset.path === path));
  const tools = PAGES.filter((p) => p.nav === 'tools' || p.nav === 'footer').map((p) => p.path);
  document.querySelector('#tabbar [data-path="__more"]')?.classList.toggle('active', tools.includes(path));
}

applyTheme();
renderSidebar();
window.addEventListener('hashchange', route);
route();
