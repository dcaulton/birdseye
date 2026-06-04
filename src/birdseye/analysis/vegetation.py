"""
Vegetation index calculations from RGB drone frames.
Lighter path (ExG / VARI etc.) before multispectral.
"""

import cv2
import numpy as np
from numpy.typing import NDArray


def compute_vegetation_indices(bgr_frame: NDArray[np.uint8]) -> dict[str, float]:
    """
    Expects OpenCV BGR uint8 frame.
    Returns mean + stats for ExG, VARI, green channel (good for biomass/veg health).
    """
    rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]

    # Excess Green (ExG) — very common for vegetation segmentation
    exg = 2 * g - r - b
    exg_mean = float(np.nanmean(exg))

    # VARI — robust to atmospheric/soil effects
    vari = (g - r) / (g + r - b + 1e-6)
    vari_mean = float(np.nanmean(vari))

    green_mean = float(np.nanmean(g))

    return {
        "exg_mean": round(exg_mean, 4),
        "vari_mean": round(vari_mean, 4),
        "green_mean": round(green_mean, 4),
        "exg_min": round(float(np.nanmin(exg)), 4),
        "exg_max": round(float(np.nanmax(exg)), 4),
    }
