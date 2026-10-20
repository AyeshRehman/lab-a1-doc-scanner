// Pieces shared by several pages.
import { api } from '../lib/api.js';
import { downloadBlob, downloadUrl, h, icon, openMenu, relTime, toastError } from '../lib/ui.js';

export const MODE_LABELS = { color: 'Colour', gray: 'Gray', bw: 'B&W', original: 'Original' };

export const MODE_OPTIONS = [
  { value: 'color', label: 'Colour', title: 'Clean colour (1)' },
  { value: 'gray', label: 'Gray', title: 'Sharpened grayscale (2)' },
  { value: 'bw', label: 'B&W', title: 'Black & white, like a photocopy (3)' },
  { value: 'original', label: 'Original', title: 'Only straightened, no clean-up (4)' },
];

export const ASPECT_OPTIONS = [
  { value: 'auto', label: 'Automatic (measured)' },
  { value: 'a4', label: 'A4' },
  { value: 'letter', label: 'US Letter' },
  { value: 'legal', label: 'US Legal' },
  { value: 'free', label: 'As photographed' },
];

export function docCard(doc, { onOpen, selectable = false, selected = false, onToggle } = {}) {
  const card = h('div', { class: `doc-card${selected ? ' selected' : ''}`, tabindex: 0, role: 'button', 'aria-label': `Open ${doc.name}` },
    selectable && h('span', {
      class: 'check', role: 'checkbox', 'aria-checked': String(selected), title: 'Select',
      onClick: (e) => { e.stopPropagation(); onToggle?.(); },
    }, icon('check')),
    h('div', { class: 'thumb' }, doc.urls.thumb ? h('img', { src: doc.urls.thumb, alt: '', loading: 'lazy' }) : h('span', { class: 'spinner' })),
    h('div', { class: 'info' },
      h('div', { class: 'name', title: doc.name }, doc.name),
      h('div', { class: 'meta' }, relTime(doc.created), h('span', null, '·'), MODE_LABELS[doc.options.mode] || doc.options.mode)));
  card.addEventListener('click', (e) => (e.ctrlKey || e.metaKey) && selectable ? onToggle?.() : onOpen?.());
  card.addEventListener('keydown', (e) => { if (e.key === 'Enter') onOpen?.(); if (e.key === ' ' && selectable) { e.preventDefault(); onToggle?.(); } });
  return card;
}

export function downloadMenu(anchor, doc) {
  openMenu(anchor, [
    { label: 'Download as', header: true },
    { label: 'PDF document', icon: 'file', hint: '.pdf', onClick: () => downloadUrl(api.docs.downloadUrl(doc.id, 'pdf')) },
    { label: 'PNG image', icon: 'image', hint: 'lossless', onClick: () => downloadUrl(api.docs.downloadUrl(doc.id, 'png')) },
    { label: 'JPG image', icon: 'image', hint: 'smaller', onClick: () => downloadUrl(api.docs.downloadUrl(doc.id, 'jpg')) },
  ]);
}

export async function exportMany(ids, format) {
  try {
    const { blob, filename } = await api.docs.export(ids, format);
    downloadBlob(blob, filename);
  } catch (err) { toastError(err); }
}
