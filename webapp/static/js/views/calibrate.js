// Camera calibration with a chessboard: show board -> capture views -> solve.
import { api } from '../lib/api.js';
import { Webcam, cameraErrorMessage } from '../lib/camera.js';
import { button, compareSlider, confirmDialog, containRect, h, icon, lightbox, toast, toastError, toggle } from '../lib/ui.js';

const RECOMMENDED = 12;

export default {
  async mount(root) {
    let pattern = '9x6';
    let state = { count: 0, thumbs: [], calibration: null };
    let serverSettings = { use_calibration: false };
    let found = null, running = false, gen = 0;

    try {
      const [s, st] = await Promise.all([api.calib.status(), api.status()]);
      state = s;
      serverSettings = st.settings;
    } catch (err) { toastError(err); }

    // ---------------------------------------------------------------- step 1
    const boardUrl = '/api/samples/board/chessboard_9x6.png';
    const step1 = h('section', { class: 'card step-card' },
      h('div', { class: 'card-head' }, h('h2', null, h('span', { class: 'step-num' }, '1'), 'Get a chessboard')),
      h('div', { class: 'card-body row-wrap', style: { gap: '20px', alignItems: 'flex-start' } },
        h('img', { src: boardUrl, alt: 'Chessboard', style: { width: '180px', borderRadius: '6px', border: '1px solid var(--border)', cursor: 'zoom-in' }, onClick: () => lightbox(boardUrl, 'Calibration chessboard (9 x 6 inner corners)') }),
        h('div', { class: 'stack', style: { flex: 1, minWidth: '240px' } },
          h('p', { class: 'muted' }, 'Print this board, or open it full-screen on a tablet or second monitor. Keep it flat - a wavy board gives a poor calibration.'),
          h('div', { class: 'row-wrap' },
            button('Download board', { icon: 'download', onClick: () => { const a = h('a', { href: boardUrl, download: 'chessboard_9x6.png' }); a.click(); } }),
            button('Show full-screen', { icon: 'maximize', variant: 'ghost', onClick: () => lightbox(boardUrl, 'Calibration chessboard') })),
          h('p', { class: 'subtle' }, 'Pattern: 9 × 6 inner corners (the points where four squares meet).'))));

    // ---------------------------------------------------------------- step 2
    const video = h('video', { playsinline: true, muted: true });
    const overlay = h('canvas', { class: 'overlay' });
    const flash = h('div', { class: 'flash' });
    const pill = h('div', { class: 'pill' }, h('span', { class: 'dot' }), h('span', { class: 'label' }, 'Camera off'));
    const emptyBox = h('div', { class: 'stage-empty' },
      icon('camera', 'icon-lg'), h('h2', null, 'Capture the board from different angles'),
      h('p', null, 'Tilt it, move it to the corners of the frame, nearer and further. About a dozen varied views is ideal.'),
      button('Start camera', { variant: 'primary', icon: 'camera', onClick: startCamera }));
    const stage = h('div', { class: 'stage' }, video, overlay, flash, pill, emptyBox);
    const webcam = new Webcam(video);

    const captureBtn = button('Capture view', { variant: 'primary', icon: 'plus', disabled: true, onClick: captureView });
    const uploadInput = h('input', { type: 'file', accept: 'image/*', multiple: true, class: 'hidden', onChange: () => uploadViews([...uploadInput.files]) });
    const meter = h('div', { class: 'meter' }, h('div'));
    const countLabel = h('span', { class: 'subtle' });
    const thumbs = h('div', { class: 'view-thumbs' });

    const step2 = h('section', { class: 'card step-card' },
      h('div', { class: 'card-head' }, h('h2', null, h('span', { class: 'step-num' }, '2'), 'Capture views'),
        button('Upload photos', { icon: 'upload', size: 'sm', variant: 'ghost', onClick: () => uploadInput.click() }),
        button('Clear', { icon: 'trash', size: 'sm', variant: 'ghost', onClick: resetViews }), uploadInput),
      h('div', { class: 'card-body calib-layout' },
        h('div', null, stage, h('div', { class: 'row', style: { justifyContent: 'center', marginTop: '14px' } }, captureBtn)),
        h('div', { class: 'stack' }, h('div', { class: 'row' }, h('strong', null, 'Views'), h('span', { class: 'spacer' }), countLabel), meter, thumbs)));

    // ---------------------------------------------------------------- step 3
    const runBtn = button('Calibrate', { variant: 'primary', icon: 'zap', onClick: run });
    const resultBox = h('div', { class: 'stack' });
    const step3 = h('section', { class: 'card step-card' },
      h('div', { class: 'card-head' }, h('h2', null, h('span', { class: 'step-num' }, '3'), 'Solve and use'), runBtn),
      h('div', { class: 'card-body' }, resultBox));

    root.append(
      h('div', { class: 'page-header' },
        h('div', { class: 'titles' }, h('h1', null, 'Calibrate camera'),
          h('p', null, 'Measure your lens once so its distortion can be removed. Straight page edges then stay straight, and page proportions come out more accurate.'))),
      h('div', { class: 'steps' }, step1, step2, step3));

    function paintViews() {
      const n = state.count;
      countLabel.textContent = `${n} / ${RECOMMENDED} recommended`;
      meter.firstChild.style.width = `${Math.min(100, (n / RECOMMENDED) * 100)}%`;
      thumbs.replaceChildren(...state.thumbs.map((src, i) => h('div', { class: 'view-thumb' },
        h('img', { src, alt: `View ${i + 1}` }),
        h('button', { title: 'Remove view', onClick: async () => { state = await api.calib.removeView(i); paintViews(); } }, icon('x')))));
      if (!n) thumbs.append(h('p', { class: 'subtle', style: { gridColumn: '1 / -1' } }, 'No views yet. Views with the board found are added here.'));
      step2.classList.toggle('done', n >= 5);
      runBtn.disabled = n < 5;
      runBtn.title = n < 5 ? 'Capture at least 5 views first' : '';
    }

    function paintCalibration(cal, before, after) {
      if (!cal) {
        resultBox.replaceChildren(h('p', { class: 'muted' }, 'With at least 5 views captured, press Calibrate. The result is saved and can be applied to every camera scan.'));
        step3.classList.remove('done');
        return;
      }
      step3.classList.add('done');
      const quality = cal.rms < 0.5 ? ['success', 'Excellent'] : cal.rms < 1 ? ['accent', 'Good'] : ['warning', 'Rough - recapture with more varied views'];
      const K = cal.K;
      const useToggle = toggle({ checked: serverSettings.use_calibration, label: 'Apply to camera scans', onChange: async (v) => {
        try { serverSettings = await api.setServerSettings({ use_calibration: v }); toast(v ? 'Lens correction on for camera scans' : 'Lens correction off', { type: 'success' }); } catch (err) { toastError(err); }
      } });
      resultBox.replaceChildren(...[
        h('div', { class: 'row-wrap' }, h('span', { class: `badge ${quality[0]}` }, h('span', { class: 'dot' }), quality[1]),
          h('span', { class: 'subtle' }, `${cal.views || '?'} views · ${cal.size?.join(' × ')} px${cal.date ? ` · ${new Date(cal.date * 1000).toLocaleString()}` : ''}`)),
        h('div', { class: 'stats' },
          stat(`${cal.rms.toFixed(3)} px`, 'reprojection error (RMS)'),
          K && stat(`${K[0][0].toFixed(0)} px`, 'focal length fx'),
          K && stat(`${K[1][1].toFixed(0)} px`, 'focal length fy'),
          K && stat(`${K[0][2].toFixed(0)}, ${K[1][2].toFixed(0)}`, 'principal point')),
        K && h('div', null, h('div', { class: 'field-label', style: { marginBottom: '6px' } }, 'Camera matrix K'),
          h('div', { class: 'matrix' }, K.flat().map((v) => h('span', null, Number(v).toFixed(1))))),
        cal.dist && h('p', { class: 'subtle mono' }, `distortion k1 k2 p1 p2 k3 = ${cal.dist.map((v) => v.toFixed(4)).join('  ')}`),
        before && h('div', null, h('div', { class: 'field-label', style: { marginBottom: '6px' } }, 'Drag to compare'), compareSlider(before, after, ['Original', 'Undistorted'])),
        h('div', { class: 'setting-row', style: { borderTop: '1px solid var(--border)', paddingTop: '14px' } },
          h('div', { class: 'text' }, h('div', null, 'Apply to camera scans'), h('div', { class: 'subtle' }, 'Undistort frames from the live camera and IP cameras before scanning.')),
          useToggle),
        h('div', null, button('Remove calibration', { variant: 'danger', size: 'sm', icon: 'trash', onClick: removeCalibration })),
      ].filter(Boolean));
    }

    const stat = (value, label) => h('div', { class: 'stat' }, h('span', { class: 'value' }, value), h('span', { class: 'label' }, label));

    // ---------------------------------------------------------------- camera
    async function startCamera() {
      const my = ++gen;
      pill.querySelector('.label').textContent = 'Starting camera…';
      try {
        await webcam.start({ height: 1080 });
        if (my !== gen) return;
        emptyBox.classList.add('hidden');
        running = true;
        detectLoop(my);
        drawLoop(my);
      } catch (err) {
        emptyBox.querySelector('p').textContent = cameraErrorMessage(err);
      }
    }

    async function detectLoop(my) {
      while (running && my === gen) {
        try {
          const blob = await webcam.grab(800, 0.75);
          const res = await api.calib.detect(blob, pattern);
          if (my !== gen) return;
          found = res.found ? res.corners : null;
          captureBtn.disabled = !found;
          pill.className = `pill ${found ? 'stable' : ''}`;
          pill.querySelector('.label').textContent = found ? 'Board found - capture this view' : 'Show the whole board to the camera';
        } catch { await new Promise((r) => setTimeout(r, 500)); }
      }
    }

    function drawLoop(my) {
      const ctx = overlay.getContext('2d');
      const frame = () => {
        if (my !== gen) return;
        const dpr = window.devicePixelRatio || 1, bw = overlay.clientWidth, bh = overlay.clientHeight;
        if (overlay.width !== Math.round(bw * dpr)) { overlay.width = Math.round(bw * dpr); overlay.height = Math.round(bh * dpr); }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, bw, bh);
        if (found && video.videoWidth) {
          const r = containRect(video.videoWidth, video.videoHeight, bw, bh);
          const cols = Number(pattern.split('x')[0]);
          found.forEach(([x, y], i) => {
            ctx.beginPath();
            ctx.arc(r.x + x * r.w, r.y + y * r.h, 4, 0, Math.PI * 2);
            ctx.fillStyle = `hsl(${(Math.floor(i / cols) * 47) % 360} 85% 60%)`;
            ctx.fill();
          });
        }
        requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    }

    async function captureView() {
      captureBtn.disabled = true;
      flash.classList.remove('go'); void flash.offsetWidth; flash.classList.add('go');
      try {
        const blob = await webcam.grab(Infinity, 0.95);
        const res = await api.calib.addViews([new File([blob], 'view.jpg', { type: 'image/jpeg' })], pattern);
        state = res;
        paintViews();
        if (!res.added) toast('The board was not found at full resolution - hold it still and try again.', { type: 'error' });
      } catch (err) { toastError(err); }
    }

    async function uploadViews(files) {
      if (!files.length) return;
      try {
        toast(`Checking ${files.length} photo${files.length > 1 ? 's' : ''}…`);
        const res = await api.calib.addViews(files, pattern);
        state = res;
        paintViews();
        toast(`${res.added} view${res.added === 1 ? '' : 's'} added${res.rejected ? `, ${res.rejected} skipped (board not found or different size)` : ''}`, { type: res.added ? 'success' : 'error' });
      } catch (err) { toastError(err); } finally { uploadInput.value = ''; }
    }

    async function resetViews() {
      state = await api.calib.reset();
      paintViews();
    }

    async function run() {
      runBtn.disabled = true;
      runBtn.replaceChildren(h('span', { class: 'spinner' }), 'Solving…');
      try {
        const res = await api.calib.run(pattern, 1);
        state.calibration = res.calibration;
        paintCalibration(res.calibration, res.before, res.after);
        toast('Calibration saved', { type: 'success' });
      } catch (err) { toastError(err); } finally {
        runBtn.disabled = state.count < 5;
        runBtn.replaceChildren(icon('zap'), 'Calibrate');
      }
    }

    async function removeCalibration() {
      if (!await confirmDialog({ title: 'Remove calibration?', message: 'Camera scans will no longer be corrected for lens distortion.', confirmLabel: 'Remove', danger: true })) return;
      try {
        await api.calib.remove();
        serverSettings.use_calibration = false;
        state.calibration = null;
        paintCalibration(null);
      } catch (err) { toastError(err); }
    }

    paintViews();
    paintCalibration(state.calibration);

    return () => { running = false; gen++; webcam.stop(); };
  },
};
