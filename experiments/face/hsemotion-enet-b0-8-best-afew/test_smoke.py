"""Unit tests for HSEmotion model asset verification."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import smoke


class ModelVerificationTest(unittest.TestCase):
    def test_matching_checksum_is_returned(self) -> None:
        content = b"verified model asset"
        expected = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.pt"
            model_path.write_bytes(content)

            self.assertEqual(smoke.verify_model(model_path, expected), expected)

    def test_existing_mismatch_fails_before_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.pt"
            model_path.write_bytes(b"corrupted model asset")

            with self.assertRaises(smoke.ModelChecksumError):
                smoke.ensure_model(
                    offline=True,
                    model_path=model_path,
                    expected_sha256=hashlib.sha256(b"expected").hexdigest(),
                )

    def test_download_mismatch_is_not_promoted_and_is_cleaned_up(self) -> None:
        def write_unexpected_asset(_url: str, destination: Path) -> None:
            Path(destination).write_bytes(b"unexpected download")

        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.pt"
            temporary_path = model_path.with_suffix(".download")
            with patch.object(
                smoke.urllib.request,
                "urlretrieve",
                side_effect=write_unexpected_asset,
            ):
                with self.assertRaises(smoke.ModelChecksumError):
                    smoke.ensure_model(
                        offline=False,
                        model_path=model_path,
                        model_url="https://example.invalid/model.pt",
                        expected_sha256=hashlib.sha256(b"expected").hexdigest(),
                    )

            self.assertFalse(model_path.exists())
            self.assertFalse(temporary_path.exists())

    def test_cli_reports_checksum_mismatch_with_exit_code_one(self) -> None:
        error = smoke.ModelChecksumError(expected="expected", actual="actual")
        with (
            patch.object(smoke, "ensure_model", side_effect=error),
            patch("sys.argv", ["smoke.py", "--offline"]),
            patch("builtins.print") as print_mock,
            self.assertRaises(SystemExit) as exit_context,
        ):
            smoke.main()

        self.assertEqual(exit_context.exception.code, 1)
        payload = json.loads(print_mock.call_args.args[0])
        self.assertEqual(payload["reason"], "model_checksum_mismatch")
        self.assertEqual(payload["expected_model_sha256"], "expected")
        self.assertEqual(payload["actual_model_sha256"], "actual")


if __name__ == "__main__":
    unittest.main()
