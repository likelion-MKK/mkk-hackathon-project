from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = REPOSITORY_ROOT / "services" / "eye" / "scripts" / "run_worker.py"


def test_root_entrypoint_prepares_private_worker_imports() -> None:
    result = subprocess.run(
        [sys.executable, str(ENTRYPOINT), "--check-imports"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Eye worker imports are ready."
