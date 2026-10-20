"""docscan - a classical (no deep learning) document scanner built with OpenCV + NumPy.

Modules map onto the Module A1 learning goals:

    basics    - pixels, channels, bit depth, BGR vs RGB, colour spaces, colour segmentation
    geometry  - resize, crop, rotate, affine and perspective warps
    filters   - blur, sharpening, morphology, thresholding, shadow removal
    detect    - Canny, contours, Hough lines and circles -> find the paper sheet
    enhance   - turn the warped sheet into a clean "scan"
    features  - ORB / SIFT keypoints, matching and homography
    camera    - video sources (webcam, file, RTSP), calibration, lens undistortion
    pipeline  - glues everything into scan_document()
"""

from .pipeline import ScanResult, scan_document

__all__ = ["ScanResult", "scan_document"]
