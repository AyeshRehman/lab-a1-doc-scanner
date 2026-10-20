// Browser webcam helper (getUserMedia) + frame grabbing.

export class Webcam {
  constructor(video) {
    this.video = video;
    this.stream = null;
    this.canvas = document.createElement('canvas');
  }

  static supported() {
    return !!navigator.mediaDevices?.getUserMedia;
  }

  static async devices() {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === 'videoinput').map((d, i) => ({ id: d.deviceId, label: d.label || `Camera ${i + 1}` }));
  }

  async start({ deviceId = '', height = 1080 } = {}) {
    this.stop();
    const video = {
      height: { ideal: Number(height) },
      width: { ideal: Math.round(Number(height) * 16 / 9) },
    };
    if (deviceId) video.deviceId = { exact: deviceId };
    else video.facingMode = { ideal: 'environment' };   // back camera on phones
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
    } catch (err) {
      if (deviceId && err.name === 'OverconstrainedError') return this.start({ height });
      throw err;
    }
    this.video.srcObject = this.stream;
    await this.video.play();
    await new Promise((r) => (this.video.videoWidth ? r() : this.video.addEventListener('loadedmetadata', r, { once: true })));
    return this.settings();
  }

  settings() {
    const track = this.stream?.getVideoTracks()[0];
    return { width: this.video.videoWidth, height: this.video.videoHeight, label: track?.label, deviceId: track?.getSettings().deviceId };
  }

  get ready() { return this.video.readyState >= 2 && this.video.videoWidth > 0; }

  /** Current frame as a JPEG blob, scaled so its width is at most maxWidth. */
  grab(maxWidth = Infinity, quality = 0.92) {
    const vw = this.video.videoWidth, vh = this.video.videoHeight;
    const s = Math.min(1, maxWidth / vw);
    this.canvas.width = Math.round(vw * s);
    this.canvas.height = Math.round(vh * s);
    this.canvas.getContext('2d').drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);
    return new Promise((resolve) => this.canvas.toBlob(resolve, 'image/jpeg', quality));
  }

  stop() {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    if (this.video) this.video.srcObject = null;
  }
}

export function cameraErrorMessage(err) {
  switch (err?.name) {
    case 'NotAllowedError': return 'Camera access was blocked. Allow it in the browser address bar, then try again.';
    case 'NotFoundError': return 'No camera was found on this device.';
    case 'NotReadableError': return 'The camera is busy - close other apps that use it (Zoom, Teams, another tab) and try again.';
    default: return err?.message || 'The camera could not be started.';
  }
}
