// Align a photo of a known form to its clean original with ORB / SIFT + homography.
import { api } from '../lib/api.js';
import { settings } from '../lib/settings.js';
import { button, dropzone, h, icon, lightbox, segmented, toast, toastError } from '../lib/ui.js';

export default {
  async mount(root, { navigate }) {
    const files = { template: null, image: null };
    let method = 'orb', ratio = 0.75, result = null, view = 'aligned';

    const slots = {};
    for (const [key, title, hint] of [
      ['template', 'The clean original', 'A scan or PDF export of the blank form'],
      ['image', 'The photo to align', 'A photo of the same page, from any angle'],
    ]) {
      const host = h('div');
      const zone = dropzone({ title: 'Drop or click to add', hint, multiple: false, compact: true, ic: 'image', onFiles: ([f]) => setFile(key, f) });
      host.append(zone);
      slots[key] = { host, zone };
      slots[key].wrap = h('div', null, h('div', { class: 'slot-label' }, h('span', { class: 'step-num' }, key === 'template' ? '1' : '2'), title), host);
    }

    function setFile(key, file) {
      files[key] = file;
      const url = URL.createObjectURL(file);
      const slot = slots[key];
      const replace = button('Replace', { size: 'sm', icon: 'upload', onClick: (e) => { e.stopPropagation(); slot.zone.pick(); } });
      slot.host.replaceChildren(h('div', { class: 'dropzone has-image', onClick: () => slot.zone.pick() }, h('img', { src: url, alt: file.name }), h('div', { class: 'replace' }, replace)));
      slot.host.append(slot.zone);
      slot.zone.classList.add('hidden');
      runBtn.disabled = !(files.template && files.image);
    }

    async function useSample() {
      try {
        const { photos, template } = await api.samples();
        const photo = photos.includes('synthetic_photo_rotated.jpg') ? 'synthetic_photo_rotated.jpg' : photos[0];
        const [t, p] = await Promise.all([
          fetch(`/api/samples/templates/${template}`).then((r) => r.blob()),
          fetch(`/api/samples/photos/${photo}`).then((r) => r.blob()),
        ]);
        setFile('template', new File([t], template, { type: 'image/png' }));
        setFile('image', new File([p], photo, { type: 'image/jpeg' }));
      } catch (err) { toastError(err); }
    }

    const methodSeg = segmented({
      label: 'Feature detector', value: method,
      options: [{ value: 'orb', label: 'ORB', title: 'Fast binary features' }, { value: 'sift', label: 'SIFT', title: 'Slower, more robust' }],
      onChange: (v) => { method = v; },
    });
    const ratioInput = h('input', { type: 'range', min: 0.5, max: 0.95, step: 0.05, value: ratio, style: { width: '140px', accentColor: 'var(--accent)' } });
    const ratioLabel = h('span', { class: 'mono' }, ratio.toFixed(2));
    ratioInput.addEventListener('input', () => { ratio = Number(ratioInput.value); ratioLabel.textContent = ratio.toFixed(2); });

    const runBtn = button('Align', { variant: 'primary', icon: 'zap', disabled: true, onClick: run });
    const out = h('div');

    async function run() {
      runBtn.disabled = true;
      runBtn.replaceChildren(h('span', { class: 'spinner' }), 'Matching…');
      try {
        result = await api.align(files.template, files.image, method, ratio);
        paintResult();
        if (!result.ok) toast('Not enough matching points. Try SIFT, or a higher ratio.', { type: 'error' });
      } catch (err) { toastError(err); } finally {
        runBtn.disabled = false;
        runBtn.replaceChildren(icon('zap'), 'Align');
      }
    }

    function paintResult() {
      const r = result;
      const stat = (value, label) => h('div', { class: 'stat' }, h('span', { class: 'value' }, value), h('span', { class: 'label' }, label));
      const tabs = segmented({
        label: 'Result view', value: r.ok ? view : 'matches',
        options: [
          r.ok && { value: 'aligned', label: 'Aligned' },
          { value: 'matches', label: 'Matches' },
          r.ok && { value: 'diff', label: 'Differences' },
        ].filter(Boolean),
        onChange: (v) => { view = v; paintImage(); },
      });
      const imgBox = h('div', { class: 'result-image' });
      const caption = h('p', { class: 'subtle', style: { marginTop: '10px' } });
      function paintImage() {
        const v = r.ok ? view : 'matches';
        const src = { aligned: r.aligned, matches: r.matches_image, diff: r.diff }[v];
        caption.textContent = {
          aligned: 'The photo warped into the template\'s frame by the RANSAC homography.',
          matches: 'Green lines join keypoints that survived the ratio test and RANSAC (inliers).',
          diff: 'Bright areas differ from the template - handwriting, stamps or filled-in fields show up here.',
        }[v];
        imgBox.replaceChildren(h('img', { src, alt: v, onClick: () => lightbox(src, v) }));
      }
      paintImage();
      out.replaceChildren(h('section', { class: 'card', style: { marginTop: '20px' } },
        h('div', { class: 'card-head' }, h('h2', null, 'Result'),
          r.ok ? h('span', { class: 'badge success' }, h('span', { class: 'dot' }), 'Aligned') : h('span', { class: 'badge danger' }, h('span', { class: 'dot' }), 'Failed'),
          r.ok && button('Save to library', { size: 'sm', icon: 'plus', onClick: save })),
        h('div', { class: 'card-body stack' },
          h('div', { class: 'stats' },
            stat(r.keypoints.photo.toLocaleString(), 'keypoints in photo'),
            stat(r.keypoints.template.toLocaleString(), 'keypoints in template'),
            stat(r.matches.toLocaleString(), 'good matches'),
            stat(r.inliers.toLocaleString(), 'RANSAC inliers'),
            stat(`${r.ms} ms`, `${r.method.toUpperCase()} time`)),
          tabs, imgBox, caption)));
    }

    async function save() {
      try {
        const blob = await fetch(result.aligned).then((r) => r.blob());
        const name = (files.image.name || 'aligned').replace(/\.[^.]+$/, '');
        const { docs } = await api.docs.create([new File([blob], `${name} (aligned).jpg`, { type: 'image/jpeg' })],
          { source: 'align', detect: 0, options: settings.scanOptions() });
        toast('Saved to library', { type: 'success', action: { label: 'Open', onClick: () => navigate(`doc/${docs[0].id}`) } });
      } catch (err) { toastError(err); }
    }

    root.append(
      h('div', { class: 'page-header' },
        h('div', { class: 'titles' }, h('h1', null, 'Align to template'),
          h('p', null, 'For forms you already have a clean copy of. Matching printed details (keypoints) lines the photo up exactly - even when the page edges are not visible.')),
        h('div', { class: 'actions' }, button('Use sample pair', { icon: 'sparkles', variant: 'ghost', onClick: useSample }))),
      h('div', { class: 'two-up' }, slots.template.wrap, slots.image.wrap),
      h('div', { class: 'row-wrap', style: { marginTop: '18px', gap: '16px' } },
        h('div', { class: 'row' }, h('span', { class: 'field-label' }, 'Detector'), methodSeg),
        h('label', { class: 'row', title: "Lowe's ratio test: lower is stricter" }, h('span', { class: 'field-label' }, 'Match strictness'), ratioInput, ratioLabel),
        h('span', { class: 'spacer' }), runBtn),
      out);
  },
};
