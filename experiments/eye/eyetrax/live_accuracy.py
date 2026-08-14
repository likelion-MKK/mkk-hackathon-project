"""Run a live, aggregate-only EyeTrax accuracy benchmark.

The camera frame and per-frame gaze prediction remain in memory. Only aggregate
metrics are written to the result JSON.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import ctypes
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Sequence
import urllib.request

import cv2
import eyetrax
from eyetrax import GazeEstimator
from eyetrax.models import create_model
from eyetrax.utils.screen import get_screen_size
import numpy as np
import psutil


WINDOW_NAME = "MCM EyeTrax Live Benchmark"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = REPO_ROOT / "data" / "lookbooks" / "example" / "manifest.json"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / ".cache" / "face_landmarker.task"
FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
FACE_MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
EYETRAX_SOURCE_REVISION = "84e13a16af168ac7c383f7d50ec901cd6c0ad61d"

CALIBRATION_POINTS = (
    (0.50, 0.50),
    (0.10, 0.10),
    (0.90, 0.10),
    (0.10, 0.90),
    (0.90, 0.90),
    (0.50, 0.10),
    (0.10, 0.50),
    (0.90, 0.50),
    (0.50, 0.90),
)
DENSE_GRID_AXIS = (0.10, 0.30, 0.50, 0.70, 0.90)
VALIDATION_TARGETS = (
    ("P001", 0.20, 0.30),
    ("P001", 0.38, 0.30),
    ("P001", 0.20, 0.70),
    ("P001", 0.42, 0.70),
    ("P002", 0.80, 0.30),
    ("P002", 0.62, 0.30),
    ("P002", 0.80, 0.70),
    ("P002", 0.58, 0.70),
)

VALID_RATIO_GATE = 0.90
AOI_HIT_GATE = 0.80
LATENCY_P95_GATE_MS = 100.0
NO_FACE_GATE = 0.95
MIN_CALIBRATION_SAMPLES = 15
RIDGE_ALPHA_CANDIDATES = (0.001, 0.01, 0.1, 1.0, 10.0)


class UserAbort(RuntimeError):
    """Raised when the participant presses Escape."""


def calibration_points_for(mode: str) -> tuple[tuple[float, float], ...]:
    if mode == "9p":
        return CALIBRATION_POINTS
    if mode == "dense5":
        points: list[tuple[float, float]] = []
        for row, y in enumerate(DENSE_GRID_AXIS):
            x_values = DENSE_GRID_AXIS if row % 2 == 0 else tuple(reversed(DENSE_GRID_AXIS))
            points.extend((x, y) for x in x_values)
        return tuple(points)
    raise ValueError(f"Unknown calibration mode: {mode}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_face_model(path: Path, *, offline: bool) -> Path:
    if path.exists():
        actual = sha256_file(path)
        if actual != FACE_MODEL_SHA256:
            raise RuntimeError(
                f"Face model checksum mismatch: expected {FACE_MODEL_SHA256}, got {actual}"
            )
        return path
    if offline:
        raise RuntimeError(f"Face model is missing in offline mode: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    request = urllib.request.Request(FACE_MODEL_URL, headers={"User-Agent": "mcm-eye-benchmark"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        actual = sha256_file(temporary)
        if actual != FACE_MODEL_SHA256:
            raise RuntimeError(
                f"Downloaded face model checksum mismatch: expected {FACE_MODEL_SHA256}, got {actual}"
            )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


@contextmanager
def native_face_model_path(path: Path):
    """Give MediaPipe an ASCII path while retaining the verified repo cache."""
    if str(path).isascii():
        yield path
        return

    descriptor, temporary_name = tempfile.mkstemp(prefix="mcm-face-landmarker-", suffix=".task")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if not str(temporary).isascii():
            raise RuntimeError(f"MediaPipe requires an ASCII runtime path on Windows: {temporary}")
        shutil.copyfile(path, temporary)
        actual = sha256_file(temporary)
        if actual != FACE_MODEL_SHA256:
            raise RuntimeError(
                f"Runtime face model checksum mismatch: expected {FACE_MODEL_SHA256}, got {actual}"
            )
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def normalize_prediction(
    prediction: Sequence[float], width: int, height: int
) -> tuple[tuple[float, float] | None, str | None]:
    if len(prediction) < 2 or not all(math.isfinite(float(value)) for value in prediction[:2]):
        return None, "invalid_prediction"
    x_norm = float(prediction[0]) / width
    y_norm = float(prediction[1]) / height
    if not 0.0 <= x_norm <= 1.0 or not 0.0 <= y_norm <= 1.0:
        return None, "outside_viewport"
    return (x_norm, y_norm), None


def extraction_failure_reason(features: Any, blink: bool) -> str | None:
    if features is None:
        return "no_face"
    if blink:
        return "blink"
    return None


def point_in_polygon(point: tuple[float, float], polygon: Sequence[Sequence[float]]) -> bool:
    x, y = point
    inside = False
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        x1, y1 = float(previous[0]), float(previous[1])
        x2, y2 = float(current[0]), float(current[1])

        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) <= 1e-12 and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
            return True

        intersects = (y1 > y) != (y2 > y)
        if intersects:
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
    return inside


def load_product_polygons(path: Path) -> dict[str, list[list[float]]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("coordinate_space") != "video_normalized":
        raise ValueError("Lookbook manifest must use video_normalized coordinates")
    polygons: dict[str, list[list[float]]] = {}
    for exposure in manifest.get("exposures", []):
        shape = exposure.get("shape", {})
        if shape.get("type") == "polygon":
            polygons.setdefault(exposure["product_id"], shape["points"])
    required = {target[0] for target in VALIDATION_TARGETS}
    if not required.issubset(polygons):
        raise ValueError(f"Manifest is missing validation AOIs: {sorted(required - polygons.keys())}")
    return polygons


def metric_stats(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None}
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": int(array.size),
        "mean": round(float(array.mean()), 4),
        "p50": round(float(np.percentile(array, 50)), 4),
        "p95": round(float(np.percentile(array, 95)), 4),
    }


def summarize_target_metrics(
    *,
    target_index: int,
    product_id: str,
    target_normalized: tuple[float, float],
    predictions_normalized: Sequence[tuple[float, float]],
    total_frames: int,
    aoi_hits: int,
    failures: Counter[str],
    polygon: Sequence[Sequence[float]],
    width: int,
    height: int,
) -> dict[str, Any]:
    target_x, target_y = target_normalized
    valid_frames = len(predictions_normalized)
    if predictions_normalized:
        values = np.asarray(predictions_normalized, dtype=np.float64)
        median_x, median_y = np.median(values, axis=0)
        median = (float(median_x), float(median_y))
        spread_px = [
            math.hypot((x - median[0]) * width, (y - median[1]) * height)
            for x, y in predictions_normalized
        ]
        signed_x_px = [(x - target_x) * width for x, _ in predictions_normalized]
        signed_y_px = [(y - target_y) * height for _, y in predictions_normalized]
        median_aoi_hit: bool | None = point_in_polygon(median, polygon)
        median_value: dict[str, float] | None = {
            "x": round(median[0], 6),
            "y": round(median[1], 6),
        }
    else:
        spread_px = []
        signed_x_px = []
        signed_y_px = []
        median_aoi_hit = None
        median_value = None

    return {
        "target_index": target_index,
        "product_id": product_id,
        "target_normalized": {"x": target_x, "y": target_y},
        "total_frames": total_frames,
        "valid_frames": valid_frames,
        "valid_ratio": round(valid_frames / total_frames, 4) if total_frames else 0.0,
        "aoi_hits": aoi_hits,
        "aoi_hit_ratio": round(aoi_hits / valid_frames, 4) if valid_frames else 0.0,
        "failure_counts": dict(sorted(failures.items())),
        "median_predicted_normalized": median_value,
        "median_aoi_hit": median_aoi_hit,
        "signed_error_x_px": metric_stats(signed_x_px),
        "signed_error_y_px": metric_stats(signed_y_px),
        "prediction_spread_px": metric_stats(spread_px),
    }


def select_ridge_alpha(
    features: np.ndarray,
    targets: np.ndarray,
    samples_per_point: Sequence[int],
    candidates: Sequence[float] = RIDGE_ALPHA_CANDIDATES,
) -> tuple[float, dict[str, Any]]:
    if sum(samples_per_point) != len(features) or len(features) != len(targets):
        raise ValueError("Calibration feature, target and point counts do not match")
    if len(samples_per_point) < 3:
        raise ValueError("At least three calibration points are required for cross-validation")

    groups = np.concatenate(
        [np.full(count, index, dtype=np.int32) for index, count in enumerate(samples_per_point)]
    )
    candidate_results: list[dict[str, Any]] = []
    for alpha in candidates:
        errors: list[float] = []
        for held_out in range(len(samples_per_point)):
            train_mask = groups != held_out
            test_mask = ~train_mask
            model = create_model("ridge", alpha=float(alpha))
            model.train(features[train_mask], targets[train_mask])
            predicted = model.predict(features[test_mask])
            errors.extend(np.linalg.norm(predicted - targets[test_mask], axis=1).tolist())
        candidate_results.append({"alpha": float(alpha), "error_px": metric_stats(errors)})

    selected = min(
        candidate_results,
        key=lambda item: (
            float(item["error_px"]["p50"]),
            float(item["error_px"]["p95"]),
            item["alpha"],
        ),
    )
    return float(selected["alpha"]), {
        "method": "leave_one_calibration_point_out",
        "selection_metric": "error_px_p50_then_p95",
        "selected_alpha": float(selected["alpha"]),
        "candidates": candidate_results,
    }


def get_screen_geometry() -> dict[str, float | int | str]:
    if sys.platform == "win32":
        logical_width = int(ctypes.windll.user32.GetSystemMetrics(0))
        logical_height = int(ctypes.windll.user32.GetSystemMetrics(1))
    else:
        logical_width, logical_height = get_screen_size()
    physical_width, physical_height = get_screen_size()
    if logical_width <= 0 or logical_height <= 0:
        raise RuntimeError("Could not determine a positive screen viewport")
    return {
        "coordinate_space": "logical_pixels",
        "width": logical_width,
        "height": logical_height,
        "physical_width": physical_width,
        "physical_height": physical_height,
        "physical_to_logical_scale_x": round(physical_width / logical_width, 4),
        "physical_to_logical_scale_y": round(physical_height / logical_height, 4),
    }


def evaluate_run_gate(run: dict[str, Any]) -> dict[str, Any]:
    latency_p95 = run["capture_to_result_ms"]["p95"]
    checks = {
        "calibration_completed": bool(run["calibration"]["completed"]),
        "valid_ratio": run["valid_ratio"] >= VALID_RATIO_GATE,
        "aoi_hit_ratio": run["aoi_hit_ratio"] >= AOI_HIT_GATE,
        "latency_p95_ms": latency_p95 is not None and latency_p95 <= LATENCY_P95_GATE_MS,
    }
    return {"passed": all(checks.values()), "checks": checks}


def evaluate_overall_gate(runs: Sequence[dict[str, Any]], no_face: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "three_runs_completed": len(runs) == 3,
        "every_run_passed": len(runs) == 3 and all(run["gate"]["passed"] for run in runs),
        "no_face_ratio": no_face["no_face_ratio"] >= NO_FACE_GATE,
        "camera_released": bool(no_face.get("camera_released")),
    }
    return {"passed": all(checks.values()), "checks": checks}


def provisional_recommendation(condition: str, runs_requested: int, passed: bool) -> str:
    if condition != "baseline" or runs_requested != 3:
        return "diagnostic_only"
    return "eyetrax_provisional_priority" if passed else "eyetrax_deferred_openvino_next"


def assert_privacy_safe_summary(summary: dict[str, Any]) -> None:
    forbidden_keys = {
        "frame",
        "frames",
        "frame_data",
        "image",
        "images",
        "base64",
        "embedding",
        "embeddings",
        "gaze_samples",
        "predictions",
        "trajectory",
        "raw_path",
        "participant_name",
        "participant_id",
        "subject_id",
    }

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in forbidden_keys:
                    raise ValueError(f"Privacy-unsafe result key: {key}")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and value.lower().endswith(
            (".jpg", ".jpeg", ".png", ".bmp", ".mp4", ".avi", ".mov")
        ):
            raise ValueError(f"Privacy-unsafe media path in result: {value}")

    visit(summary)


def _show_canvas(
    width: int,
    height: int,
    lines: Sequence[str],
    *,
    target: tuple[int, int] | None = None,
    progress: float | None = None,
) -> None:
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    if target:
        radius = 14 + int(8 * abs(math.sin(time.perf_counter() * math.pi * 2)))
        cv2.circle(canvas, target, radius, (0, 220, 255), -1)
        if progress is not None:
            cv2.ellipse(
                canvas,
                target,
                (42, 42),
                0,
                -90,
                -90 + int(360 * max(0.0, min(progress, 1.0))),
                (255, 255, 255),
                4,
            )
    for index, line in enumerate(lines):
        scale = 0.9 if index else 1.2
        thickness = 2
        size, _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
        x = max(20, (width - size[0]) // 2)
        y = 80 + index * 50
        cv2.putText(canvas, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (235, 235, 235), thickness)
    cv2.imshow(WINDOW_NAME, canvas)
    if cv2.waitKey(1) & 0xFF == 27:
        raise UserAbort("Participant cancelled with Escape")


def _wait_for_space(width: int, height: int, lines: Sequence[str]) -> None:
    while True:
        _show_canvas(width, height, lines)
        key = cv2.waitKey(20) & 0xFF
        if key == 27:
            raise UserAbort("Participant cancelled with Escape")
        if key == 32:
            return


def _capture_frame(cap: cv2.VideoCapture) -> tuple[np.ndarray | None, float]:
    started = time.perf_counter()
    ok, frame = cap.read()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return (frame if ok else None), elapsed_ms


def _wait_with_target(
    cap: cv2.VideoCapture,
    target: tuple[int, int],
    width: int,
    height: int,
    duration: float,
    message: str,
) -> None:
    started = time.perf_counter()
    while (elapsed := time.perf_counter() - started) < duration:
        cap.grab()
        _show_canvas(width, height, (message,), target=target, progress=elapsed / duration)


def _preflight(
    cap: cv2.VideoCapture,
    estimator: GazeEstimator,
    width: int,
    height: int,
) -> dict[str, Any]:
    valid = total = 0
    started = time.perf_counter()
    while time.perf_counter() - started < 3.0:
        frame, _ = _capture_frame(cap)
        if frame is None:
            continue
        total += 1
        features, blink = estimator.extract_features(frame)
        if extraction_failure_reason(features, blink) is None:
            valid += 1
        _show_canvas(width, height, ("FACE PREFLIGHT", f"valid frames: {valid}/{total}"))
    return {
        "frame_count": total,
        "valid_frames": valid,
        "passed": valid >= MIN_CALIBRATION_SAMPLES,
    }


def _calibrate_once(
    cap: cv2.VideoCapture,
    estimator: GazeEstimator,
    width: int,
    height: int,
    *,
    calibration_points: Sequence[tuple[float, float]],
    run_index: int,
    run_total: int,
) -> dict[str, Any]:
    all_features: list[np.ndarray] = []
    all_targets: list[list[float]] = []
    counts: list[int] = []
    point_total = len(calibration_points)
    for index, (x_norm, y_norm) in enumerate(calibration_points, start=1):
        target = (int(x_norm * width), int(y_norm * height))
        _wait_with_target(
            cap,
            target,
            width,
            height,
            1.0,
            f"RUN {run_index}/{run_total} - CALIBRATION {index}/{point_total} - LOOK AT THE DOT",
        )
        point_features: list[np.ndarray] = []
        started = time.perf_counter()
        while (elapsed := time.perf_counter() - started) < 1.0:
            frame, _ = _capture_frame(cap)
            if frame is not None:
                features, blink = estimator.extract_features(frame)
                if extraction_failure_reason(features, blink) is None:
                    point_features.append(np.asarray(features))
            _show_canvas(
                width,
                height,
                (f"RUN {run_index}/{run_total} - CALIBRATION {index}/{point_total} - HOLD",),
                target=target,
                progress=elapsed,
            )
        counts.append(len(point_features))
        all_features.extend(point_features)
        all_targets.extend([[float(target[0]), float(target[1])]] * len(point_features))

    completed = bool(counts) and min(counts) >= MIN_CALIBRATION_SAMPLES
    ridge_selection: dict[str, Any] | None = None
    fit_error_px: list[float] = []
    fit_signed_x_px: list[float] = []
    fit_signed_y_px: list[float] = []
    fit_outside_viewport = 0
    if completed:
        feature_matrix = np.asarray(all_features)
        target_matrix = np.asarray(all_targets)
        selected_alpha, ridge_selection = select_ridge_alpha(
            feature_matrix, target_matrix, counts
        )
        estimator.model = create_model("ridge", alpha=selected_alpha)
        estimator.train(feature_matrix, target_matrix)
        for prediction, target in zip(estimator.predict(feature_matrix), target_matrix, strict=True):
            if not np.all(np.isfinite(prediction[:2])):
                continue
            dx = float(prediction[0] - target[0])
            dy = float(prediction[1] - target[1])
            fit_signed_x_px.append(dx)
            fit_signed_y_px.append(dy)
            fit_error_px.append(math.hypot(dx, dy))
            if not 0 <= prediction[0] <= width or not 0 <= prediction[1] <= height:
                fit_outside_viewport += 1
    return {
        "completed": completed,
        "valid_samples_per_point": counts,
        "total_valid_samples": sum(counts),
        "minimum_required_per_point": MIN_CALIBRATION_SAMPLES,
        "ridge_selection": ridge_selection,
        "training_fit": {
            "error_px": metric_stats(fit_error_px),
            "signed_error_x_px": metric_stats(fit_signed_x_px),
            "signed_error_y_px": metric_stats(fit_signed_y_px),
            "outside_viewport_count": fit_outside_viewport,
        },
    }


def _run_validation(
    cap: cv2.VideoCapture,
    estimator: GazeEstimator,
    polygons: dict[str, list[list[float]]],
    width: int,
    height: int,
    *,
    run_index: int,
    run_total: int,
    seed: int,
    calibration: dict[str, Any],
) -> dict[str, Any]:
    targets = list(VALIDATION_TARGETS)
    random.Random(seed + run_index).shuffle(targets)
    failures: Counter[str] = Counter()
    latencies: list[float] = []
    errors_px: list[float] = []
    errors_diagonal: list[float] = []
    cpu_samples: list[float] = []
    rss_samples: list[int] = []
    target_metrics: list[dict[str, Any]] = []
    total_frames = valid_frames = hits = 0
    diagonal = math.hypot(width, height)
    process = psutil.Process()
    process.cpu_percent(None)
    validation_started = time.perf_counter()

    for index, (product_id, x_norm, y_norm) in enumerate(targets, start=1):
        target = (int(x_norm * width), int(y_norm * height))
        target_failures: Counter[str] = Counter()
        target_predictions: list[tuple[float, float]] = []
        target_total_frames = target_hits = 0
        _wait_with_target(
            cap,
            target,
            width,
            height,
            0.75,
            f"RUN {run_index}/{run_total} - VALIDATION {index}/8 - LOOK AT THE DOT",
        )
        started = time.perf_counter()
        while (elapsed := time.perf_counter() - started) < 1.0:
            observation_started = time.perf_counter()
            frame, _ = _capture_frame(cap)
            if frame is None:
                failures["camera_read_failed"] += 1
                target_failures["camera_read_failed"] += 1
                continue
            total_frames += 1
            target_total_frames += 1
            features, blink = estimator.extract_features(frame)
            reason = extraction_failure_reason(features, blink)
            if reason is None:
                prediction = estimator.predict(np.asarray([features]))[0]
                normalized, reason = normalize_prediction(prediction, width, height)
                if normalized is not None:
                    valid_frames += 1
                    target_predictions.append(normalized)
                    predicted_x = normalized[0] * width
                    predicted_y = normalized[1] * height
                    error = math.hypot(predicted_x - target[0], predicted_y - target[1])
                    errors_px.append(error)
                    errors_diagonal.append(error / diagonal)
                    if point_in_polygon(normalized, polygons[product_id]):
                        hits += 1
                        target_hits += 1
            if reason is not None:
                failures[reason] += 1
                target_failures[reason] += 1
            latencies.append((time.perf_counter() - observation_started) * 1000)
            _show_canvas(
                width,
                height,
                (f"RUN {run_index}/{run_total} - VALIDATION {index}/8 - HOLD",),
                target=target,
                progress=elapsed,
            )
        cpu_samples.append(process.cpu_percent(None))
        rss_samples.append(process.memory_info().rss)
        target_metrics.append(
            summarize_target_metrics(
                target_index=index,
                product_id=product_id,
                target_normalized=(x_norm, y_norm),
                predictions_normalized=target_predictions,
                total_frames=target_total_frames,
                aoi_hits=target_hits,
                failures=target_failures,
                polygon=polygons[product_id],
                width=width,
                height=height,
            )
        )

    elapsed = time.perf_counter() - validation_started
    target_medians = [item for item in target_metrics if item["median_aoi_hit"] is not None]
    target_median_hits = sum(item["median_aoi_hit"] is True for item in target_medians)
    run = {
        "run_index": run_index,
        "calibration": calibration,
        "total_frames": total_frames,
        "valid_frames": valid_frames,
        "valid_ratio": round(valid_frames / total_frames, 4) if total_frames else 0.0,
        "aoi_hits": hits,
        "aoi_hit_ratio": round(hits / valid_frames, 4) if valid_frames else 0.0,
        "target_median_aoi_hits": target_median_hits,
        "target_median_aoi_hit_ratio": (
            round(target_median_hits / len(target_medians), 4) if target_medians else 0.0
        ),
        "target_metrics": target_metrics,
        "failure_counts": dict(sorted(failures.items())),
        "error_px": metric_stats(errors_px),
        "error_screen_diagonal_ratio": metric_stats(errors_diagonal),
        "capture_to_result_ms": metric_stats(latencies),
        "observed_fps": round(total_frames / elapsed, 4) if elapsed else 0.0,
        "process_cpu_percent": metric_stats(cpu_samples),
        "peak_rss_bytes": max(rss_samples, default=process.memory_info().rss),
    }
    run["gate"] = evaluate_run_gate(run)
    return run


def _run_no_face(
    cap: cv2.VideoCapture,
    estimator: GazeEstimator,
    width: int,
    height: int,
) -> dict[str, Any]:
    readiness_started = time.perf_counter()
    consecutive_no_face = 0
    readiness_frames = 0
    readiness_confirmed = False
    while (elapsed := time.perf_counter() - readiness_started) < 20.0:
        frame, _ = _capture_frame(cap)
        if frame is not None:
            readiness_frames += 1
            features, _ = estimator.extract_features(frame)
            consecutive_no_face = consecutive_no_face + 1 if features is None else 0
            if consecutive_no_face >= 10:
                readiness_confirmed = True
                break
        _show_canvas(
            width,
            height,
            (
                "NO-FACE CHECK - STEP OUT OR COVER THE RGB CAMERA",
                f"Waiting for 10 no-face frames: {consecutive_no_face}/10",
                f"Timeout in {math.ceil(20.0 - elapsed)} seconds. Do not press a key.",
            ),
        )
    if not readiness_confirmed:
        return {
            "readiness_confirmed": False,
            "readiness_frame_count": readiness_frames,
            "readiness_seconds": round(time.perf_counter() - readiness_started, 4),
            "frame_count": 0,
            "no_face_frames": 0,
            "no_face_ratio": 0.0,
        }

    total = no_face = 0
    started = time.perf_counter()
    while (elapsed := time.perf_counter() - started) < 3.0:
        frame, _ = _capture_frame(cap)
        if frame is None:
            continue
        total += 1
        features, _ = estimator.extract_features(frame)
        if features is None:
            no_face += 1
        _show_canvas(
            width,
            height,
            ("NO-FACE CHECK - STAY OUT OF VIEW", f"frames: {total}"),
            progress=elapsed / 3.0,
        )
    return {
        "readiness_confirmed": True,
        "readiness_frame_count": readiness_frames,
        "readiness_seconds": round(time.perf_counter() - readiness_started, 4),
        "frame_count": total,
        "no_face_frames": no_face,
        "no_face_ratio": round(no_face / total, 4) if total else 0.0,
    }


def _git_value(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return process.stdout.strip()


def _default_output_path() -> Path:
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    return Path(__file__).resolve().parent / "results" / f"{stamp}-lg-laptop-live-summary.json"


def run_live(args: argparse.Namespace, model_path: Path) -> dict[str, Any]:
    polygons = load_product_polygons(args.manifest)
    calibration_points = calibration_points_for(args.calibration)
    screen = get_screen_geometry()
    screen_width, screen_height = int(screen["width"]), int(screen["height"])
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(args.camera, backend)
    if not cap.isOpened() and backend != cv2.CAP_ANY:
        cap.release()
        cap = cv2.VideoCapture(args.camera, cv2.CAP_ANY)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {args.camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.requested_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.requested_height)
    cap.set(cv2.CAP_PROP_FPS, args.requested_fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    if not args.windowed:
        cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    if sys.platform == "win32":
        cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_TOPMOST, 1)

    camera = {
        "index": args.camera,
        "friendly_name": args.camera_name,
        "requested_width": args.requested_width,
        "requested_height": args.requested_height,
        "requested_fps": args.requested_fps,
        "actual_width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "actual_height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "actual_fps": round(float(cap.get(cv2.CAP_PROP_FPS)), 4),
        "backend": cap.getBackendName(),
    }
    runs: list[dict[str, Any]] = []
    no_face: dict[str, Any] = {
        "readiness_confirmed": False,
        "readiness_frame_count": 0,
        "readiness_seconds": 0.0,
        "frame_count": 0,
        "no_face_frames": 0,
        "no_face_ratio": 0.0,
    }
    camera_released = False
    try:
        _wait_for_space(
            screen_width,
            screen_height,
            (
                "MCM EYETRAX LIVE TEST",
                "No camera frames or per-frame gaze data are saved.",
                "Press SPACE to start. Press ESC to cancel.",
            ),
        )

        preflight_estimator = GazeEstimator(face_landmarker_model=model_path)
        try:
            preflight = _preflight(cap, preflight_estimator, screen_width, screen_height)
        finally:
            preflight_estimator.close()
        if not preflight["passed"]:
            raise RuntimeError("Face preflight did not collect enough valid frames")

        for run_index in range(1, args.runs + 1):
            calibration_attempts: list[dict[str, Any]] = []
            estimator: GazeEstimator | None = None
            for _ in range(2):
                if estimator is not None:
                    estimator.close()
                estimator = GazeEstimator(face_landmarker_model=model_path)
                calibration = _calibrate_once(
                    cap,
                    estimator,
                    screen_width,
                    screen_height,
                    calibration_points=calibration_points,
                    run_index=run_index,
                    run_total=args.runs,
                )
                calibration_attempts.append(calibration)
                if calibration["completed"]:
                    break
            assert estimator is not None
            calibration = {
                **calibration,
                "attempt_count": len(calibration_attempts),
                "attempts": calibration_attempts,
            }
            if not calibration["completed"]:
                estimator.close()
                failed = {
                    "run_index": run_index,
                    "calibration": calibration,
                    "total_frames": 0,
                    "valid_frames": 0,
                    "valid_ratio": 0.0,
                    "aoi_hits": 0,
                    "aoi_hit_ratio": 0.0,
                    "failure_counts": {"calibration_failed": 1},
                    "error_px": metric_stats([]),
                    "error_screen_diagonal_ratio": metric_stats([]),
                    "capture_to_result_ms": metric_stats([]),
                    "observed_fps": 0.0,
                    "process_cpu_percent": metric_stats([]),
                    "peak_rss_bytes": psutil.Process().memory_info().rss,
                }
                failed["gate"] = evaluate_run_gate(failed)
                runs.append(failed)
                break
            try:
                run = _run_validation(
                    cap,
                    estimator,
                    polygons,
                    screen_width,
                    screen_height,
                    run_index=run_index,
                    run_total=args.runs,
                    seed=args.seed,
                    calibration=calibration,
                )
                runs.append(run)
            finally:
                estimator.close()

        no_face_estimator = GazeEstimator(face_landmarker_model=model_path)
        try:
            no_face = _run_no_face(cap, no_face_estimator, screen_width, screen_height)
        finally:
            no_face_estimator.close()
    finally:
        cap.release()
        camera_released = not cap.isOpened()
        cv2.destroyAllWindows()

    no_face["camera_released"] = camera_released
    overall_gate = evaluate_overall_gate(runs, no_face)
    return {
        "schema_version": "1.0",
        "status": "completed",
        "result_scope": "single-participant development-PC live target accuracy",
        "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        "repository": {
            "head": _git_value("rev-parse", "HEAD"),
            "branch": _git_value("branch", "--show-current"),
        },
        "candidate": {
            "name": "EyeTrax",
            "version": eyetrax.__version__,
            "source_revision": EYETRAX_SOURCE_REVISION,
            "code_license": "MIT",
            "face_model_url": FACE_MODEL_URL,
            "face_model_sha256": FACE_MODEL_SHA256,
            "smoothing": "none",
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "screen": screen,
            "camera": camera,
        },
        "configuration": {
            "condition": args.condition,
            "calibration_mode": args.calibration,
            "participant_count": 1,
            "runs_requested": args.runs,
            "calibration_points": calibration_points,
            "validation_targets": VALIDATION_TARGETS,
            "manifest": str(args.manifest.relative_to(REPO_ROOT)).replace("\\", "/"),
            "gates": {
                "valid_ratio_min": VALID_RATIO_GATE,
                "aoi_hit_ratio_min": AOI_HIT_GATE,
                "latency_p95_ms_max": LATENCY_P95_GATE_MS,
                "no_face_ratio_min": NO_FACE_GATE,
            },
        },
        "privacy": {
            "self_consent": True,
            "raw_frame_saved": False,
            "per_frame_gaze_saved": False,
            "preview_saved": False,
        },
        "preflight": preflight,
        "runs": runs,
        "no_face": no_face,
        "overall_gate": overall_gate,
        "provisional_recommendation": provisional_recommendation(
            args.condition, args.runs, overall_gate["passed"]
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--camera-name", default="LGE Camera")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--calibration", choices=("9p", "dense5"), default="9p")
    parser.add_argument("--condition", choices=("baseline", "glasses", "head-motion"), default="baseline")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--requested-width", type=int, default=1280)
    parser.add_argument("--requested-height", type=int, default=720)
    parser.add_argument("--requested-fps", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=20260815)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--prepare-model", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    args.manifest = args.manifest.resolve()
    args.model_path = args.model_path.resolve()
    return args


def main() -> int:
    args = parse_args()
    model_path = ensure_face_model(args.model_path, offline=args.offline)
    print(f"Face model verified: {model_path} ({FACE_MODEL_SHA256})")
    if args.prepare_model:
        return 0

    output = (args.output or _default_output_path()).resolve()
    if output.exists():
        print(
            f"Refusing to overwrite an existing aggregate result; choose --output: {output}",
            file=sys.stderr,
        )
        return 1
    try:
        with native_face_model_path(model_path) as runtime_model_path:
            summary = run_live(args, runtime_model_path)
    except UserAbort as error:
        print(str(error), file=sys.stderr)
        return 130
    assert_privacy_safe_summary(summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Aggregate-only result: {output}")
    print(f"Overall gate passed: {summary['overall_gate']['passed']}")
    print(f"Recommendation: {summary['provisional_recommendation']}")
    return 0 if summary["overall_gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
