// Live scanning from this device's camera, an IP/RTSP camera or a video file.
//
// Device camera: the browser sends small frames to /api/detect and smooths the
// corners itself. Remote sources: the server reads the stream and returns each
// frame together with its tracked corners.
import { api } from '../lib/api.js';
import { Webcam, cameraErrorMessage } from '../lib/camera.js';
import { settings, STEADINESS } from '../lib/settings.js';
import { CornerTracker, drawPageOverlay } from '../lib/tracker.js';
import { MODE_OPTIONS } from './shared.js';
import { button, containRect, h, icon, modal, segmented, selectBox, toast, toastError, toggle } from '../lib/ui.js';

const DETECT_WIDTH = 640;

export default {
  async mount(root, { navigate }) {
    const video = h('video', { playsinline: true, muted: true, autoplay: true });
    const remoteImg = h('img', { class: 'remote hidden', alt: 'Camera stream' });
    const overlay = h('canvas', { class: 'overlay' });
    const flash = h('div', { class: 'flash' });
    const pill = h('div', { class: 'pill' }, h('span', { class: 'dot' }), h('span', { class: 'label' }, 'Starting…'));
    const fpsTag = h('div', { class: 'fps hidden' });
    const debugBox = h('div', { class: 'debug hidden' });
    const emptyBox = h('div', { class: 'stage-empty hidden' });
    const stage = h('div', { class: 'stage' }, video, remoteImg, overlay, flash, pill, fpsTag, debugBox, emptyBox);
    const captures = h('div', { class: 'captures' });
    const captureCount = h('span', { class: 'subtle' }, '0');
    const capturesHint = h('p', { class: 'subtle' }, 'Your captures from this session appear here. They are also saved in the Library.');
    const capturesCard = h('div', null, h('div', { class: 'section-head' }, h('h2', null, 'Captured'), captureCount), capturesHint, captures);

    const webcam = new Webcam(video);
    const tracker = new CornerTracker({ stable: STEADINESS[settings.get('steadiness')] });
    let source = { kind: 'device', label: 'This device' };
    let running = false, generation = 0;
    let remoteState = null, lastFrameAt = 0, fps = 0, frameCount = 0;
    let capturedThisHold = false, lastCapture = 0, busy = false;
    let mode = settings.get('mode');
    let auto = settings.get('autoCapture');
    let showDebug = settings.get('showDebug');

    // ---------------------------------------------------------------- controls
    const modeSeg = segmented({ options: MODE_OPTIONS, value: mode, label: 'Scan look', onChange: (v) => { mode = v; } });
    const shutter = h('button', { class: 'shutter', title: 'Capture (Space)', 'aria-label': 'Capture', disabled: true, onClick: () => capture('manual') });
    const autoToggle = toggle({ checked: auto, label: 'Auto-capture', onChange: (v) => { auto = v; settings.set('autoCapture', v); } });
    const sourceBtn = button('This device', { icon: 'camera', onClick: chooseSource });
    const debugBtn = button('', { icon: 'eye', title: 'Show what the detector sees (D)', onClick: () => setDebug(!showDebug) });
    debugBtn.classList.toggle('is-on', showDebug);

    function setDebug(on) {
      showDebug = on;
      settings.set('showDebug', on);
      debugBtn.classList.toggle('is-on', on);
      debugBox.classList.toggle('hidden', !on || source.kind !== 'device');
    }

    root.append(
      h('div', { class: 'page-header' },
        h('div', { class: 'titles' }, h('h1', null, 'Live camera'),
          h('p', null, 'Hold a page in view. The outline turns green when it is steady - press the button or let auto-capture take it.')),
        h('div', { class: 'actions' }, debugBtn, sourceBtn)),
      h('div', { class: 'live-layout' },
        h('div', null,
          stage,
          h('div', { class: 'controls' },
            h('div', { class: 'side' }, modeSeg),
            shutter,
            h('label', { class: 'side right row', style: { gap: '10px', cursor: 'pointer' } }, h('span', null, 'Auto-capture'), autoToggle))),
        capturesCard));

    // ---------------------------------------------------------------- status
    function setStatus(kind, text) {
      pill.className = `pill ${kind}`;
      pill.querySelector('.label').textContent = text;
    }

    function showEmpty(title, text, actions) {
      emptyBox.replaceChildren(icon('camera', 'icon-lg'), h('h2', null, title), h('p', null, text),
        h('div', { class: 'row-wrap', style: { justifyContent: 'center' } }, actions));
      emptyBox.classList.remove('hidden');
      pill.classList.add('hidden');
    }

    function hideEmpty() { emptyBox.classList.add('hidden'); pill.classList.remove('hidden'); }

    // ---------------------------------------------------------------- sources
    async function startDevice(deviceId = settings.get('deviceId')) {
      await stopAll();
      const gen = ++generation;
      source = { kind: 'device', label: 'This device' };
      remoteImg.classList.add('hidden');
      video.classList.remove('hidden');
      sourceBtn.replaceChildren(icon('camera'), h('span', null, 'This device'));
      if (!Webcam.supported()) {
        showEmpty('Camera not available', 'This browser cannot use a camera here. Open the app at http://127.0.0.1:8000 or use an IP camera / video file instead.',
          [button('Choose another source', { variant: 'primary', onClick: chooseSource })]);
        return;
      }
      setStatus('', 'Starting camera…');
      try {
        const info = await webcam.start({ deviceId, height: settings.get('resolution') });
        if (gen !== generation) return;
        hideEmpty();
        source.label = info.label || 'This device';
        sourceBtn.replaceChildren(icon('camera'), h('span', null, shorten(source.label)));
        running = true;
        detectLoop(gen);
        drawLoop(gen);
        setDebug(showDebug);
      } catch (err) {
        if (gen !== generation) return;
        showEmpty('Camera unavailable', cameraErrorMessage(err), [
          button('Try again', { variant: 'primary', icon: 'rotateCw', onClick: () => startDevice() }),
          button('Use the sample video', { icon: 'video', onClick: () => startRemote('sample', 'Sample video') }),
        ]);
      }
    }

    async function startRemote(src, label, file) {
      await stopAll();
      const gen = ++generation;
      source = { kind: 'remote', label, src };
      video.classList.add('hidden');
      remoteImg.classList.remove('hidden');
      debugBox.classList.add('hidden');
      sourceBtn.replaceChildren(icon(file || src === 'sample' ? 'video' : 'link'), h('span', null, shorten(label)));
      setStatus('', 'Connecting…');
      hideEmpty();
      try {
        if (file) await api.stream.upload(file);
        else await api.stream.start(src, STEADINESS[settings.get('steadiness')]);
        if (gen !== generation) return;
        running = true;
        remoteLoop(gen);
        drawLoop(gen);
      } catch (err) {
        if (gen !== generation) return;
        showEmpty('Could not connect', err.message, [
          button('Choose another source', { variant: 'primary', onClick: chooseSource }),
          button('Back to this device', { icon: 'camera', onClick: () => startDevice() }),
        ]);
      }
    }

    async function stopAll() {
      running = false;
      generation++;
      webcam.stop();
      tracker.reset();
      remoteState = null;
      if (source.kind === 'remote') { try { await api.stream.stop(); } catch { /* server may be gone */ } }
    }

    // ---------------------------------------------------------------- loops
    async function detectLoop(gen) {
      let n = 0;
      while (running && gen === generation) {
        if (!webcam.ready) { await sleep(50); continue; }
        try {
          const blob = await webcam.grab(DETECT_WIDTH, 0.7);
          const wantDebug = showDebug && n++ % 6 === 0;
          const res = await api.detect(blob, wantDebug);
          if (gen !== generation) return;
          tracker.update(res.found ? res.corners : null);
          if (wantDebug && res.debug) paintDebug(res.debug);
          tick();
        } catch (err) {
          if (gen !== generation) return;
          setStatus('', 'Reconnecting…');
          await sleep(800);
        }
      }
    }

    async function remoteLoop(gen) {
      let seq = 0, url = null;
      while (running && gen === generation) {
        try {
          const { blob, state } = await api.stream.frame(seq);
          if (gen !== generation) return;
          seq = state.seq;
          const next = URL.createObjectURL(blob);
          // decode first, then swap image and corners together so the outline never lags the picture
          const decoded = new Image();
          decoded.src = next;
          await decoded.decode().catch(() => {});
          if (gen !== generation) return;
          remoteImg.src = next;
          remoteState = state;
          if (url) URL.revokeObjectURL(url);
          url = next;
          tick();
          if (state.error) throw new Error(state.error);
        } catch (err) {
          if (gen !== generation) return;
          if (err.status === 504) continue;
          showEmpty('Stream stopped', err.message, [
            button('Reconnect', { variant: 'primary', icon: 'rotateCw', onClick: () => startRemote(source.src || 'sample', source.label) }),
            button('Choose another source', { onClick: chooseSource }),
          ]);
          running = false;
          return;
        }
      }
    }

    function tick() {
      const now = performance.now();
      if (lastFrameAt) fps = fps * 0.85 + (1000 / (now - lastFrameAt)) * 0.15;
      lastFrameAt = now;
      if (++frameCount % 5 === 0) { fpsTag.textContent = `${fps.toFixed(0)} fps`; fpsTag.classList.remove('hidden'); }
    }

    function current() {
      if (source.kind === 'remote') {
        const s = remoteState;
        return s ? { corners: s.corners, progress: s.progress, w: s.width, h: s.height } : { corners: null, progress: 0 };
      }
      return { corners: tracker.corners, progress: tracker.progress, w: video.videoWidth, h: video.videoHeight };
    }

    function drawLoop(gen) {
      const ctx = overlay.getContext('2d');
      const frame = () => {
        if (gen !== generation) return;
        const dpr = window.devicePixelRatio || 1;
        const bw = overlay.clientWidth, bh = overlay.clientHeight;
        if (overlay.width !== Math.round(bw * dpr)) { overlay.width = Math.round(bw * dpr); overlay.height = Math.round(bh * dpr); }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, bw, bh);
        const { corners, progress, w, h: hh } = current();
        if (corners && w) {
          drawPageOverlay(ctx, containRect(w, hh, bw, bh), corners, { progress });
          setStatus(progress >= 1 ? 'stable' : 'found', progress >= 1 ? (auto ? 'Hold still - capturing' : 'Ready - press capture') : 'Hold steady…');
        } else if (running) {
          setStatus('', 'Looking for a page…');
        }
        shutter.classList.toggle('ready', !!corners && progress >= 1);
        shutter.disabled = !running;
        shutter.style.setProperty('--p', progress);
        // auto-capture once per steady hold
        if (!corners || progress < 1) capturedThisHold = false;
        if (auto && corners && progress >= 1 && !capturedThisHold && !busy && performance.now() - lastCapture > 2000) {
          capturedThisHold = true;
          capture('auto');
        }
        requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    }

    function paintDebug(dbg) {
      debugBox.replaceChildren(
        h('figure', null, h('img', { src: dbg.edges, alt: 'Edges' }), h('figcaption', null, 'Edges (Canny + close)')),
        h('figure', null, h('img', { src: dbg.paper_mask, alt: 'Paper mask' }), h('figcaption', null, 'Paper colour mask')));
    }

    // ---------------------------------------------------------------- capture
    async function capture(how) {
      if (busy) return;
      const { corners } = current();
      if (!running) return;
      if (!corners && how === 'manual' && source.kind === 'remote') return toast('No page in view yet.', { type: 'error' });
      busy = true;
      lastCapture = performance.now();
      flash.classList.remove('go'); void flash.offsetWidth; flash.classList.add('go');
      try {
        const options = { ...settings.scanOptions(), mode };
        let res;
        if (source.kind === 'remote') res = await api.stream.capture(options);
        else {
          const blob = await webcam.grab(Infinity, 0.95);
          res = await api.docs.create([new File([blob], 'frame.jpg', { type: 'image/jpeg' })], {
            source: 'camera', options, corners: corners || undefined, detect: corners ? 1 : 0,
          });
        }
        const doc = res.docs[0];
        addCapture(doc);
        toast(how === 'auto' ? 'Captured automatically' : 'Captured', {
          type: 'success', action: { label: 'Open', onClick: () => navigate(`doc/${doc.id}`) },
        });
      } catch (err) { toastError(err); } finally { busy = false; }
    }

    const session = [];
    function addCapture(doc) {
      session.unshift(doc.id);
      capturesHint.remove();
      sessionStorage.setItem('docscan.batch', JSON.stringify(session));
      captures.prepend(h('a', { class: 'capture', href: `#/doc/${doc.id}` },
        h('img', { src: doc.urls.thumb, alt: '' }),
        h('div', null, h('div', { class: 't' }, `Scan ${session.length}`), h('div', { class: 's' }, new Date().toLocaleTimeString()))));
      captureCount.textContent = String(session.length);
    }

    // ---------------------------------------------------------------- source picker
    async function chooseSource() {
      const devices = await Webcam.devices().catch(() => []);
      let kind = source.kind === 'device' ? 'device' : (source.src && source.src !== 'sample' ? 'ip' : 'file');
      const panel = h('div', { class: 'stack' });
      const opts = [
        { value: 'device', icon: 'camera', title: 'This device', text: 'Webcam or phone camera, in the browser' },
        { value: 'ip', icon: 'link', title: 'IP camera', text: 'RTSP or HTTP stream, read by the server' },
        { value: 'file', icon: 'video', title: 'Video file', text: 'Upload a clip, or use the sample video' },
      ];
      const optionEls = opts.map((o) => h('button', {
        type: 'button', class: `source-option${o.value === kind ? ' active' : ''}`,
        onClick: () => { kind = o.value; optionEls.forEach((el, i) => el.classList.toggle('active', opts[i].value === kind)); paintPanel(); },
      }, h('span', { class: 'bubble' }, icon(o.icon)), h('span', null, h('strong', null, o.title), h('span', null, o.text))));

      let deviceSel, resSel, urlInput, fileInput;
      function paintPanel() {
        if (kind === 'device') {
          deviceSel = selectBox({ label: 'Camera', value: settings.get('deviceId'),
            options: [{ value: '', label: 'Default camera' }, ...devices.map((d) => ({ value: d.id, label: d.label }))] });
          resSel = selectBox({ label: 'Resolution', value: settings.get('resolution'),
            options: [{ value: '720', label: 'HD (720p) - faster' }, { value: '1080', label: 'Full HD (1080p) - sharper scans' }] });
          panel.replaceChildren(h('div', { class: 'field' }, h('label', null, 'Camera'), deviceSel), h('div', { class: 'field' }, h('label', null, 'Resolution'), resSel));
        } else if (kind === 'ip') {
          urlInput = h('input', { class: 'input', placeholder: 'rtsp://user:password@192.168.1.20:554/stream1', value: source.src && source.src !== 'sample' ? source.src : '' });
          panel.replaceChildren(h('div', { class: 'field' }, h('label', null, 'Stream address'), urlInput),
            h('p', { class: 'subtle' }, 'Also works with a webcam index on the server (e.g. 0) or a video file path. Phone apps such as "IP Webcam" give you an http:// address.'));
        } else {
          fileInput = h('input', { type: 'file', accept: 'video/*', class: 'input', style: { paddingTop: '6px' } });
          panel.replaceChildren(h('div', { class: 'field' }, h('label', null, 'Video file'), fileInput),
            h('p', { class: 'subtle' }, 'Leave empty to play the built-in sample video.'));
        }
      }
      paintPanel();

      modal({
        title: 'Video source', wide: true,
        body: h('div', { class: 'stack' }, h('div', { class: 'source-options' }, optionEls), panel),
        actions: [
          { label: 'Cancel', variant: 'ghost' },
          { label: 'Connect', variant: 'primary', onClick: (close) => {
            if (kind === 'device') {
              settings.set('deviceId', deviceSel.value);
              settings.set('resolution', resSel.value);
              close(); startDevice(deviceSel.value);
            } else if (kind === 'ip') {
              const url = urlInput.value.trim();
              if (!url) { urlInput.focus(); return; }
              close(); startRemote(url, url);
            } else {
              const file = fileInput.files[0];
              close();
              if (file) startRemote(null, file.name, file);
              else startRemote('sample', 'Sample video');
            }
          } },
        ],
      });
    }

    // ---------------------------------------------------------------- shortcuts
    const onKey = (e) => {
      if (e.target.closest('input, select, textarea, dialog')) return;
      const k = e.key.toLowerCase();
      if (k === ' ') { e.preventDefault(); capture('manual'); }
      else if (k === 'a') { auto = !auto; autoToggle.setValue(auto); settings.set('autoCapture', auto); toast(`Auto-capture ${auto ? 'on' : 'off'}`, { timeout: 1400 }); }
      else if (k === 'd') setDebug(!showDebug);
      else if (k === 'm') { const i = MODE_OPTIONS.findIndex((o) => o.value === mode); mode = MODE_OPTIONS[(i + 1) % MODE_OPTIONS.length].value; modeSeg.setValue(mode); }
    };
    document.addEventListener('keydown', onKey);

    startDevice();

    return () => {
      document.removeEventListener('keydown', onKey);
      stopAll();
    };
  },
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const shorten = (s) => (s.length > 28 ? `${s.slice(0, 26)}…` : s);
