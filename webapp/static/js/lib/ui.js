// Tiny DOM toolkit: element builder, icons and the shared UI components.
import { ICONS } from './icons.js';

/** h('div', {class: 'x', onClick() {}}, child, 'text', [more]) */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style' && typeof value === 'object') Object.assign(el.style, value);
    else if (key === 'html') el.innerHTML = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key === 'ref') value(el);
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (['value', 'checked', 'disabled', 'selected', 'hidden', 'multiple'].includes(key)) el[key] = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function icon(name, cls = '') {
  const t = document.createElement('template');
  t.innerHTML = `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
  return t.content.firstChild;
}

export function button(label, { icon: ic, variant = '', size = '', title, onClick, disabled, type = 'button' } = {}) {
  const iconOnly = !label;
  return h('button', {
    type, class: ['btn', variant && `btn-${variant}`, size && `btn-${size}`, iconOnly && 'btn-icon'].filter(Boolean).join(' '),
    title: title || (iconOnly ? undefined : null), 'aria-label': iconOnly ? title : undefined, onClick, disabled,
  }, ic && icon(ic), label && h('span', { class: 'label' }, label));
}

export function clear(el) { while (el.firstChild) el.firstChild.remove(); return el; }

export const debounce = (fn, ms = 250) => {
  let t;
  const wrapped = (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  wrapped.cancel = () => clearTimeout(t);
  return wrapped;
};

export function relTime(ts) {
  const s = Math.round(Date.now() / 1000 - ts);
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function fmtBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function downloadUrl(url) {
  const a = h('a', { href: url, download: '' });
  document.body.append(a);
  a.click();
  a.remove();
}

// ------------------------------------------------------------------ toasts
export function toast(message, { type = 'info', action, timeout = 3800 } = {}) {
  const host = document.getElementById('toasts');
  const ic = { success: 'checkCircle', error: 'alert', info: 'info' }[type];
  const el = h('div', { class: `toast ${type}` }, icon(ic), h('span', { class: 'msg' }, message));
  const close = () => { el.classList.add('leaving'); setTimeout(() => el.remove(), 200); };
  if (action) el.append(h('button', { onClick: () => { action.onClick(); close(); } }, action.label));
  host.append(el);
  if (timeout) setTimeout(close, timeout);
  return close;
}

export const toastError = (err) => toast(err?.message || String(err), { type: 'error', timeout: 6000 });

// ------------------------------------------------------------------ dialogs
export function modal({ title, body, actions = [], wide = false, onClose }) {
  const dialog = h('dialog');
  const close = (value) => { dialog.close(); dialog.remove(); onClose?.(value); };
  const foot = actions.length ? h('div', { class: 'modal-foot' }, actions.map((a) =>
    button(a.label, { variant: a.variant, icon: a.icon, onClick: () => a.onClick ? a.onClick(close) : close(a.value) }))) : null;
  dialog.append(h('div', { class: `modal${wide ? ' wide' : ''}` },
    h('div', { class: 'modal-head' }, h('h2', null, title), button('', { icon: 'x', variant: 'ghost', size: 'sm', title: 'Close', onClick: () => close(undefined) })),
    h('div', { class: 'modal-body' }, body),
    foot));
  dialog.addEventListener('cancel', (e) => { e.preventDefault(); close(undefined); });
  dialog.addEventListener('click', (e) => { if (e.target === dialog) close(undefined); });
  document.body.append(dialog);
  dialog.showModal();
  return { dialog, close };
}

export function confirmDialog({ title, message, confirmLabel = 'Confirm', danger = false }) {
  return new Promise((resolve) => {
    modal({
      title, body: h('p', null, message), onClose: (v) => resolve(v === true),
      actions: [
        { label: 'Cancel', variant: 'ghost', value: false },
        { label: confirmLabel, variant: danger ? 'danger-solid' : 'primary', value: true },
      ],
    });
  });
}

export function lightbox(src, caption = '') {
  const dialog = h('dialog', { class: 'lightbox-dialog' });
  const img = h('img', { src, alt: caption });
  const canvas = h('div', { class: 'canvas', onClick: () => canvas.classList.toggle('zoomed') }, img);
  const close = () => { dialog.close(); dialog.remove(); };
  dialog.append(h('div', { class: 'lightbox' },
    h('div', { class: 'bar' },
      h('span', { class: 'caption' }, caption),
      button('', { icon: 'download', size: 'sm', title: 'Save image', onClick: () => downloadUrl(src) }),
      button('', { icon: 'x', size: 'sm', title: 'Close', onClick: close })),
    canvas));
  dialog.addEventListener('close', () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

// ------------------------------------------------------------------ menu (popover)
export function openMenu(anchor, items) {
  document.querySelectorAll('.menu').forEach((m) => m.remove());
  const menu = h('div', { class: 'menu', role: 'menu' });
  for (const item of items) {
    if (item === '-') { menu.append(h('hr')); continue; }
    if (item.label && item.header) { menu.append(h('div', { class: 'menu-label' }, item.label)); continue; }
    menu.append(h('button', {
      role: 'menuitem', class: item.danger ? 'danger' : '',
      onClick: () => { close(); item.onClick(); },
    }, item.icon && icon(item.icon), item.label, item.hint && h('span', { class: 'hint' }, item.hint)));
  }
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  const mw = menu.offsetWidth, mh = menu.offsetHeight;
  let left = Math.min(r.right - mw, window.innerWidth - mw - 8);
  left = Math.max(8, left);
  let top = r.bottom + 6;
  if (top + mh > window.innerHeight - 8) top = r.top - mh - 6;
  Object.assign(menu.style, { left: `${left}px`, top: `${top}px` });
  menu.querySelector('button')?.focus();
  const onDoc = (e) => { if (!menu.contains(e.target) && e.target !== anchor) close(); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  function close() {
    menu.remove();
    document.removeEventListener('pointerdown', onDoc, true);
    document.removeEventListener('keydown', onKey);
  }
  setTimeout(() => { document.addEventListener('pointerdown', onDoc, true); document.addEventListener('keydown', onKey); });
  return close;
}

// ------------------------------------------------------------------ form controls
export function segmented({ options, value, onChange, full = false, label }) {
  const el = h('div', { class: `seg${full ? ' full' : ''}`, role: 'radiogroup', 'aria-label': label });
  const buttons = options.map((o) => h('button', {
    type: 'button', role: 'radio', title: o.title, 'aria-checked': String(o.value === value),
    class: o.value === value ? 'active' : '',
    onClick: () => { set(o.value); onChange?.(o.value); },
  }, o.icon && icon(o.icon, 'icon-sm'), o.label));
  el.append(...buttons);
  function set(v) {
    value = v;
    options.forEach((o, i) => {
      buttons[i].classList.toggle('active', o.value === v);
      buttons[i].setAttribute('aria-checked', String(o.value === v));
    });
  }
  el.setValue = set;
  return el;
}

export function toggle({ checked, onChange, label }) {
  const input = h('input', { type: 'checkbox', role: 'switch', checked, 'aria-label': label, onChange: () => onChange?.(input.checked) });
  const el = h('label', { class: 'switch' }, input, h('span', { class: 'track' }), h('span', { class: 'thumb' }));
  el.setValue = (v) => { input.checked = v; };
  el.input = input;
  return el;
}

export function selectBox({ options, value, onChange, label }) {
  const el = h('select', { class: 'select', 'aria-label': label, onChange: () => onChange?.(el.value) },
    options.map((o) => h('option', { value: o.value, selected: o.value === value }, o.label)));
  return el;
}

export function emptyState({ icon: ic, title, text, actions = [] }) {
  return h('div', { class: 'empty' },
    h('div', { class: 'bubble' }, icon(ic, 'icon-lg')),
    h('h2', null, title), text && h('p', null, text),
    actions.length ? h('div', { class: 'row', style: { marginTop: '8px' } }, actions) : null);
}

/** Click-or-drop file picker. */
export function dropzone({ title, hint, accept = 'image/*', multiple = true, compact = false, ic = 'upload', onFiles }) {
  const input = h('input', { type: 'file', accept, multiple, onChange: () => { if (input.files.length) onFiles([...input.files]); input.value = ''; } });
  const el = h('div', {
    class: `dropzone${compact ? ' compact' : ''}`, tabindex: 0, role: 'button',
    onClick: () => input.click(),
    onKeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } },
    onDragover: (e) => { e.preventDefault(); el.classList.add('drag'); },
    onDragleave: () => el.classList.remove('drag'),
    onDrop: (e) => {
      e.preventDefault(); e.stopPropagation(); el.classList.remove('drag');
      const files = [...e.dataTransfer.files].filter((f) => matchesAccept(f, accept));
      if (files.length) onFiles(multiple ? files : files.slice(0, 1));
    },
  }, h('div', { class: 'bubble' }, icon(ic, compact ? '' : 'icon-lg')), h('h2', null, title), hint && h('p', { class: 'subtle' }, hint), input);
  el.pick = () => input.click();
  return el;
}

export function matchesAccept(file, accept) {
  if (!accept || accept === '*') return true;
  return accept.split(',').some((a) => {
    a = a.trim();
    if (a.endsWith('/*')) return file.type.startsWith(a.slice(0, -1));
    if (a.startsWith('.')) return file.name.toLowerCase().endsWith(a);
    return file.type === a;
  });
}

/** Before/after comparison slider. */
export function compareSlider(beforeSrc, afterSrc, labels = ['Before', 'After']) {
  const after = h('div', { class: 'after' }, h('img', { src: afterSrc, alt: labels[1] }));
  const handle = h('div', { class: 'handle', role: 'slider', tabindex: 0, 'aria-label': 'Compare', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': 50 });
  const el = h('div', { class: 'compare' }, h('img', { src: beforeSrc, alt: labels[0] }), after, handle,
    h('span', { class: 'tag l' }, labels[0]), h('span', { class: 'tag r' }, labels[1]));
  const set = (pct) => {
    pct = Math.max(0, Math.min(100, pct));
    after.style.clipPath = `inset(0 0 0 ${pct}%)`;
    handle.style.left = `${pct}%`;
    handle.setAttribute('aria-valuenow', Math.round(pct));
  };
  const fromEvent = (e) => { const r = el.getBoundingClientRect(); set(((e.clientX - r.left) / r.width) * 100); };
  el.addEventListener('pointerdown', (e) => { el.setPointerCapture(e.pointerId); fromEvent(e); });
  el.addEventListener('pointermove', (e) => { if (el.hasPointerCapture(e.pointerId)) fromEvent(e); });
  handle.addEventListener('keydown', (e) => {
    const now = parseFloat(handle.style.left || '50');
    if (e.key === 'ArrowLeft') set(now - 5);
    if (e.key === 'ArrowRight') set(now + 5);
  });
  return el;
}

/** Fit a source of size (sw, sh) inside a box (bw, bh) like object-fit: contain. */
export function containRect(sw, sh, bw, bh) {
  const s = Math.min(bw / sw, bh / sh);
  const w = sw * s, hgt = sh * s;
  return { x: (bw - w) / 2, y: (bh - hgt) / 2, w, h: hgt };
}
