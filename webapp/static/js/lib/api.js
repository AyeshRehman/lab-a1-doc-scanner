// Thin wrapper around the Flask API. Every call throws an Error with a readable message.

async function request(method, url, body, { raw = false } = {}) {
  const opts = { method, headers: {} };
  if (body instanceof FormData || body instanceof Blob) opts.body = body;
  else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers['Content-Type'] = 'application/json';
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch {
    throw new Error('Cannot reach the DocScan server. Is "python app.py" still running?');
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).error || msg; } catch { /* not JSON */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return raw ? res : res.json();
}

const get = (url) => request('GET', url);
const post = (url, body) => request('POST', url, body ?? {});
const patch = (url, body) => request('PATCH', url, body);
const del = (url) => request('DELETE', url);

async function fileFromResponse(res, fallback) {
  const cd = res.headers.get('Content-Disposition') || '';
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  return { blob: await res.blob(), filename: m ? decodeURIComponent(m[1]) : fallback };
}

export const api = {
  status: () => get('/api/status'),
  setServerSettings: (body) => patch('/api/settings', body),

  docs: {
    list: () => get('/api/docs'),
    get: (id) => get(`/api/docs/${id}`),
    /** files: File[] | Blob; extra: {source, corners, detect, options} */
    create(files, extra = {}) {
      const fd = new FormData();
      for (const f of [].concat(files)) fd.append('files', f, f.name || 'frame.jpg');
      for (const [k, v] of Object.entries(extra)) {
        if (v === undefined || v === null) continue;
        fd.append(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
      }
      return post('/api/docs', fd);
    },
    process: (id, body) => post(`/api/docs/${id}/process`, body),
    detect: (id) => post(`/api/docs/${id}/detect`),
    rename: (id, name) => patch(`/api/docs/${id}`, { name }),
    remove: (id) => del(`/api/docs/${id}`),
    removeAll: () => del('/api/docs'),
    steps: (id) => get(`/api/docs/${id}/steps`),
    downloadUrl: (id, format) => `/api/docs/${id}/download?format=${format}`,
    async export(ids, format) {
      const res = await request('POST', '/api/export', { ids, format }, { raw: true });
      return fileFromResponse(res, `scans.${format}`);
    },
  },

  detect(blob, debug = false) {
    return request('POST', `/api/detect${debug ? '?debug=1' : ''}`, blob);
  },

  samples: () => get('/api/samples'),
  importSample: (name, options) => post('/api/samples/import', { name, options }),

  stream: {
    start: (source, stableFrames) => post('/api/stream/start', { source, stable_frames: stableFrames }),
    upload(file) { const fd = new FormData(); fd.append('file', file); return post('/api/stream/upload', fd); },
    async frame(after) {
      const res = await request('GET', `/api/stream/frame?after=${after}`, undefined, { raw: true });
      return { blob: await res.blob(), state: JSON.parse(res.headers.get('X-State') || '{}') };
    },
    capture: (options) => post('/api/stream/capture', { options }),
    stop: () => post('/api/stream/stop'),
  },

  calib: {
    status: () => get('/api/calibration'),
    detect: (blob, pattern) => request('POST', `/api/calibration/detect?pattern=${pattern}`, blob),
    addViews(files, pattern) {
      const fd = new FormData();
      for (const f of [].concat(files)) fd.append('files', f, f.name || 'view.jpg');
      return post(`/api/calibration/views?pattern=${pattern}`, fd);
    },
    removeView: (i) => del(`/api/calibration/views/${i}`),
    reset: () => del('/api/calibration/views'),
    run: (pattern, square) => post('/api/calibration/run', { pattern, square }),
    remove: () => del('/api/calibration'),
  },

  align(template, image, method, ratio) {
    const fd = new FormData();
    fd.append('template', template);
    fd.append('image', image);
    fd.append('method', method);
    fd.append('ratio', String(ratio));
    return post('/api/align', fd);
  },

  topics: () => get('/api/topics'),
  topicUrl: (id, docId) => `/api/topics/${id}.jpg${docId ? `?doc=${docId}` : ''}`,
};
