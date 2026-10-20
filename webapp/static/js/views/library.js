// All scans: search, sort, select several, export as one PDF / ZIP, delete.
import { api } from '../lib/api.js';
import { settings } from '../lib/settings.js';
import { docCard, exportMany } from './shared.js';
import { button, confirmDialog, emptyState, h, icon, selectBox, toast, toastError } from '../lib/ui.js';

export default {
  async mount(root, { navigate }) {
    let docs = [];
    const selected = new Set();
    let query = '';

    const grid = h('div', { class: 'doc-grid' });
    const body = h('div');
    const countLabel = h('span', { class: 'count' });
    const bar = h('div', { class: 'selection-bar', role: 'toolbar', 'aria-label': 'Selected scans' },
      countLabel,
      button('PDF', { icon: 'file', size: 'sm', title: 'Combine into one PDF', onClick: () => exportMany(order([...selected]), 'pdf') }),
      button('ZIP', { icon: 'download', size: 'sm', title: 'Download PNGs in a ZIP', onClick: () => exportMany(order([...selected]), 'zip') }),
      button('Delete', { icon: 'trash', size: 'sm', variant: 'danger', onClick: removeSelected }),
      button('', { icon: 'x', size: 'sm', title: 'Clear selection', onClick: () => { selected.clear(); paint(); } }));
    document.body.append(bar);

    const search = h('input', {
      class: 'input', type: 'search', placeholder: 'Search scans', 'aria-label': 'Search scans',
      onInput: () => { query = search.value.trim().toLowerCase(); paint(); },
    });
    const sort = selectBox({
      label: 'Sort', value: settings.get('librarySort'),
      options: [{ value: 'new', label: 'Newest first' }, { value: 'old', label: 'Oldest first' }, { value: 'name', label: 'Name' }],
      onChange: (v) => { settings.set('librarySort', v); paint(); },
    });
    sort.style.width = 'auto';
    const selectAllBtn = button('Select all', { icon: 'checkSquare', variant: 'ghost', onClick: () => {
      const vis = visible();
      const all = vis.every((d) => selected.has(d.id));
      vis.forEach((d) => (all ? selected.delete(d.id) : selected.add(d.id)));
      paint();
    } });

    function order(ids) {          // export in the order shown on screen
      const pos = new Map(visible().map((d, i) => [d.id, i]));
      return ids.sort((a, b) => (pos.get(a) ?? 1e9) - (pos.get(b) ?? 1e9));
    }

    function visible() {
      let list = docs.filter((d) => !query || d.name.toLowerCase().includes(query));
      const s = settings.get('librarySort');
      if (s === 'old') list = [...list].sort((a, b) => a.created - b.created);
      if (s === 'name') list = [...list].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
      return list;
    }

    function paint() {
      const list = visible();
      if (!docs.length) {
        body.replaceChildren(emptyState({
          icon: 'library', title: 'No scans yet', text: 'Scans you make from photos or the live camera are kept here.',
          actions: [button('Scan a photo', { variant: 'primary', icon: 'upload', onClick: () => navigate('scan') }),
            button('Use the camera', { icon: 'camera', onClick: () => navigate('live') })],
        }));
      } else if (!list.length) {
        body.replaceChildren(emptyState({ icon: 'search', title: 'Nothing matches', text: `No scan is called "${query}".` }));
      } else {
        grid.replaceChildren(...list.map((d) => docCard(d, {
          selectable: true, selected: selected.has(d.id),
          onOpen: () => {
            if (selected.size) return toggle(d.id);
            sessionStorage.setItem('docscan.batch', JSON.stringify(list.map((x) => x.id)));
            navigate(`doc/${d.id}`);
          },
          onToggle: () => toggle(d.id),
        })));
        grid.classList.toggle('selecting', selected.size > 0);
        body.replaceChildren(grid);
      }
      countLabel.replaceChildren(h('span', null, `${selected.size} selected`));
      bar.classList.toggle('show', selected.size > 0);
      subtitle.textContent = docs.length ? `${docs.length} scan${docs.length === 1 ? '' : 's'}` : 'Your scans live here';
    }

    function toggle(docId) {
      selected.has(docId) ? selected.delete(docId) : selected.add(docId);
      paint();
    }

    async function removeSelected() {
      const n = selected.size;
      if (!await confirmDialog({ title: `Delete ${n} scan${n === 1 ? '' : 's'}?`, message: 'They will be removed permanently, including the original photos.', confirmLabel: 'Delete', danger: true })) return;
      for (const docId of [...selected]) {
        try { await api.docs.remove(docId); docs = docs.filter((d) => d.id !== docId); selected.delete(docId); } catch (err) { toastError(err); }
      }
      toast(`Deleted ${n} scan${n === 1 ? '' : 's'}`, { type: 'success' });
      paint();
    }

    const subtitle = h('p');
    root.append(
      h('div', { class: 'page-header' },
        h('div', { class: 'titles' }, h('h1', null, 'Library'), subtitle),
        h('div', { class: 'actions' }, button('New scan', { icon: 'plus', variant: 'primary', onClick: () => navigate('scan') }))),
      h('div', { class: 'row-wrap', style: { marginBottom: '18px' } },
        h('div', { class: 'search', style: { flex: '1', minWidth: '200px', maxWidth: '360px' } }, icon('search'), search),
        sort, h('span', { class: 'spacer' }), selectAllBtn),
      body);

    body.append(h('div', { class: 'doc-grid' }, Array.from({ length: 6 }, () => h('div', { class: 'skeleton', style: { aspectRatio: '4/5.6' } }))));
    try { docs = await api.docs.list(); } catch (err) { toastError(err); }
    paint();

    const onKey = (e) => {
      if (e.target.closest('input, select, textarea')) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') { e.preventDefault(); visible().forEach((d) => selected.add(d.id)); paint(); }
      if (e.key === 'Escape' && selected.size) { selected.clear(); paint(); }
      if (e.key === 'Delete' && selected.size) removeSelected();
      if (e.key === '/') { e.preventDefault(); search.focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => { bar.remove(); document.removeEventListener('keydown', onKey); };
  },
};
