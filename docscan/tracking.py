"""Temporal smoothing of detected corners for live video."""

from __future__ import annotations

import numpy as np


class CornerTracker:
    """Smooth the detected corners over time and decide when the page is 'stable'.

    * small movement -> exponential moving average (removes jitter)
    * big movement   -> jump to the new position and restart the stability count
    * a few missed detections are tolerated (motion blur, a finger over an edge)
    """

    def __init__(self, alpha=0.4, move_thresh=0.02, hold_frames=8, stable_frames=15):
        self.alpha, self.move_thresh = alpha, move_thresh
        self.hold_frames, self.stable_frames = hold_frames, stable_frames
        self.corners, self.stable, self.missed = None, 0, 0

    def update(self, corners, diag: float):
        if corners is None:
            self.missed += 1
            if self.missed > self.hold_frames:
                self.corners, self.stable = None, 0
            return self.corners
        self.missed = 0
        if self.corners is None:
            self.corners, self.stable = corners, 0
        elif np.abs(corners - self.corners).max() / diag < self.move_thresh:
            self.corners = self.alpha * corners + (1 - self.alpha) * self.corners
            self.stable += 1
        else:
            self.corners, self.stable = corners, 0
        return self.corners

    @property
    def progress(self) -> float:
        return min(1.0, self.stable / self.stable_frames) if self.corners is not None else 0.0

    @property
    def is_stable(self) -> bool:
        return self.progress >= 1.0
