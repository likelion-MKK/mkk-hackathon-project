"""Reproducible metrics-only benchmark for the D4 Face candidates."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = REPOSITORY_ROOT / "experiments" / "face"
FIXTURE_VERSION = "face-synthetic-d4-v1"
SYNTHETIC_SEED = 20260815
DEFAULT_COLD_RUNS = 3
DEFAULT_DURATION_SECONDS = 30
DEFAULT_FPS = (3, 5)

MEDIAPIPE = "mediapipe-face-landmarker"
OPENVINO = "openvino-emotions-retail-0003"
HSEMOTION = "hsemotion-enet-b0-8-best-afew"
CANDIDATES = (MEDIAPIPE, OPENVINO, HSEMOTION)

ASSETS: dict[str, tuple[dict[str, str], ...]] = {
    MEDIAPIPE: (
        {
            "name": "face_landmarker.task",
            "relative_path": "models/face_landmarker.task",
            "url": (
                "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                "face_landmarker/float16/1/face_landmarker.task"
            ),
            "sha256": (
                "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
            ),
        },
    ),
    OPENVINO: (
        {
            "name": "emotions-recognition-retail-0003.xml",
            "relative_path": "models/FP32/emotions-recognition-retail-0003.xml",
            "url": (
                "https://storage.openvinotoolkit.org/repositories/open_model_zoo/"
                "2023.0/models_bin/1/emotions-recognition-retail-0003/FP32/"
                "emotions-recognition-retail-0003.xml"
            ),
            "sha256": (
                "11768c788fdf242ac93fa749504674878e3c797a5dce5b1d874e387a6b88f1fc"
            ),
        },
        {
            "name": "emotions-recognition-retail-0003.bin",
            "relative_path": "models/FP32/emotions-recognition-retail-0003.bin",
            "url": (
                "https://storage.openvinotoolkit.org/repositories/open_model_zoo/"
                "2023.0/models_bin/1/emotions-recognition-retail-0003/FP32/"
                "emotions-recognition-retail-0003.bin"
            ),
            "sha256": (
                "faaef5507627692057ac3b4dcd465de23568d59677f0f71c36d06bb9947904da"
            ),
        },
    ),
    HSEMOTION: (
        {
            "name": "enet_b0_8_best_afew.pt",
            "relative_path": "models/enet_b0_8_best_afew.pt",
            "url": (
                "https://raw.githubusercontent.com/HSE-asavchenko/"
                "face-emotion-recognition/520a051c64cd191521e5934655314e769a319684/"
                "models/affectnet_emotions/enet_b0_8_best_afew.pt"
            ),
            "sha256": (
                "47c1423f3e6f50e3750bf7b0eda7db947c9ce0c2637e1766bf2187eddc652b17"
            ),
        },
    ),
}

PACKAGE_NAMES = {
    MEDIAPIPE: ("mediapipe", "numpy"),
    OPENVINO: ("openvino", "numpy"),
    HSEMOTION: ("hsemotion", "torch", "timm", "numpy"),
}


@dataclass
class RuntimeSession:
    infer: Callable[[str, int], dict[str, Any]]
    close: Callable[[], None]
    model_load_ms: float
    asset_access_ms: float
    model_sha256: dict[str, str]


class BenchmarkWorkerTimeoutError(RuntimeError):
    """Raised when an isolated benchmark worker exceeds its process deadline."""

    def __init__(self, arguments: list[str], timeout_seconds: int) -> None:
        self.stage = arguments[0].lstrip("_") if arguments else "unknown"
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"benchmark worker timed out during {self.stage} after "
            f"{timeout_seconds} seconds"
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_assets(candidate: str, *, offline: bool) -> tuple[dict[str, str], float]:
    started = time.perf_counter_ns()
    checksums: dict[str, str] = {}
    candidate_root = EXPERIMENT_ROOT / candidate
    for asset in ASSETS[candidate]:
        path = candidate_root / asset["relative_path"]
        if not path.is_file():
            if offline:
                raise FileNotFoundError(f"offline model asset is missing: {asset['name']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = path.with_suffix(path.suffix + ".download")
            try:
                urllib.request.urlretrieve(asset["url"], temporary_path)
                actual = file_sha256(temporary_path)
                if actual != asset["sha256"]:
                    raise ValueError(f"model checksum mismatch: {asset['name']}")
                temporary_path.replace(path)
            finally:
                temporary_path.unlink(missing_ok=True)
        actual = file_sha256(path)
        if actual != asset["sha256"]:
            raise ValueError(f"model checksum mismatch: {asset['name']}")
        checksums[asset["name"]] = actual
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return checksums, elapsed_ms


def synthetic_rgb(kind: str, frame_index: int) -> Any:
    import numpy as np

    if kind == "no_face":
        return np.zeros((256, 256, 3), dtype=np.uint8)
    if kind != "synthetic_crop":
        raise ValueError(f"unknown synthetic input kind: {kind}")

    pixels = np.full((256, 256, 3), 24, dtype=np.uint8)
    yy, xx = np.ogrid[:256, :256]
    head = ((xx - 128) ** 2) / (78**2) + ((yy - 128) ** 2) / (96**2) <= 1
    pixels[head] = (176, 144, 120)
    for eye_x in (98, 158):
        eye = (xx - eye_x) ** 2 + (yy - 108) ** 2 <= 8**2
        pixels[eye] = (32, 32, 32)
    mouth_y = 164 + (SYNTHETIC_SEED % 3)
    mouth = ((xx - 128) ** 2) / (34**2) + ((yy - mouth_y) ** 2) / (10**2) <= 1
    pixels[mouth] = (72, 28, 28)
    return pixels


def synthetic_input_sha256() -> dict[str, str]:
    return {
        kind: hashlib.sha256(synthetic_rgb(kind, 0).tobytes()).hexdigest()
        for kind in ("no_face", "synthetic_crop")
    }


def _resize_nearest(pixels: Any, size: int) -> Any:
    import numpy as np

    indices = np.linspace(0, pixels.shape[0] - 1, size).astype(int)
    return pixels[indices][:, indices]


def load_runtime(candidate: str, *, offline: bool) -> RuntimeSession:
    checksums, asset_access_ms = ensure_assets(candidate, offline=offline)
    load_started = time.perf_counter_ns()

    if candidate == MEDIAPIPE:
        import mediapipe as mp

        model_path = EXPERIMENT_ROOT / candidate / ASSETS[candidate][0]["relative_path"]
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=1,
            output_face_blendshapes=True,
        )
        landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        model_load_ms = (time.perf_counter_ns() - load_started) / 1_000_000

        def infer(kind: str, frame_index: int) -> dict[str, Any]:
            pixels = synthetic_rgb(kind, frame_index)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=pixels)
            result = landmarker.detect(image)
            scores: dict[str, float] = {}
            if result.face_blendshapes:
                scores = {
                    category.category_name: float(category.score)
                    for category in result.face_blendshapes[0]
                }
            return {
                "face_count": len(result.face_landmarks),
                "labels": sorted(scores),
                "output_shape": {
                    "face_landmark_groups": len(result.face_landmarks),
                    "blendshape_groups": len(result.face_blendshapes),
                    "blendshape_count": len(scores),
                },
                "scores": scores,
            }

        return RuntimeSession(
            infer=infer,
            close=landmarker.close,
            model_load_ms=model_load_ms,
            asset_access_ms=asset_access_ms,
            model_sha256=checksums,
        )

    if candidate == OPENVINO:
        import numpy as np
        import openvino as ov

        model_root = EXPERIMENT_ROOT / candidate / "models" / "FP32"
        core = ov.Core()
        model = core.read_model(model_root / "emotions-recognition-retail-0003.xml")
        compiled = core.compile_model(model, "CPU")
        output_port = compiled.output(0)
        labels = ("neutral", "happy", "sad", "surprise", "anger")
        model_load_ms = (time.perf_counter_ns() - load_started) / 1_000_000

        def infer(kind: str, frame_index: int) -> dict[str, Any]:
            rgb = _resize_nearest(synthetic_rgb(kind, frame_index), 64)
            bgr = rgb[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32)
            output = compiled([bgr])[output_port]
            values = output.reshape(-1)
            return {
                "face_count": None,
                "labels": list(labels),
                "output_shape": list(output.shape),
                "scores": {
                    label: float(score) for label, score in zip(labels, values, strict=True)
                },
            }

        return RuntimeSession(
            infer=infer,
            close=lambda: None,
            model_load_ms=model_load_ms,
            asset_access_ms=asset_access_ms,
            model_sha256=checksums,
        )

    raise ValueError(f"candidate cannot enter inference benchmark: {candidate}")


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile of an empty sequence")
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile_value / 100) * len(ordered)))
    return ordered[rank - 1]


def process_memory() -> dict[str, float | None]:
    if os.name != "nt":
        return {"rss_mib": None, "peak_working_set_mib": None}

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    )
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel32.GetCurrentProcess()
    success = psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(counters), counters.cb
    )
    if not success:
        return {"rss_mib": None, "peak_working_set_mib": None}
    divisor = 1024 * 1024
    return {
        "rss_mib": round(counters.WorkingSetSize / divisor, 3),
        "peak_working_set_mib": round(counters.PeakWorkingSetSize / divisor, 3),
    }


def summarize_output(output: dict[str, Any]) -> dict[str, Any]:
    scores = output["scores"]
    finite = all(math.isfinite(value) for value in scores.values())
    return {
        "face_count": output["face_count"],
        "labels": output["labels"],
        "output_shape": output["output_shape"],
        "score_count": len(scores),
        "scores_finite": finite,
    }


def output_signature(output: dict[str, Any]) -> str:
    serialized = json.dumps(output, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def cold_worker(candidate: str, *, offline: bool) -> dict[str, Any]:
    session = load_runtime(candidate, offline=offline)
    try:
        warmup_started = time.perf_counter_ns()
        no_face_output = session.infer("no_face", 0)
        warmup_ms = (time.perf_counter_ns() - warmup_started) / 1_000_000

        first_started = time.perf_counter_ns()
        first_output = session.infer("synthetic_crop", 1)
        first_inference_ms = (time.perf_counter_ns() - first_started) / 1_000_000
        return {
            "asset_access_ms": round(session.asset_access_ms, 6),
            "first_inference_ms": round(first_inference_ms, 6),
            "first_output": summarize_output(first_output),
            "memory": process_memory(),
            "model_load_ms": round(session.model_load_ms, 6),
            "model_sha256": session.model_sha256,
            "no_face_output": summarize_output(no_face_output),
            "warmup_ms": round(warmup_ms, 6),
        }
    finally:
        session.close()


def warm_worker(
    candidate: str, *, offline: bool, duration_seconds: int, fps_values: tuple[int, ...]
) -> dict[str, Any]:
    session = load_runtime(candidate, offline=offline)
    try:
        session.infer("no_face", 0)
        workloads: dict[str, Any] = {}
        for fps in fps_values:
            latencies: list[float] = []
            signatures: dict[str, set[str]] = {
                "no_face": set(),
                "synthetic_crop": set(),
            }
            failures = 0
            deadline_misses = 0
            frame_count = duration_seconds * fps
            workload_started = time.perf_counter_ns()
            for frame_index in range(frame_count):
                kind = "no_face" if frame_index % 2 == 0 else "synthetic_crop"
                inference_started = time.perf_counter_ns()
                try:
                    output = session.infer(kind, frame_index)
                except Exception:
                    failures += 1
                    continue
                latency_ms = (time.perf_counter_ns() - inference_started) / 1_000_000
                latencies.append(latency_ms)
                if latency_ms > 1000 / fps:
                    deadline_misses += 1
                signatures[kind].add(output_signature(output))
                if not summarize_output(output)["scores_finite"]:
                    failures += 1
            workload_elapsed_ms = (time.perf_counter_ns() - workload_started) / 1_000_000
            measured_sample_count = len(latencies)
            stability_observation = (
                "pass"
                if all(len(values) == 1 for values in signatures.values())
                else "fail"
            )
            workload_status = warm_workload_status(
                frame_count=frame_count,
                measured_sample_count=measured_sample_count,
                failure_count=failures,
                deadline_miss_count=deadline_misses,
                stability_observation=stability_observation,
            )
            workloads[str(fps)] = {
                "accelerated_schedule": True,
                "capacity_fps": round(1000 / (sum(latencies) / len(latencies)), 3)
                if latencies
                else 0.0,
                "deadline_miss_count": deadline_misses,
                "failure_count": failures,
                "frame_count": frame_count,
                "latency_p50_ms": round(percentile(latencies, 50), 6)
                if latencies
                else None,
                "latency_p95_ms": round(percentile(latencies, 95), 6)
                if latencies
                else None,
                "measured_sample_count": measured_sample_count,
                "requested_fps": fps,
                "stability_observation": stability_observation,
                "status": workload_status,
                "workload_duration_seconds": duration_seconds,
                "workload_elapsed_ms": round(workload_elapsed_ms, 6),
            }
        return {
            "memory": process_memory(),
            "model_sha256": session.model_sha256,
            "status": (
                "pass"
                if workloads
                and all(
                    workload["status"] == "pass"
                    for workload in workloads.values()
                )
                else "fail"
            ),
            "workloads": workloads,
        }
    finally:
        session.close()


def warm_workload_status(
    *,
    frame_count: int,
    measured_sample_count: int,
    failure_count: int,
    deadline_miss_count: int,
    stability_observation: str,
) -> str:
    complete = frame_count > 0 and measured_sample_count == frame_count
    return (
        "pass"
        if complete
        and failure_count == 0
        and deadline_miss_count == 0
        and stability_observation == "pass"
        else "fail"
    )


def package_versions(candidate: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in PACKAGE_NAMES[candidate]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not_installed"
    return versions


def run_child(arguments: list[str], *, timeout_seconds: int = 180) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise BenchmarkWorkerTimeoutError(arguments, timeout_seconds) from error
    if completed.returncode != 0:
        summary = completed.stderr.strip().splitlines()[-1:] or ["worker failed"]
        raise RuntimeError(f"benchmark worker failed: {summary[0]}")
    for line in reversed(completed.stdout.splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise RuntimeError("benchmark worker did not return JSON")


def hard_gate_result(candidate: str, *, offline: bool) -> dict[str, Any]:
    checksums, asset_access_ms = ensure_assets(candidate, offline=offline)
    return {
        "accuracy_claim": "none",
        "asset_access_ms": round(asset_access_ms, 6),
        "candidate": candidate,
        "device": "CPU",
        "hard_gate": "fail",
        "inference_benchmark": "excluded",
        "latency_measurement": "not_measured_hard_gate_exclusion",
        "model_sha256": checksums,
        "offline": offline,
        "package_versions": package_versions(candidate),
        "python_version": platform.python_version(),
        "quality_evaluation": "not_available_without_ground_truth",
        "reason": "unsafe_legacy_pickle_blocked",
        "stability_observation": "not_measured_hard_gate_exclusion",
        "status": "excluded",
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    if args.candidate == HSEMOTION:
        result = hard_gate_result(args.candidate, offline=args.offline)
    else:
        mode_flag = "--offline" if args.offline else "--online"
        try:
            cold_runs = [
                run_child(["_cold", args.candidate, mode_flag])
                for _ in range(args.cold_runs)
            ]
            warm = run_child(
                [
                    "_warm",
                    args.candidate,
                    mode_flag,
                    "--duration-seconds",
                    str(args.duration_seconds),
                    "--fps",
                    *(str(value) for value in args.fps),
                ]
            )
        except BenchmarkWorkerTimeoutError as error:
            result = {
                "accuracy_claim": "none",
                "candidate": args.candidate,
                "device": "CPU",
                "hard_gate": "fail",
                "inference_benchmark": "failed",
                "latency_measurement": "not_measured_worker_timeout",
                "offline": args.offline,
                "package_versions": package_versions(args.candidate),
                "python_version": platform.python_version(),
                "quality_evaluation": "not_available_without_ground_truth",
                "reason": "worker_timeout",
                "stability_observation": "not_measured_worker_timeout",
                "status": "fail",
                "timeout_stage": error.stage,
                "worker_timeout_seconds": error.timeout_seconds,
            }
        else:
            no_face = cold_runs[0]["no_face_output"]
            no_face_supported = args.candidate == MEDIAPIPE
            benchmark_status = warm.get("status", "fail")
            result = {
                "accuracy_claim": "none",
                "candidate": args.candidate,
                "cold_run_count": len(cold_runs),
                "cold_runs": cold_runs,
                "device": "CPU",
                "fixture_version": FIXTURE_VERSION,
                "hard_gate": "pass",
                "inference_benchmark": (
                    "measured" if benchmark_status == "pass" else "failed"
                ),
                "latency_measurement": "measured",
                "model_sha256": warm["model_sha256"],
                "no_face_return": no_face_supported and no_face["face_count"] == 0,
                "no_face_validation": (
                    "pass"
                    if no_face_supported and no_face["face_count"] == 0
                    else "not_supported_classifier_requires_face_crop"
                ),
                "offline": args.offline,
                "package_versions": package_versions(args.candidate),
                "python_version": platform.python_version(),
                "quality_evaluation": "not_available_without_ground_truth",
                "status": benchmark_status,
                "synthetic_input_sha256": synthetic_input_sha256(),
                "synthetic_seed": SYNTHETIC_SEED,
                "warm": warm,
            }
            stability = [
                workload["stability_observation"]
                for workload in warm["workloads"].values()
            ]
            result["stability_observation"] = (
                "pass"
                if stability and all(value == "pass" for value in stability)
                else "fail"
            )
            if benchmark_status == "fail":
                result["reason"] = "warm_workload_failed"

    result["environment"] = {
        "architecture": platform.machine(),
        "logical_processors": os.cpu_count(),
        "os": platform.platform(),
        "python_implementation": platform.python_implementation(),
    }
    return result


def write_artifact(candidate: str, result: dict[str, Any], output: Path | None) -> Path:
    mode = "offline" if result["offline"] else "online"
    destination = output or EXPERIMENT_ROOT / candidate / "artifacts" / f"d4-{mode}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("candidate", choices=CANDIDATES)
    mode = run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--online", action="store_true")
    mode.add_argument("--offline", action="store_true")
    run.add_argument("--cold-runs", type=int, default=DEFAULT_COLD_RUNS)
    run.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    run.add_argument("--fps", type=int, nargs="+", default=list(DEFAULT_FPS))
    run.add_argument("--output", type=Path)

    for command in ("_cold", "_warm"):
        worker = subparsers.add_parser(command)
        worker.add_argument("candidate", choices=(MEDIAPIPE, OPENVINO))
        worker_mode = worker.add_mutually_exclusive_group(required=True)
        worker_mode.add_argument("--online", action="store_true")
        worker_mode.add_argument("--offline", action="store_true")
        if command == "_warm":
            worker.add_argument("--duration-seconds", type=int, required=True)
            worker.add_argument("--fps", type=int, nargs="+", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "_cold":
        print(json.dumps(cold_worker(args.candidate, offline=args.offline), sort_keys=True))
        return
    if args.command == "_warm":
        print(
            json.dumps(
                warm_worker(
                    args.candidate,
                    offline=args.offline,
                    duration_seconds=args.duration_seconds,
                    fps_values=tuple(args.fps),
                ),
                sort_keys=True,
            )
        )
        return

    if args.cold_runs < 1 or args.duration_seconds < 1 or any(fps < 1 for fps in args.fps):
        raise SystemExit("cold-runs, duration-seconds and fps must be positive")
    result = run_benchmark(args)
    artifact_path = write_artifact(args.candidate, result, args.output)
    print(
        json.dumps(
            {
                "artifact": str(artifact_path),
                "candidate": args.candidate,
                "hard_gate": result["hard_gate"],
                "offline": args.offline,
                "status": result["status"],
            },
            sort_keys=True,
        )
    )
    if result["status"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
