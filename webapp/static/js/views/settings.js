// Preferences: appearance, scan defaults, camera, storage, shortcuts, about.
import { api } from '../lib/api.js';
import { settings } from '../lib/settings.js';
import { ASPECT_OPTIONS, MODE_OPTIONS } from './shared.js';
import { button, confirmDialog, fmtBytes, h, segmented, selectBox, toast, toastError, toggle } from '../lib/ui.js';

export default {
  async mount(root, { navigate }) {
    let status = null;
    try { status = await api.status(); } catch (err) { toastError(err); }

    const row = (label, sub, control) => h('div', { class: 'setting-row' },
      h('div', { class: 'text' }, h('div', null, label), sub && h('div', { class: 'subtle' }, sub)), h('div', { class: 'control' }, control));
    const section = (title, ...rows) => h('section', { class: 'card' },
      h('div', { class: 'card-head' }, h('h2', null, title)), h('div', { class: 'card-body' }, rows));
    const bind = (key) => (v) => { settings.set(key, v); toast('Saved', { type: 'success', timeout: 1200 }); };

    const libraryInfo = h('span', { class: 'subtle' }, status ? `${status.library.count} scans · ${fmtBytes(status.library.bytes)}` : '');

    const calib = status?.calibration;
    const calibToggle = toggle({
      checked: !!status?.settings.use_calibration, label: 'Lens correction',
      onChange: async (v) => {
        if (v && !calib) { calibToggle.setValue(false); toast('Calibrate your camera first.', { type: 'error', action: { label: 'Calibrate', onClick: () => navigate('calibrate') } }); return; }
        try { await api.setServerSettings({ use_calibration: v }); toast('Saved', { type: 'success', timeout: 1200 }); } catch (err) { toastError(err); }
      },
    });

    const shortcuts = [
      ['Scan page', [['Ctrl', 'V'], 'Paste an image to scan it']],
      ['Editor', [['1–4'], 'Colour / Gray / B&W / Original'], [['[', ']'], 'Rotate left / right'], [['D'], 'Auto-detect the page'],
        [['F'], 'Use the whole photo'], [['Ctrl', 'Z'], 'Undo a corner change'], [['←', '→'], 'Previous / next photo'], [['Tab', '1–4', 'arrows'], 'Move a corner with the keyboard']],
      ['Live camera', [['Space'], 'Capture'], [['A'], 'Toggle auto-capture'], [['M'], 'Next look'], [['D'], 'Show what the detector sees']],
      ['Library', [['/'], 'Search'], [['Ctrl', 'A'], 'Select all'], [['Del'], 'Delete selected'], [['Esc'], 'Clear selection']],
    ];

    root.append(
      h('div', { class: 'page-header' }, h('div', { class: 'titles' }, h('h1', null, 'Settings'), h('p', null, 'Preferences are saved in this browser.'))),
      h('div', { class: 'settings' },
        section('Appearance',
          row('Theme', 'System follows your operating system.', segmented({
            label: 'Theme', value: settings.get('theme'), onChange: (v) => settings.set('theme', v),
            options: [{ value: 'system', label: 'System', icon: 'monitor' }, { value: 'light', label: 'Light', icon: 'sun' }, { value: 'dark', label: 'Dark', icon: 'moon' }],
          }))),
        section('New scans',
          row('Default look', 'Applied to new photos and camera captures.', segmented({ label: 'Default look', value: settings.get('mode'), options: MODE_OPTIONS, onChange: bind('mode') })),
          row('Page size', 'Automatic measures the real proportions from the perspective.', selectBox({ label: 'Page size', value: settings.get('aspect'), options: ASPECT_OPTIONS, onChange: bind('aspect') })),
          row('Straighten text', 'Fix small tilts using the text lines (Hough transform).', toggle({ label: 'Straighten text', checked: settings.get('deskew'), onChange: bind('deskew') })),
          row('Remove punch holes', 'Find binder holes (Hough circles) and paint them out.', toggle({ label: 'Remove punch holes', checked: settings.get('holes'), onChange: bind('holes') }))),
        section('Camera',
          row('Resolution', 'Higher gives sharper scans; lower is smoother on slow laptops.', selectBox({
            label: 'Resolution', value: settings.get('resolution'), onChange: bind('resolution'),
            options: [{ value: '720', label: '720p' }, { value: '1080', label: '1080p' }],
          })),
          row('Auto-capture', 'Take the picture by itself when the page is held still.', toggle({ label: 'Auto-capture', checked: settings.get('autoCapture'), onChange: bind('autoCapture') })),
          row('Steadiness needed', 'How long the page must stay still before it counts as steady.', segmented({
            label: 'Steadiness', value: settings.get('steadiness'), onChange: bind('steadiness'),
            options: [{ value: 'quick', label: 'Quick' }, { value: 'normal', label: 'Normal' }, { value: 'careful', label: 'Careful' }],
          })),
          row('Lens correction', calib ? `Calibrated · error ${calib.rms.toFixed(2)} px` : 'Not calibrated yet.', calibToggle),
          row('Calibration', null, button(calib ? 'Recalibrate' : 'Calibrate camera', { size: 'sm', icon: 'target', onClick: () => navigate('calibrate') }))),
        section('Storage',
          row('Library', h('span', null, 'Scans are stored in ', h('span', { class: 'mono' }, 'outputs/library'), ' inside the project folder.'), libraryInfo),
          row('Delete all scans', 'Removes every scan and original photo. This cannot be undone.', button('Delete all', {
            size: 'sm', variant: 'danger', icon: 'trash', onClick: async () => {
              if (!await confirmDialog({ title: 'Delete all scans?', message: 'Every scan and original photo in the library will be removed permanently.', confirmLabel: 'Delete everything', danger: true })) return;
              try { await api.docs.removeAll(); libraryInfo.textContent = '0 scans · 0 B'; toast('Library cleared', { type: 'success' }); } catch (err) { toastError(err); }
            },
          })),
          row('Reset preferences', 'Back to the default theme, look and camera options.', button('Reset', {
            size: 'sm', onClick: () => { settings.reset(); navigate('settings'); toast('Preferences reset', { type: 'success' }); },
          }))),
        section('Keyboard shortcuts',
          ...shortcuts.map(([group, ...items]) => h('div', { class: 'setting-row', style: { alignItems: 'flex-start' } },
            h('div', { class: 'text', style: { flex: '0 0 120px' } }, h('strong', null, group)),
            h('div', { class: 'shortcuts', style: { flex: 1 } }, items.flatMap(([keys, what]) => [
              h('span', { class: 'row', style: { gap: '4px' } }, keys.map((k) => h('span', { class: 'kbd' }, k))), h('span', { class: 'muted' }, what)]))))),
        section('About',
          row('DocScan', 'Lab A1 - classical computer vision document scanner.', h('span', { class: 'subtle mono' }, status ? `v${status.version}` : '')),
          row('Libraries', null, h('span', { class: 'subtle mono' }, status ? `OpenCV ${status.opencv} · NumPy ${status.numpy}` : '')))));
  },
};
