// Home: add photos (drop, browse, paste) and jump back into recent scans.
import { api } from '../lib/api.js';
import { settings } from '../lib/settings.js';
import { docCard } from './shared.js';
import { button, dropzone, h, icon, matchesAccept, toast, toastError } from '../lib/ui.js';

export default {
  async mount(root, { navigate }) {
    const uploads = h('div', { class: 'card hidden' });
    const recent = h('div');

    async function handleFiles(files) {
      files = files.filter((f) => matchesAccept(f, 'image/*'));
      if (!files.length) return toast('Those files are not images.', { type: 'error' });
      const rows = files.map((f) => {
        const status = h('span', { class: 'spinner' });
        const row = h('div', { class: 'upload-item' }, icon('image'), h('span', { class: 'name' }, f.name), status);
        return { f, row, status };
      });
      uploads.replaceChildren(
        h('div', { class: 'card-head' }, h('h2', null, `Scanning ${files.length} photo${files.length > 1 ? 's' : ''}`)),
        h('div', { class: 'card-body upload-list' }, rows.map((r) => r.row)));
      uploads.classList.remove('hidden');

      const ids = [];
      for (const r of rows) {      // one at a time so each row reports its own result
        try {
          const { docs } = await api.docs.create([r.f], { source: 'upload', options: settings.scanOptions() });
          ids.push(docs[0].id);
          r.status.replaceWith(docs[0].detection
            ? h('span', { class: 'ok row' }, icon('check', 'icon-sm'), 'Page found')
            : h('span', { class: 'subtle' }, 'No page found - whole photo kept'));
        } catch (err) {
          r.status.replaceWith(h('span', { class: 'err' }, err.message));
        }
      }
      if (ids.length) {
        sessionStorage.setItem('docscan.batch', JSON.stringify(ids));
        navigate(`doc/${ids[0]}`);
      }
    }

    async function trySample() {
      try {
        const { photos } = await api.samples();
        const name = photos.find((p) => p === 'synthetic_photo.jpg') || photos[0];
        toast('Loading the sample photo…');
        const { docs } = await api.importSample(name, settings.scanOptions());
        sessionStorage.setItem('docscan.batch', JSON.stringify([docs[0].id]));
        navigate(`doc/${docs[0].id}`);
      } catch (err) { toastError(err); }
    }

    const zone = dropzone({
      title: 'Drop photos of documents here',
      hint: 'or click to browse · paste an image with Ctrl+V · several at once is fine',
      onFiles: handleFiles,
    });

    root.append(
      h('div', { class: 'page-header' },
        h('div', { class: 'titles' }, h('h1', null, 'Scan a document'),
          h('p', null, 'Add a photo of a page. The edges are found automatically, the perspective is straightened and the page is cleaned up.'))),
      h('div', { class: 'home-grid' },
        zone,
        h('div', { class: 'quick-actions' },
          quick('camera', 'Use the camera', 'Scan live with your webcam', () => navigate('live')),
          quick('sparkles', 'Try a sample', 'See it work on a test photo', trySample),
          quick('layers', 'Scan a known form', 'Match it to a clean template', () => navigate('align')),
        ),
        uploads,
        recent,
      ));

    // paste an image from the clipboard
    const onPaste = (e) => {
      const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/'));
      if (files.length) { e.preventDefault(); handleFiles(files.map((f, i) => new File([f], f.name && f.name !== 'image.png' ? f.name : `Pasted ${i + 1}.png`, { type: f.type }))); }
    };
    // drop anywhere on the page
    const overlay = h('div', { class: 'page-drop' }, h('div', { class: 'panel' }, icon('upload'), 'Drop to scan'));
    document.body.append(overlay);
    let depth = 0;
    const isFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
    const onEnter = (e) => { if (isFiles(e)) { depth++; overlay.classList.add('show'); } };
    const onLeave = () => { depth = Math.max(0, depth - 1); if (!depth) overlay.classList.remove('show'); };
    const onOver = (e) => { if (isFiles(e)) e.preventDefault(); };
    const onDrop = (e) => {
      depth = 0; overlay.classList.remove('show');
      if (!isFiles(e)) return;
      e.preventDefault();
      handleFiles([...e.dataTransfer.files]);
    };
    document.addEventListener('paste', onPaste);
    window.addEventListener('dragenter', onEnter);
    window.addEventListener('dragleave', onLeave);
    window.addEventListener('dragover', onOver);
    window.addEventListener('drop', onDrop);

    // recent scans
    try {
      const docs = (await api.docs.list()).slice(0, 6);
      if (docs.length) {
        recent.append(
          h('div', { class: 'section-head' }, h('h2', null, 'Recent scans'),
            button('View all', { variant: 'ghost', size: 'sm', icon: 'arrowRight', onClick: () => navigate('library') })),
          h('div', { class: 'doc-grid' }, docs.map((d) => docCard(d, { onOpen: () => navigate(`doc/${d.id}`) }))));
      }
    } catch (err) { toastError(err); }

    return () => {
      document.removeEventListener('paste', onPaste);
      window.removeEventListener('dragenter', onEnter);
      window.removeEventListener('dragleave', onLeave);
      window.removeEventListener('dragover', onOver);
      window.removeEventListener('drop', onDrop);
      overlay.remove();
    };
  },
};

function quick(ic, title, text, onClick) {
  return h('button', { class: 'quick', type: 'button', onClick },
    h('span', { class: 'bubble' }, icon(ic)), h('span', null, h('strong', null, title), h('span', null, text)));
}
