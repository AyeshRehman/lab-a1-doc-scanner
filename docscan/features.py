"""Keypoints, descriptors, matching and homography.

* ORB  : fast, binary descriptors -> compare with Hamming distance. Free to use.
* SIFT : slower, float descriptors -> compare with L2 distance. Scale/rotation
         invariant and usually more accurate.
* Lowe's ratio test keeps a match only if it is clearly better than the 2nd best.
* findHomography + RANSAC estimates the 3x3 perspective transform while
  ignoring wrong matches (outliers).

In the scanner this lets you align a photo of a *known* form/template to its
clean digital original, even when the page outline is not visible at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


def create_detector(method: str = "orb", n_features: int | None = None):
    """n_features=None -> 5000 for ORB, unlimited for SIFT. A small cap is risky:
    background texture (wood grain, carpet) can use up the whole budget."""
    method = method.lower()
    if method == "orb":
        return cv2.ORB_create(nfeatures=n_features or 5000), cv2.NORM_HAMMING
    if method == "sift":
        return cv2.SIFT_create(nfeatures=n_features or 0), cv2.NORM_L2
    raise ValueError("method must be 'orb' or 'sift'")


def detect_and_describe(img: np.ndarray, method: str = "orb", n_features: int | None = None):
    detector, _ = create_detector(method, n_features)
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return detector.detectAndCompute(gray, None)


def match(des1, des2, method: str = "orb", ratio: float = 0.75):
    """Brute-force k-NN matching followed by Lowe's ratio test."""
    _, norm = create_detector(method)
    if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
        return []
    matcher = cv2.BFMatcher(norm)
    good = []
    for pair in matcher.knnMatch(des1, des2, k=2):
        if len(pair) == 2 and pair[0].distance < ratio * pair[1].distance:
            good.append(pair[0])
    return sorted(good, key=lambda m: m.distance)


@dataclass
class Alignment:
    aligned: np.ndarray | None   # image warped into the template's frame
    H: np.ndarray | None         # homography image -> template
    n_keypoints: tuple[int, int]
    n_matches: int
    n_inliers: int
    visual: np.ndarray           # drawMatches visualisation of the inliers


def align_to_template(image: np.ndarray, template: np.ndarray, method: str = "orb",
                      ratio: float = 0.75, min_inliers: int = 15) -> Alignment:
    kp_t, des_t = detect_and_describe(template, method)
    kp_i, des_i = detect_and_describe(image, method)
    matches = match(des_i, des_t, method, ratio)

    H, inlier_mask, aligned = None, None, None
    if len(matches) >= 4:
        src = np.float32([kp_i[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst = np.float32([kp_t[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        H, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)

    n_inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
    if H is not None and n_inliers >= min_inliers:
        h, w = template.shape[:2]
        aligned = cv2.warpPerspective(image, H, (w, h))
    else:
        H = None

    draw_mask = inlier_mask.ravel().tolist() if inlier_mask is not None else None
    visual = cv2.drawMatches(image, kp_i, template, kp_t, matches[:200], None,
                             matchColor=(0, 255, 0), singlePointColor=(255, 0, 0),
                             matchesMask=draw_mask[:200] if draw_mask else None,
                             flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
    return Alignment(aligned, H, (len(kp_i), len(kp_t)), len(matches), n_inliers, visual)


def draw_keypoints(img: np.ndarray, method: str = "orb", n_features: int = 500) -> np.ndarray:
    kps, _ = detect_and_describe(img, method, n_features)
    return cv2.drawKeypoints(img, kps, None, color=(0, 255, 0),
                             flags=cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)
