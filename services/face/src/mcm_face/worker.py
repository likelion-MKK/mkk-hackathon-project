"""Face Worker boundary with deadline, metrics, and deterministic cleanup."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from mcm_face.adapter import FaceAdapter
from mcm_face.models import ExpressionSample, FaceFrameContext
from mcm_face.result import invalid_sample


@dataclass(frozen=True, slots=True)
class WorkerObservation:
    sample: ExpressionSample
    latency_ms: float
    frame_cleanup_deferred: bool = False
    adapter_completion: Future[Any] | None = field(
        default=None,
        repr=False,
        compare=False,
    )


def _close_frame(frame: Any) -> None:
    close = getattr(frame, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


class FaceWorker:
    def __init__(self, adapter: FaceAdapter[Any], *, timeout_ms: int = 500) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self._adapter = adapter
        self._timeout_ms = timeout_ms
        self._executor: ThreadPoolExecutor | None = None
        self._started = False
        self.timeout_count = 0
        self.error_count = 0

    def start(self) -> None:
        if self._started:
            return
        try:
            self._adapter.initialize()
            self._adapter.warmup()
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcm-face-worker")
            self._started = True
        except Exception:
            self.error_count += 1
            self._adapter.dispose()

    def process(self, frame: Any, context: FaceFrameContext) -> WorkerObservation:
        started = perf_counter()
        if not self._started or self._executor is None:
            del frame
            self.error_count += 1
            return WorkerObservation(
                invalid_sample(self._adapter.metadata(), context, reason="model_unavailable"),
                (perf_counter() - started) * 1000,
            )
        future = self._executor.submit(self._adapter.infer, frame, context)
        frame_cleanup_deferred = False
        adapter_completion: Future[Any] | None = None
        try:
            sample = future.result(timeout=self._timeout_ms / 1000)
        except FutureTimeout:
            if not future.cancel():
                # A running ThreadPool task cannot be cancelled. Keep the frame
                # alive until the adapter has really stopped reading it and make
                # that ownership transfer explicit to the caller.
                future.add_done_callback(
                    lambda _done, retained_frame=frame: _close_frame(retained_frame)
                )
                frame_cleanup_deferred = True
                adapter_completion = future
            self.timeout_count += 1
            sample = invalid_sample(self._adapter.metadata(), context, reason="timeout")
        except Exception:
            self.error_count += 1
            sample = invalid_sample(self._adapter.metadata(), context, reason="model_unavailable")
        del frame
        return WorkerObservation(
            sample,
            (perf_counter() - started) * 1000,
            frame_cleanup_deferred=frame_cleanup_deferred,
            adapter_completion=adapter_completion,
        )

    def close(self) -> None:
        executor, self._executor = self._executor, None
        self._started = False
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        self._adapter.dispose()

    def __enter__(self) -> "FaceWorker":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
