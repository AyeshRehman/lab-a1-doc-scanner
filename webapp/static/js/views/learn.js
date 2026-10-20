// "How it works": the pipeline step by step on one of your scans, plus the Module A1 topic figures.
import { api } from '../lib/api.js';
import { button, emptyState, h, icon, lightbox, segmented, selectBox, toastError } from '../lib/ui.js';

export default {
  async mount(root, { params, navigate }) {
    let docs = [];
    try { docs = await api.docs.list(); } catch (err) { toastError(err); }
    let docId = params[0] || docs[0]?.id || '';
    let tab = sessionStorage.getItem('docscan.learnTab') || 'pipeline';

    const content = h('div');
    const picker = selectBox({
      label: 'Scan to explain', value: docId,
      options: [...docs.map((d) => ({ value: d.id, label: d.name })), { value: '', label: 'Built-in sample photo' }],
      onChange: (v) => { docId = v; paint(); },
    });
    picker.style.maxWidth = '280px';
    const tabs = segmented({
      label: 'Section', value: tab,
      options: [{ value: 'pipeline', label: 'Step by step', icon: 'scan' }, { value: 'topics', label: 'Module A1 topics', icon: 'book' }],
      onChange: (v) => { tab = v; sessionStorage.setItem('docscan.learnTab', v); paint(); },
    });

    root.append(
      h('div', { class: 'page-header' },
        h('div', { class: 'titles' }, h('h1', null, 'How it works'),
          h('p', null, 'Every step uses classical computer vision - OpenCV and NumPy, no deep learning.')),
        h('div', { class: 'actions' }, picker)),
      h('div', { style: { marginBottom: '22px' } }, tabs),
      content);

    let token = 0;
    async function paint() {
      const my = ++token;
      if (tab === 'topics') return paintTopics();
      if (!docId) {
        content.replaceChildren(emptyState({
          icon: 'scan', title: 'Pick a scan to explain', text: 'The step-by-step view runs on one of your scans. Scan something first, or load the sample.',
          actions: [button('Scan the sample', { variant: 'primary', icon: 'sparkles', onClick: loadSample })],
        }));
        return;
      }
      content.replaceChildren(h('div', { class: 'stack' }, Array.from({ length: 3 }, () => h('div', { class: 'skeleton', style: { height: '200px' } }))));
      try {
        const { steps, found } = await api.docs.steps(docId);
        if (my !== token) return;
        const items = steps.map((s, i) => h('div', { class: 'tl-step' },
          h('div', { class: 'tl-rail' }, h('span', { class: 'step-num' }, String(i + 1)), i < steps.length - 1 && h('div', { class: 'line' })),
          h('div', { class: 'tl-content' },
            h('div', null, h('h3', null, s.title), h('p', null, s.text)),
            h('img', { src: s.image, alt: s.title, loading: 'lazy', onClick: () => lightbox(s.image, s.title) }))));
        content.replaceChildren(...[
          found ? null : h('p', { class: 'badge warning', style: { marginBottom: '16px' } }, 'No page was found automatically in this photo - later steps use the corners you set.'),
          h('div', { class: 'timeline' }, items),
          h('div', { class: 'row' }, button('Open this scan', { icon: 'arrowRight', onClick: () => navigate(`doc/${docId}`) })),
        ].filter(Boolean));
      } catch (err) { toastError(err); }
    }

    async function loadSample() {
      try {
        const { docs: [d] } = await api.importSample('synthetic_photo.jpg');
        navigate(`learn/${d.id}`);
      } catch (err) { toastError(err); }
    }

    let topics = null;
    async function paintTopics() {
      if (!topics) {
        try { topics = await api.topics(); } catch (err) { return toastError(err); }
      }
      content.replaceChildren(
        h('p', { class: 'muted', style: { marginBottom: '16px' } }, docId
          ? 'Each figure is generated from the selected scan. Click one to see it full size.'
          : 'Each figure is generated from the built-in sample photo. Click one to see it full size.'),
        h('div', { class: 'topic-grid' }, topics.map((t) => {
          const src = api.topicUrl(t.id, docId);
          const preview = h('div', { class: 'preview' }, h('span', { class: 'spinner' }));
          const img = new Image();
          img.onload = () => preview.replaceChildren(img);
          img.onerror = () => preview.replaceChildren(h('span', { class: 'subtle' }, 'Not available for this photo'));
          img.alt = t.title;
          img.src = src;
          return h('button', { class: 'topic', type: 'button', onClick: () => lightbox(src, t.title) },
            preview, h('div', { class: 'body' }, h('strong', null, t.title), h('span', null, t.text)));
        })));
    }

    paint();
  },
};
