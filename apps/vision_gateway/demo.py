"""Run the deterministic D7 in-process vertical slice from the API environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.app.main import create_app
from apps.api.app.store import MemoryStore
from apps.vision_gateway.runner import D7RunConfig, D7SessionRunner, HttpBackendPort
from mcm_face import FaceWorker, FakeFaceAdapter, ReplayFaceAdapter


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="D7 synthetic/replay in-process E2E")
    parser.add_argument("--mode", choices=("synthetic", "replay"), default="synthetic")
    args = parser.parse_args()
    fixture = ROOT / "services" / "face" / "tests" / "fixtures" / "expression-replay.d3.json"

    def worker_factory() -> FaceWorker:
        adapter = ReplayFaceAdapter.from_fixture(fixture) if args.mode == "replay" else FakeFaceAdapter()
        return FaceWorker(adapter, timeout_ms=100)

    store = MemoryStore(ROOT)
    with TestClient(create_app(store)) as client:
        runner = D7SessionRunner(
            backend=HttpBackendPort(client),
            face_worker_factory=worker_factory,
            config=D7RunConfig(input_mode=args.mode),
        )
        session_id = runner.start()
        observations = [runner.process_frame(index)[0] for index in range(2)]
        recommendation = runner.close()
        print(
            json.dumps(
                {
                    "transport": "d7-in-process-harness",
                    "input_mode": args.mode,
                    "recommendation_mode": recommendation["engine_mode"],
                    "session_id": session_id,
                    "frame_ids": [item.gaze.frame_id for item in observations],
                    "face_reasons": [item.face.reason for item in observations],
                    "top_two": recommendation["items"],
                    "status": recommendation["status"],
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
