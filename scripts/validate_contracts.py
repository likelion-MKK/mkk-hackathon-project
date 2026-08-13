#!/usr/bin/env python3
"""Validate JSON Schemas and contract example documents.

The validator intentionally fails closed: every example must resolve to exactly
one schema, either through its filename or through an optional schema mapping
manifest.  It also rejects raw image/frame payload keys from event examples so
that an otherwise-valid contract cannot accidentally normalize transporting
camera data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

try:
    import yaml
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
except ImportError as exc:  # pragma: no cover - exercised before test collection
    print(
        "[ERROR] contract validator dependencies are missing. "
        "Run: python -m pip install -r requirements-contracts.txt",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


DRAFT_2020_12_URI = "https://json-schema.org/draft/2020-12/schema"
MAPPING_FILENAMES = {
    "schema-map.json",
    "example-schema-map.json",
    "_schema-map.json",
    "manifest.json",
}
EXAMPLE_SUFFIXES = (".example", ".examples", ".fixture", ".valid", ".invalid")

# Exact keys are intentionally conservative enough to permit metadata such as
# image_url, frame_id, and thumbnail_url while rejecting embedded media.
FORBIDDEN_EVENT_KEYS = {
    "base64",
    "blob",
    "frame",
    "frames",
    "frameblob",
    "framebytes",
    "framedata",
    "framepayload",
    "image",
    "images",
    "imageblob",
    "imagebytes",
    "imagedata",
    "imagepayload",
    "rawframe",
    "rawframes",
    "rawimage",
    "rawimages",
}
MEDIA_WORDS = ("frame", "image")
PAYLOAD_WORDS = ("base64", "binary", "blob", "bytes", "content", "data", "payload", "raw")
MODEL_WEIGHT_SUFFIXES = {
    ".bin",
    ".ckpt",
    ".engine",
    ".gguf",
    ".h5",
    ".joblib",
    ".keras",
    ".mlmodel",
    ".onnx",
    ".pb",
    ".pkl",
    ".pt",
    ".pth",
    ".safetensors",
    ".tflite",
}
IGNORED_ARTIFACT_DIRECTORIES = {".git", ".venv", "node_modules", "__pycache__"}


@dataclass(frozen=True)
class Issue:
    file: Path | None
    message: str


@dataclass(frozen=True)
class SchemaDocument:
    path: Path
    body: Mapping[str, Any]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=default_root,
        help="repository root (defaults to the parent of scripts/)",
    )
    return parser.parse_args(argv)


def path_key(path: Path) -> str:
    """Return a stable, case-normalized key for a local path."""

    return os.path.normcase(str(path.resolve()))


def display_path(path: Path | None, root: Path) -> str:
    if path is None:
        return "contracts"
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path, issues: list[Issue]) -> Any | None:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError:
        issues.append(Issue(path, "file does not exist"))
    except json.JSONDecodeError as exc:
        issues.append(
            Issue(path, f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        )
    except OSError as exc:
        issues.append(Issue(path, f"could not read file: {exc}"))
    return None


def json_pointer(parts: Iterable[Any]) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped) if escaped else "/"


def format_validation_error(error: Any) -> str:
    location = json_pointer(error.absolute_path)
    keyword = f" [{error.validator}]" if getattr(error, "validator", None) else ""
    return f"{location}: {error.message}{keyword}"


def load_schemas(
    schema_paths: Sequence[Path], issues: list[Issue]
) -> tuple[list[SchemaDocument], Registry]:
    schemas: list[SchemaDocument] = []
    registry: Registry = Registry()

    for path in schema_paths:
        body = read_json(path, issues)
        if body is None:
            continue
        if not isinstance(body, dict):
            issues.append(Issue(path, "schema root must be a JSON object"))
            continue

        dialect = body.get("$schema")
        if not isinstance(dialect, str) or dialect.rstrip("#") != DRAFT_2020_12_URI:
            issues.append(
                Issue(
                    path,
                    f"$schema must declare Draft 2020-12 ({DRAFT_2020_12_URI})",
                )
            )
            continue

        try:
            Draft202012Validator.check_schema(body)
        except SchemaError as exc:
            issues.append(Issue(path, "invalid Draft 2020-12 schema: " + format_validation_error(exc)))
            continue

        try:
            resource = Resource.from_contents(body, default_specification=DRAFT202012)
            registry = registry.with_resource(path.resolve().as_uri(), resource)
            schema_id = body.get("$id")
            if isinstance(schema_id, str) and urlparse(schema_id).scheme:
                registry = registry.with_resource(schema_id, resource)
        except Exception as exc:  # referencing exposes several implementation errors
            issues.append(Issue(path, f"could not register schema references: {exc}"))
            continue

        schemas.append(SchemaDocument(path.resolve(), body))

    return schemas, registry


def mapping_entries(body: Any) -> list[tuple[str, str]] | None:
    """Parse supported mapping-manifest shapes, or return None if not a map.

    Supported examples::

        {"examples": {"gaze.example.json": "../events/gaze.schema.json"}}
        {"mappings": [{"example": "gaze.json", "schema": "..."}]}
        {"gaze.example.json": "../events/gaze.schema.json"}
    """

    candidate: Any = body
    if isinstance(body, dict):
        for key in ("mappings", "examples", "schemaMap", "schema_map"):
            if key in body:
                candidate = body[key]
                break

    if isinstance(candidate, dict):
        if not candidate:
            return []
        if all(isinstance(key, str) and isinstance(value, str) for key, value in candidate.items()):
            # A direct object is accepted only when its values look like schema paths.
            if candidate is body and not all(value.endswith(".schema.json") for value in candidate.values()):
                return None
            return list(candidate.items())
        return None

    if isinstance(candidate, list):
        result: list[tuple[str, str]] = []
        for item in candidate:
            if not isinstance(item, dict):
                return None
            example = item.get("example", item.get("file", item.get("document")))
            schema = item.get("schema")
            if not isinstance(example, str) or not isinstance(schema, str):
                return None
            result.append((example, schema))
        return result

    return None


def resolve_example_reference(reference: str, manifest: Path, root: Path) -> Path:
    raw = Path(reference.replace("/", os.sep))
    if raw.is_absolute():
        return raw.resolve()
    if raw.parts and raw.parts[0].lower() in {"contracts", "data"}:
        return (root / raw).resolve()
    return (manifest.parent / raw).resolve()


def resolve_schema_reference(
    reference: str,
    manifest: Path,
    root: Path,
    schemas: Sequence[SchemaDocument],
) -> tuple[Path | None, str | None]:
    raw = Path(reference.replace("/", os.sep))
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw.resolve())
    else:
        if raw.parts and raw.parts[0].lower() == "contracts":
            candidates.append((root / raw).resolve())
        candidates.extend(
            [
                (manifest.parent / raw).resolve(),
                (root / "contracts" / raw).resolve(),
            ]
        )

    known = {path_key(schema.path): schema.path for schema in schemas}
    matches = {path_key(candidate): known[path_key(candidate)] for candidate in candidates if path_key(candidate) in known}

    # A basename-only mapping remains convenient as long as it is unambiguous.
    if not matches and len(raw.parts) == 1:
        for schema in schemas:
            if schema.path.name.lower() == raw.name.lower():
                matches[path_key(schema.path)] = schema.path

    if len(matches) == 1:
        return next(iter(matches.values())), None
    if len(matches) > 1:
        rendered = ", ".join(sorted(display_path(path, root) for path in matches.values()))
        return None, f"schema mapping is ambiguous: {rendered}"
    return None, f"mapped schema does not exist or is invalid: {reference}"


def load_explicit_mappings(
    example_paths: Sequence[Path],
    root: Path,
    schemas: Sequence[SchemaDocument],
    issues: list[Issue],
) -> tuple[dict[str, Path], set[str]]:
    mappings: dict[str, Path] = {}
    manifest_keys: set[str] = set()

    for manifest in example_paths:
        if manifest.name.lower() not in MAPPING_FILENAMES:
            continue
        local_issues: list[Issue] = []
        body = read_json(manifest, local_issues)
        if body is None:
            # Canonical mapping filenames should surface parse failures as map failures.
            issues.extend(local_issues)
            manifest_keys.add(path_key(manifest))
            continue
        entries = mapping_entries(body)
        if entries is None:
            # A generic manifest.json may itself be a contract example.
            if manifest.name.lower() != "manifest.json":
                issues.append(Issue(manifest, "mapping manifest has an unsupported shape"))
                manifest_keys.add(path_key(manifest))
            continue

        manifest_keys.add(path_key(manifest))
        for example_ref, schema_ref in entries:
            example_path = resolve_example_reference(example_ref, manifest, root)
            example_key = path_key(example_path)
            if not example_path.is_file():
                issues.append(Issue(manifest, f"mapped example does not exist: {example_ref}"))
                continue
            schema_path, error = resolve_schema_reference(schema_ref, manifest, root, schemas)
            if error is not None or schema_path is None:
                issues.append(Issue(manifest, f"{example_ref}: {error}"))
                continue
            previous = mappings.get(example_key)
            if previous is not None and path_key(previous) != path_key(schema_path):
                issues.append(Issue(manifest, f"conflicting schema mappings for {example_ref}"))
                continue
            mappings[example_key] = schema_path

    return mappings, manifest_keys


def schema_aliases(schema: SchemaDocument) -> set[str]:
    aliases = {schema.path.name[: -len(".schema.json")].lower()}
    schema_id = schema.body.get("$id")
    if isinstance(schema_id, str):
        tail = Path(urlparse(schema_id).path).name
        if tail.endswith(".schema.json"):
            aliases.add(tail[: -len(".schema.json")].lower())
    return aliases


def example_aliases(path: Path, root: Path) -> list[str]:
    name = path.name[: -len(".json")].lower()
    aliases = [name]
    changed = True
    while changed:
        changed = False
        for suffix in EXAMPLE_SUFFIXES:
            if aliases[-1].endswith(suffix):
                aliases.append(aliases[-1][: -len(suffix)])
                changed = True
                break

    relative = display_path(path, root).lower()
    if relative == "data/lookbooks/example/manifest.json":
        aliases.extend(["lookbook-manifest", "manifest"])
    elif relative == "data/products/catalog.example.json":
        aliases.extend(["product-catalog", "catalog"])
    return list(dict.fromkeys(aliases))


def infer_schema(
    example: Path,
    root: Path,
    schemas: Sequence[SchemaDocument],
) -> tuple[SchemaDocument | None, str | None]:
    aliases = example_aliases(example, root)
    matches: dict[str, SchemaDocument] = {}
    for schema in schemas:
        if schema_aliases(schema).intersection(aliases):
            matches[path_key(schema.path)] = schema

    if len(matches) == 1:
        return next(iter(matches.values())), None
    if len(matches) > 1:
        rendered = ", ".join(
            sorted(display_path(schema.path, root) for schema in matches.values())
        )
        return None, f"filename matches multiple schemas: {rendered}; add a schema mapping"
    return None, "no matching schema; rename the example or add a schema mapping"


def is_event_schema(schema: SchemaDocument, root: Path) -> bool:
    try:
        relative_parts = schema.path.relative_to(root / "contracts").parts
    except ValueError:
        relative_parts = schema.path.parts
    return "events" in {part.lower() for part in relative_parts[:-1]} or schema.body.get(
        "x-event-schema"
    ) is True


def normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def forbidden_event_key(key: str) -> bool:
    normalized = normalized_key(key)
    if normalized in FORBIDDEN_EVENT_KEYS:
        return True
    return any(media in normalized for media in MEDIA_WORDS) and any(
        payload in normalized for payload in PAYLOAD_WORDS
    )


def scan_event_payload(value: Any, location: tuple[Any, ...] = ()) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            next_location = (*location, key)
            if isinstance(key, str) and forbidden_event_key(key):
                yield f"{json_pointer(next_location)}: forbidden raw media payload key '{key}'"
            if isinstance(child, str) and child.lower().startswith("data:image/"):
                yield f"{json_pointer(next_location)}: inline image data URI is forbidden"
            yield from scan_event_payload(child, next_location)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from scan_event_payload(child, (*location, index))


def schema_by_path(schemas: Sequence[SchemaDocument]) -> dict[str, SchemaDocument]:
    return {path_key(schema.path): schema for schema in schemas}


def validate_document(
    path: Path,
    schema: SchemaDocument,
    registry: Registry,
    root: Path,
    issues: list[Issue],
) -> tuple[bool, bool]:
    body = read_json(path, issues)
    if body is None:
        return False, False

    validator_body: Mapping[str, Any] = schema.body
    if "$id" not in validator_body:
        validator_body = dict(validator_body)
        validator_body["$id"] = schema.path.as_uri()

    try:
        validator = Draft202012Validator(validator_body, registry=registry)
        errors = sorted(
            validator.iter_errors(body),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                tuple(str(part) for part in error.absolute_schema_path),
            ),
        )
    except Exception as exc:
        issues.append(
            Issue(path, f"could not validate against {display_path(schema.path, root)}: {exc}")
        )
        return True, False

    for error in errors:
        issues.append(
            Issue(
                path,
                f"against {display_path(schema.path, root)} - {format_validation_error(error)}",
            )
        )

    guarded = is_event_schema(schema, root)
    if guarded:
        for message in scan_event_payload(body):
            issues.append(Issue(path, message))
    return True, guarded


def assert_invalid_examples(
    invalid_dir: Path,
    root: Path,
    schemas: Sequence[SchemaDocument],
    registry: Registry,
    issues: list[Issue],
) -> int:
    """Ensure every intentional negative fixture is rejected."""

    paths = sorted(invalid_dir.rglob("*.json")) if invalid_dir.is_dir() else []
    if not paths:
        issues.append(Issue(invalid_dir, "no intentional invalid example files found"))
        return 0

    checked = 0
    for path in paths:
        schema, error = infer_schema(path, root, schemas)
        if error is not None or schema is None:
            issues.append(Issue(path, error or "could not resolve schema for invalid example"))
            continue

        body = read_json(path, issues)
        if body is None:
            continue

        validator_body: Mapping[str, Any] = schema.body
        if "$id" not in validator_body:
            validator_body = dict(validator_body)
            validator_body["$id"] = schema.path.as_uri()

        try:
            validator = Draft202012Validator(validator_body, registry=registry)
            schema_errors = list(validator.iter_errors(body))
        except Exception as exc:
            issues.append(Issue(path, f"could not run negative validation: {exc}"))
            continue

        guard_errors = list(scan_event_payload(body)) if is_event_schema(schema, root) else []
        if not schema_errors and not guard_errors:
            issues.append(
                Issue(
                    path,
                    f"intentional invalid example unexpectedly passed {display_path(schema.path, root)}",
                )
            )
            continue
        checked += 1

    return checked


def duplicate_values(items: Sequence[Any]) -> set[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for item in items:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    return duplicates


def validate_cross_document_invariants(root: Path, issues: list[Issue]) -> None:
    """Validate relationships JSON Schema cannot express across documents."""

    manifest_path = root / "data" / "lookbooks" / "example" / "manifest.json"
    catalog_path = root / "data" / "products" / "catalog.example.json"
    batch_path = root / "contracts" / "examples" / "reaction-batch.valid.json"
    recommendation_path = (
        root / "contracts" / "examples" / "recommendation-result.valid.json"
    )
    conversion_path = root / "contracts" / "examples" / "conversion-outcome.valid.json"

    manifest = read_json(manifest_path, issues)
    catalog = read_json(catalog_path, issues)
    batch = read_json(batch_path, issues)
    recommendation = read_json(recommendation_path, issues)
    conversion = read_json(conversion_path, issues)

    catalog_ids: set[str] = set()
    if isinstance(catalog, dict) and isinstance(catalog.get("products"), list):
        product_ids = [
            product.get("product_id")
            for product in catalog["products"]
            if isinstance(product, dict) and isinstance(product.get("product_id"), str)
        ]
        duplicates = duplicate_values(product_ids)
        if duplicates:
            issues.append(Issue(catalog_path, f"duplicate product_id values: {sorted(duplicates)}"))
        catalog_ids = set(product_ids)

    if isinstance(manifest, dict) and isinstance(manifest.get("exposures"), list):
        exposure_ids: list[str] = []
        for index, exposure in enumerate(manifest["exposures"]):
            if not isinstance(exposure, dict):
                continue
            exposure_id = exposure.get("exposure_id")
            if isinstance(exposure_id, str):
                exposure_ids.append(exposure_id)
            start_ms = exposure.get("start_ms")
            end_ms = exposure.get("end_ms")
            if isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float)):
                if start_ms >= end_ms:
                    issues.append(
                        Issue(
                            manifest_path,
                            f"/exposures/{index}: start_ms must be less than end_ms",
                        )
                    )
            product_id = exposure.get("product_id")
            if isinstance(product_id, str) and catalog_ids and product_id not in catalog_ids:
                issues.append(
                    Issue(
                        manifest_path,
                        f"/exposures/{index}: unknown product_id '{product_id}'",
                    )
                )
        duplicates = duplicate_values(exposure_ids)
        if duplicates:
            issues.append(
                Issue(manifest_path, f"duplicate exposure_id values: {sorted(duplicates)}")
            )

    if isinstance(batch, dict) and isinstance(batch.get("events"), list):
        event_ids: list[str] = []
        sequences: list[int] = []
        for index, event in enumerate(batch["events"]):
            if not isinstance(event, dict):
                continue
            if isinstance(event.get("event_id"), str):
                event_ids.append(event["event_id"])
            if isinstance(event.get("sequence"), int):
                sequences.append(event["sequence"])
            if event.get("session_id") != batch.get("session_id"):
                issues.append(
                    Issue(batch_path, f"/events/{index}: session_id differs from batch envelope")
                )
            if event.get("video_id") != batch.get("video_id"):
                issues.append(
                    Issue(batch_path, f"/events/{index}: video_id differs from batch envelope")
                )
        duplicate_event_ids = duplicate_values(event_ids)
        if duplicate_event_ids:
            issues.append(
                Issue(batch_path, f"duplicate event_id values: {sorted(duplicate_event_ids)}")
            )
        duplicate_sequences = duplicate_values(sequences)
        if duplicate_sequences:
            issues.append(
                Issue(batch_path, f"duplicate event sequence values: {sorted(duplicate_sequences)}")
            )

    if isinstance(recommendation, dict):
        if recommendation.get("status") == "completed" and isinstance(
            recommendation.get("items"), list
        ):
            ranks = [item.get("rank") for item in recommendation["items"] if isinstance(item, dict)]
            product_ids = [
                item.get("product_id")
                for item in recommendation["items"]
                if isinstance(item, dict)
            ]
            if sorted(ranks) != [1, 2]:
                issues.append(Issue(recommendation_path, "completed Top 2 ranks must be 1 and 2"))
            if len(set(product_ids)) != len(product_ids):
                issues.append(Issue(recommendation_path, "completed Top 2 product_id values must differ"))
            unknown = sorted(
                product_id
                for product_id in product_ids
                if isinstance(product_id, str) and catalog_ids and product_id not in catalog_ids
            )
            if unknown:
                issues.append(
                    Issue(recommendation_path, f"unknown recommended product_id values: {unknown}")
                )
        if isinstance(manifest, dict):
            if recommendation.get("video_id") != manifest.get("video_id"):
                issues.append(Issue(recommendation_path, "video_id differs from lookbook manifest"))
            if recommendation.get("manifest_version") != manifest.get("manifest_version"):
                issues.append(
                    Issue(recommendation_path, "manifest_version differs from lookbook manifest")
                )

    if isinstance(conversion, dict):
        product_id = conversion.get("product_id")
        if isinstance(product_id, str) and catalog_ids and product_id not in catalog_ids:
            issues.append(Issue(conversion_path, f"unknown product_id '{product_id}'"))
        if isinstance(recommendation, dict) and conversion.get("recommendation_id") != recommendation.get(
            "recommendation_id"
        ):
            issues.append(
                Issue(conversion_path, "recommendation_id differs from recommendation fixture")
            )


def validate_openapi(root: Path, issues: list[Issue]) -> None:
    openapi_path = root / "contracts" / "openapi.yaml"
    try:
        with openapi_path.open("r", encoding="utf-8-sig") as handle:
            document = yaml.safe_load(handle)
    except FileNotFoundError:
        issues.append(Issue(openapi_path, "required OpenAPI file does not exist"))
        return
    except yaml.YAMLError as exc:
        issues.append(Issue(openapi_path, f"invalid YAML: {exc}"))
        return
    except OSError as exc:
        issues.append(Issue(openapi_path, f"could not read file: {exc}"))
        return

    if not isinstance(document, dict):
        issues.append(Issue(openapi_path, "OpenAPI root must be an object"))
        return
    if document.get("openapi") != "3.1.0":
        issues.append(Issue(openapi_path, "OpenAPI version must be 3.1.0 for FastAPI compatibility"))
    if not isinstance(document.get("info"), dict):
        issues.append(Issue(openapi_path, "missing info object"))
    paths = document.get("paths")
    if not isinstance(paths, dict):
        issues.append(Issue(openapi_path, "missing paths object"))
        return

    required_paths = {
        "/api/v1/sessions",
        "/api/v1/lookbooks/{lookbook_id}/manifest",
        "/api/v1/sessions/{session_id}/reaction-batches",
        "/api/v1/sessions/{session_id}/complete",
        "/api/v1/sessions/{session_id}/recommendations",
        "/api/v1/sessions/{session_id}/manager-product-requests",
        "/api/v1/products/{product_id}",
        "/api/v1/conversions",
        "/api/v1/manager/events",
        "/api/v1/health",
    }
    missing_paths = sorted(required_paths.difference(paths))
    if missing_paths:
        issues.append(Issue(openapi_path, f"missing required API paths: {missing_paths}"))

    for pointer, message in (("components", "missing components object"),):
        if not isinstance(document.get(pointer), dict):
            issues.append(Issue(openapi_path, message))

    def walk_refs(value: Any, location: tuple[Any, ...] = ()) -> Iterable[tuple[str, str]]:
        if isinstance(value, dict):
            for key, child in value.items():
                next_location = (*location, key)
                if key == "$ref" and isinstance(child, str):
                    yield json_pointer(next_location), child
                yield from walk_refs(child, next_location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk_refs(child, (*location, index))

    for pointer, reference in walk_refs(document):
        if reference.startswith("./"):
            target = (openapi_path.parent / reference).resolve()
            if not target.is_file():
                issues.append(Issue(openapi_path, f"{pointer}: missing local $ref target {reference}"))

    for message in scan_event_payload(document):
        issues.append(Issue(openapi_path, message))


def validate_repository_artifacts(root: Path, issues: list[Issue]) -> None:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in IGNORED_ARTIFACT_DIRECTORIES for part in relative.parts):
            continue
        if path.suffix.lower() in MODEL_WEIGHT_SUFFIXES:
            issues.append(Issue(path, "model weight or serialized model file must not be committed"))
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            issues.append(Issue(path, f"could not inspect file size: {exc}"))
            continue
        if size > 25 * 1024 * 1024:
            issues.append(
                Issue(
                    path,
                    "file exceeds 25 MiB; use an approved asset or LFS workflow instead of normal Git",
                )
            )


def print_issues(issues: Sequence[Issue], root: Path) -> None:
    grouped: dict[str, list[str]] = defaultdict(list)
    for issue in issues:
        grouped[display_path(issue.file, root)].append(issue.message)

    print(f"[FAIL] contract validation found {len(issues)} issue(s):", file=sys.stderr)
    for file_name in sorted(grouped):
        print(f"- {file_name}", file=sys.stderr)
        for message in grouped[file_name]:
            print(f"  - {message}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    contracts_dir = root / "contracts"
    examples_dir = contracts_dir / "examples"
    issues: list[Issue] = []

    schema_paths = sorted(contracts_dir.rglob("*.schema.json")) if contracts_dir.is_dir() else []
    if not schema_paths:
        issues.append(Issue(contracts_dir, "no contracts/**/*.schema.json files found"))

    schemas, registry = load_schemas(schema_paths, issues)
    for schema in schemas:
        if is_event_schema(schema, root):
            for message in scan_event_payload(schema.body):
                issues.append(Issue(schema.path, message))
    example_paths = sorted(examples_dir.glob("*.json")) if examples_dir.is_dir() else []
    explicit_mappings, mapping_manifest_keys = load_explicit_mappings(
        example_paths, root, schemas, issues
    )
    contract_examples = [
        path for path in example_paths if path_key(path) not in mapping_manifest_keys
    ]
    if not contract_examples:
        issues.append(Issue(examples_dir, "no contracts/examples/*.json example files found"))

    required_data_documents = [
        root / "data" / "lookbooks" / "example" / "manifest.json",
        root / "data" / "products" / "catalog.example.json",
    ]
    documents = [*contract_examples, *required_data_documents]
    known_schemas = schema_by_path(schemas)
    validated_count = 0
    guarded_count = 0

    for document in documents:
        if not document.is_file():
            issues.append(Issue(document, "required example file does not exist"))
            continue

        mapped_path = explicit_mappings.get(path_key(document))
        if mapped_path is not None:
            schema = known_schemas.get(path_key(mapped_path))
            if schema is None:
                issues.append(Issue(document, "mapped schema is unavailable because it is invalid"))
                continue
        else:
            schema, error = infer_schema(document, root, schemas)
            if error is not None or schema is None:
                issues.append(Issue(document, error or "could not resolve schema"))
                continue

        parsed, guarded = validate_document(document, schema, registry, root, issues)
        validated_count += int(parsed)
        guarded_count += int(parsed and guarded)

    invalid_count = assert_invalid_examples(
        examples_dir / "invalid", root, schemas, registry, issues
    )
    validate_cross_document_invariants(root, issues)
    validate_openapi(root, issues)
    validate_repository_artifacts(root, issues)

    if issues:
        print_issues(issues, root)
        return 1

    print(
        "[OK] contract validation passed: "
        f"{len(schemas)} schema file(s), {validated_count} example document(s), "
        f"{invalid_count} rejected negative example(s), "
        f"{guarded_count} event example guard check(s), event schemas, OpenAPI, "
        "cross-document invariants and repository artifacts checked."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
