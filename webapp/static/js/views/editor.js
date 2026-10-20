// Edit one scan: drag corners, pick the look, rotate, download.
import { api } from '../lib/api.js';
import { CornerEditor } from '../components/corner-editor.js';
import { ASPECT_OPTIONS, MODE_OPTIONS, downloadMenu } from './shared.js';
import { button, confirmDialog, debounce, h, icon, lightbox, openMenu, segmented, selectBox, toast, toastError, toggle } from '../lib/ui.js';

export default {
  async mount(root, { params, navigate }) {
    const id = params[0];
    let doc;
    try { doc = await api.docs.get(id); } catch (err) {
      root.append(h('div', { class: 'empty' }, h('h2', null, 'Scan not found'), h('p', null, 'It may have been deleted.'),
        button('Go to library', { variant: 'primary', onClick: () => navigate('library') })));
      return;
    }

    const history = [];          // corner undo stack
    let requestId = 0;

    // ---------------------------------------------------------------- header
    const title = h('input', { class: 'title-input', value: doc.name, 'aria-label': 'Scan name', maxlength: 120 });
    const saveName = async () => {
      const name = title.value.trim();
      if (!name || name === doc.name) { title.value = doc.name; return; }
      try { doc = await api.docs.rename(id, name); toast('Renamed', { type: 'success', timeout: 1800 }); } catch (err) { toastError(err); }
    };
    title.addEventListener('blur', saveName);
    title.addEventListener('keydown', (e) => { if (e.key === 'Enter') title.blur(); if (e.key === 'Escape') { title.value = doc.name; title.blur(); } });

    const batch = JSON.parse(sessionStorage.getItem('docscan.batch') || '[]');
    const pos = batch.indexOf(id);
    const pager = pos >= 0 && batch.length > 1 ? h('div', { class: 'pager' },
      button('', { icon: 'chevronLeft', variant: 'ghost', size: 'sm', title: 'Previous photo', disabled: pos === 0, onClick: () => navigate(`doc/${batch[pos - 1]}`) }),
      h('span', null, `${pos + 1} of ${batch.length}`),
      button('', { icon: 'chevronRight', variant: 'ghost', size: 'sm', title: 'Next photo', disabled: pos === batch.length - 1, onClick: () => navigate(`doc/${batch[pos + 1]}`) }),
    ) : null;

    const downloadBtn = button('Download', { icon: 'download', variant: 'primary', onClick: () => downloadMenu(downloadBtn, doc) });
    const moreBtn = button('', {
      icon: 'more', title: 'More actions', onClick: () => openMenu(moreBtn, [
        { label: 'See how it was scanned', icon: 'book', onClick: () => navigate(`learn/${id}`) },
        { label: 'Open full size', icon: 'maximize', onClick: () => lightbox(doc.urls.preview, doc.name) },
        '-',
        { label: 'Delete scan', icon: 'trash', danger: true, onClick: remove },
      ]),
    });

    async function remove() {
      if (!await confirmDialog({ title: 'Delete this scan?', message: `"${doc.name}" and its original photo will be removed permanently.`, confirmLabel: 'Delete', danger: true })) return;
      try {
        await api.docs.remove(id);
        sessionStorage.setItem('docscan.batch', JSON.stringify(batch.filter((b) => b !== id)));
        toast('Scan deleted', { type: 'success' });
        navigate('library');
      } catch (err) { toastError(err); }
    }

    // ---------------------------------------------------------------- corner editor
    const editor = new CornerEditor({
      src: doc.urls.original, corners: doc.corners,
      onChange: (c) => { history.push(doc.corners); render({ corners: c }); },
    });
    const detectInfo = h('p', { class: 'subtle' });
    const paintDetectInfo = () => {
      const d = doc.detection;
      if (!doc.corners) detectInfo.textContent = 'Using the whole photo. Drag the corners to crop to the page.';
      else if (d?.method === 'live') detectInfo.textContent = 'Corners from the live camera, refined on the full photo. Drag to adjust.';
      else if (d) detectInfo.textContent = `Found by ${d.method === 'color' ? 'paper colour' : d.method === 'hough' ? 'straight lines' : 'edges'}${d.area ? ` · page covers ${Math.round(d.area * 100)}% of the photo` : ''}. Drag a corner or edge to adjust.`;
      else detectInfo.textContent = 'Corners set by hand. Drag to adjust.';
    };
    paintDetectInfo();

    const autoBtn = button('Auto-detect', { icon: 'sparkles', size: 'sm', variant: 'ghost', title: 'Find the page again (D)', onClick: redetect });
    const fullBtn = button('Whole photo', { icon: 'maximize', size: 'sm', variant: 'ghost', title: 'Use the entire photo (F)', onClick: () => { history.push(doc.corners); editor.setCorners(null); render({ corners: null }); } });
    const undoBtn = button('', { icon: 'undo', size: 'sm', variant: 'ghost', title: 'Undo corner change (Ctrl+Z)', onClick: undo, disabled: true });

    async function redetect() {
      autoBtn.disabled = true;
      try {
        const res = await api.docs.detect(id);
        if (res.found) {
          history.push(doc.corners);
          doc = res;
          editor.setCorners(doc.corners);
          showResult();
          toast('Page found', { type: 'success', timeout: 1800 });
        } else {
          doc.detection = res.detection;
          toast('No page found automatically - drag the corners by hand.', { type: 'error' });
        }
        paintDetectInfo();
      } catch (err) { toastError(err); } finally { autoBtn.disabled = false; }
    }

    function undo() {
      if (!history.length) return;
      const prev = history.pop();
      editor.setCorners(prev);
      render({ corners: prev });
    }

    // ---------------------------------------------------------------- result + options
    const resultImg = h('img', { alt: 'Scanned page', onClick: () => lightbox(doc.urls.preview, doc.name) });
    const resultWrap = h('div', { class: 'result-wrap' }, resultImg, h('div', { class: 'busy' }, h('span', { class: 'spinner lg' })));
    const notes = h('div', { class: 'note-list' });
    const sizeInfo = h('span', { class: 'subtle' });

    const mode = segmented({ options: MODE_OPTIONS, value: doc.options.mode, full: true, label: 'Scan look', onChange: (v) => render({ options: { mode: v } }) });
    const aspect = selectBox({ options: ASPECT_OPTIONS, value: doc.options.aspect, label: 'Page size', onChange: (v) => render({ options: { aspect: v } }) });
    const deskew = toggle({ checked: doc.options.deskew, label: 'Straighten text', onChange: (v) => render({ options: { deskew: v } }) });
    const holes = toggle({ checked: doc.options.holes, label: 'Remove punch holes', onChange: (v) => render({ options: { holes: v } }) });
    const rotate = (delta) => render({ options: { rotate: (doc.options.rotate + delta + 360) % 360 } });

    function showResult() {
      resultImg.src = doc.urls.preview;
      sizeInfo.textContent = doc.scan ? `${doc.scan.width} × ${doc.scan.height} px` : '';
      notes.replaceChildren(...(doc.notes || []).map((n) => h('span', { class: 'badge accent' }, icon('check', 'icon-sm'), n)));
      undoBtn.disabled = !history.length;
    }

    // changes made in quick succession are merged and sent as one request
    let pending = {};
    const flush = debounce(async () => {
      const body = pending;
      pending = {};
      const mine = ++requestId;
      try {
        const res = await api.docs.process(id, body);
        if (mine !== requestId) return;      // a newer request is on its way
        doc = res;
        showResult();
        paintDetectInfo();
      } catch (err) { toastError(err); } finally {
        if (mine === requestId) resultWrap.classList.remove('loading');
      }
    }, 120);

    function render(change) {
      if (change.options) {
        doc.options = { ...doc.options, ...change.options };
        pending.options = { ...(pending.options || {}), ...change.options };
      }
      if ('corners' in change) { doc.corners = change.corners; pending.corners = change.corners; }
      resultWrap.classList.add('loading');
      flush();
    }

    const optionRow = (label, sub, control) => h('div', { class: 'option-toggle' },
      h('div', { class: 'text' }, h('div', null, label), h('div', { class: 'subtle' }, sub)), control);

    root.append(
      h('div', { class: 'page-header' },
        h('div', { class: 'row', style: { flex: 1, minWidth: '260px' } },
          button('', { icon: 'arrowLeft', variant: 'ghost', title: 'Back to library', onClick: () => navigate('library') }),
          title),
        h('div', { class: 'actions' }, pager, moreBtn, downloadBtn)),
      h('div', { class: 'editor-grid' },
        h('section', { class: 'card' },
          h('div', { class: 'card-head' }, h('h2', null, 'Page edges'), undoBtn, fullBtn, autoBtn),
          h('div', { class: 'card-body canvas-body' }, editor.el),
          h('div', { class: 'card-foot' }, detectInfo)),
        h('section', { class: 'card' },
          h('div', { class: 'card-head' }, h('h2', null, 'Result'), sizeInfo,
            button('', { icon: 'rotateCcw', size: 'sm', variant: 'ghost', title: 'Rotate left ([)', onClick: () => rotate(-90) }),
            button('', { icon: 'rotateCw', size: 'sm', variant: 'ghost', title: 'Rotate right (])', onClick: () => rotate(90) })),
          h('div', { class: 'card-body canvas-body' }, resultWrap)),
        h('aside', { class: 'card options-panel' },
          h('div', { class: 'card-head' }, h('h2', null, 'Look')),
          h('div', { class: 'card-body' },
            h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Style'), mode),
            h('div', { class: 'field' }, h('label', null, 'Page size'), aspect),
            optionRow('Straighten text', 'Fix a slight tilt using the text lines', deskew),
            optionRow('Remove punch holes', 'Paint out binder holes near the edges', holes),
            notes))));

    showResult();

    // ---------------------------------------------------------------- shortcuts
    const onKey = (e) => {
      if (e.target.closest('input, select, textarea') || e.target === editor.canvas) return;
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); undo(); return; }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (['1', '2', '3', '4'].includes(k)) { const v = MODE_OPTIONS[Number(k) - 1].value; mode.setValue(v); render({ options: { mode: v } }); }
      else if (k === '[') rotate(-90);
      else if (k === ']') rotate(90);
      else if (k === 'd') redetect();
      else if (k === 'f') fullBtn.click();
      else if (k === 'arrowright' && pager && pos < batch.length - 1) navigate(`doc/${batch[pos + 1]}`);
      else if (k === 'arrowleft' && pager && pos > 0) navigate(`doc/${batch[pos - 1]}`);
    };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); editor.destroy(); flush.cancel(); };
  },
};
