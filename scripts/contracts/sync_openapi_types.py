from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main import app

DEFAULT_OPENAPI_OUTPUT = PROJECT_ROOT / "src" / "frontend" / "openapi" / "openapi.json"
DEFAULT_TYPES_OUTPUT = PROJECT_ROOT / "src" / "frontend" / "src" / "api" / "generated" / "openapi-types.ts"
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "options", "head", "trace")
TS_IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_$]")
TS_SAFE_PROP_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
PRIMITIVE_TS_TYPE = {
    "string": "string",
    "number": "number",
    "integer": "number",
    "boolean": "boolean",
    "null": "null",
}


def _resolve_path(path_like: str) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    canonical = _canonicalize(value)
    return json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _schema_hash(schema: dict[str, Any]) -> str:
    payload = _canonical_json(schema).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_live_schema() -> dict[str, Any]:
    app.openapi_schema = None
    schema = app.openapi()
    if not isinstance(schema, dict):
        raise RuntimeError("FastAPI app.openapi() did not return dict")
    return _canonicalize(schema)


def _extract_path_methods(schema: dict[str, Any]) -> dict[str, list[str]]:
    paths = schema.get("paths", {})
    if not isinstance(paths, dict):
        return {}

    result: dict[str, list[str]] = {}
    for path_name in sorted(paths):
        raw_item = paths.get(path_name, {})
        if not isinstance(raw_item, dict):
            continue
        methods = [method for method in HTTP_METHODS if method in raw_item]
        if methods:
            result[path_name] = methods
    return result


def _extract_operation_ids(schema: dict[str, Any]) -> dict[str, dict[str, str]]:
    paths = schema.get("paths", {})
    if not isinstance(paths, dict):
        return {}

    result: dict[str, dict[str, str]] = {}
    for path_name in sorted(paths):
        raw_item = paths.get(path_name, {})
        if not isinstance(raw_item, dict):
            continue
        item_result: dict[str, str] = {}
        for method in HTTP_METHODS:
            operation = raw_item.get(method, {})
            if not isinstance(operation, dict):
                continue
            operation_id = str(operation.get("operationId", "")).strip()
            if operation_id:
                item_result[method] = operation_id
        if item_result:
            result[path_name] = item_result
    return result


def _extract_components(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components = schema.get("components", {})
    if not isinstance(components, dict):
        return {}
    schemas = components.get("schemas", {})
    if not isinstance(schemas, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for schema_name in sorted(schemas):
        raw_schema = schemas[schema_name]
        if isinstance(raw_schema, dict):
            result[schema_name] = raw_schema
    return result


def _extract_request_schema_refs(schema: dict[str, Any]) -> dict[str, dict[str, str]]:
    paths = schema.get("paths", {})
    if not isinstance(paths, dict):
        return {}

    result: dict[str, dict[str, str]] = {}
    for path_name in sorted(paths):
        path_item = paths.get(path_name, {})
        if not isinstance(path_item, dict):
            continue
        method_map: dict[str, str] = {}
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            request_schema = (
                operation.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if not isinstance(request_schema, dict):
                continue
            ref = request_schema.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                method_map[method] = ref.rsplit("/", 1)[-1]
        if method_map:
            result[path_name] = method_map
    return result


def _ts_identifier(raw: str) -> str:
    value = TS_IDENTIFIER_RE.sub("_", raw).strip("_")
    if not value:
        value = "Schema"
    if value[0].isdigit():
        value = f"Schema_{value}"
    return value


def _quote_prop_key(key: str) -> str:
    if TS_SAFE_PROP_RE.match(key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _uniq(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        normalized = part.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _needs_wrap(expr: str) -> bool:
    return (" | " in expr or " & " in expr) and not expr.startswith("(")


def _resolve_component_aliases(component_schemas: dict[str, dict[str, Any]]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    used: set[str] = set()
    for schema_name in sorted(component_schemas):
        base = _ts_identifier(schema_name)
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        aliases[schema_name] = candidate
        used.add(candidate)
    return aliases


def _schema_to_ts(
    schema: Any,
    component_aliases: dict[str, str],
) -> str:
    if not isinstance(schema, dict):
        return "unknown"

    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        ref_name = ref.rsplit("/", 1)[-1]
        return component_aliases.get(ref_name, _ts_identifier(ref_name))

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        parts = [json.dumps(item, ensure_ascii=False) for item in enum_values]
        base = " | ".join(_uniq(parts))
        if schema.get("nullable") is True and "null" not in parts:
            return f"{base} | null"
        return base

    const_value = schema.get("const")
    if const_value is not None:
        base = json.dumps(const_value, ensure_ascii=False)
        if schema.get("nullable") is True and base != "null":
            return f"{base} | null"
        return base

    for union_key in ("anyOf", "oneOf"):
        union_schemas = schema.get(union_key)
        if isinstance(union_schemas, list) and union_schemas:
            union_parts = _uniq([_schema_to_ts(item, component_aliases) for item in union_schemas])
            base = " | ".join(union_parts) if union_parts else "unknown"
            if schema.get("nullable") is True and "null" not in union_parts:
                base = f"{base} | null"
            return base

    all_of = schema.get("allOf")
    if isinstance(all_of, list) and all_of:
        intersection_parts = _uniq([_schema_to_ts(item, component_aliases) for item in all_of])
        base = " & ".join(intersection_parts) if intersection_parts else "unknown"
        if schema.get("nullable") is True and "null" not in intersection_parts:
            base = f"{base} | null"
        return base

    schema_type = schema.get("type")

    if schema_type == "array":
        items = _schema_to_ts(schema.get("items", {}), component_aliases)
        if _needs_wrap(items):
            items = f"({items})"
        base = f"Array<{items}>"
        if schema.get("nullable") is True:
            return f"{base} | null"
        return base

    if schema_type == "object" or "properties" in schema or "additionalProperties" in schema:
        properties = schema.get("properties", {})
        required_list = schema.get("required", [])
        required = set(required_list) if isinstance(required_list, list) else set()
        object_parts: list[str] = []

        if isinstance(properties, dict):
            for prop_name in sorted(properties):
                prop_schema = properties[prop_name]
                prop_type = _schema_to_ts(prop_schema, component_aliases)
                optional = "" if prop_name in required else "?"
                object_parts.append(f"{_quote_prop_key(prop_name)}{optional}: {prop_type}")

        additional = schema.get("additionalProperties")
        if additional is True:
            object_parts.append("[key: string]: unknown")
        elif isinstance(additional, dict):
            additional_type = _schema_to_ts(additional, component_aliases)
            object_parts.append(f"[key: string]: {additional_type}")

        if object_parts:
            base = "{ " + "; ".join(object_parts) + " }"
        elif additional is False:
            base = "Record<string, never>"
        else:
            base = "Record<string, unknown>"

        if schema.get("nullable") is True:
            return f"{base} | null"
        return base

    if isinstance(schema_type, list) and schema_type:
        mapped: list[str] = []
        for item_type in schema_type:
            if item_type in PRIMITIVE_TS_TYPE:
                mapped.append(PRIMITIVE_TS_TYPE[item_type])
            elif item_type == "array":
                array_expr = _schema_to_ts({**schema, "type": "array"}, component_aliases)
                mapped.append(array_expr)
            elif item_type == "object":
                object_expr = _schema_to_ts({**schema, "type": "object"}, component_aliases)
                mapped.append(object_expr)
            else:
                mapped.append("unknown")
        base = " | ".join(_uniq(mapped)) if mapped else "unknown"
        if schema.get("nullable") is True and "null" not in mapped:
            base = f"{base} | null"
        return base

    if isinstance(schema_type, str) and schema_type in PRIMITIVE_TS_TYPE:
        base = PRIMITIVE_TS_TYPE[schema_type]
        if schema.get("nullable") is True and base != "null":
            return f"{base} | null"
        return base

    base = "unknown"
    if schema.get("nullable") is True:
        return f"{base} | null"
    return base


def _render_component_types(component_schemas: dict[str, dict[str, Any]]) -> tuple[str, list[str], dict[str, str]]:
    if not component_schemas:
        return (
            "export const OPENAPI_COMPONENT_SCHEMA_NAMES = [] as const;\n"
            "export interface OpenApiComponentSchemaMap {}\n"
            "export type OpenApiComponentSchemaName = keyof OpenApiComponentSchemaMap;\n\n",
            [],
            {},
        )

    component_aliases = _resolve_component_aliases(component_schemas)
    component_names = sorted(component_schemas.keys())
    lines: list[str] = []

    names_literal = json.dumps(component_names, ensure_ascii=False, indent=2)
    lines.append(f"export const OPENAPI_COMPONENT_SCHEMA_NAMES = {names_literal} as const;\n")

    for component_name in component_names:
        alias = component_aliases[component_name]
        ts_body = _schema_to_ts(component_schemas[component_name], component_aliases)
        lines.append(f"export type {alias} = {ts_body};\n")

    lines.append("export interface OpenApiComponentSchemaMap {")
    for component_name in component_names:
        alias = component_aliases[component_name]
        lines.append(f'  "{component_name}": {alias};')
    lines.append("}")
    lines.append("export type OpenApiComponentSchemaName = keyof OpenApiComponentSchemaMap;\n")

    return "\n".join(lines), component_names, component_aliases


def _render_types(schema: dict[str, Any], schema_hash: str) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    path_methods = _extract_path_methods(schema)
    operation_ids = _extract_operation_ids(schema)
    request_body_schemas = _extract_request_schema_refs(schema)
    component_schemas = _extract_components(schema)

    path_methods_literal = json.dumps(path_methods, ensure_ascii=False, indent=2)
    operation_ids_literal = json.dumps(operation_ids, ensure_ascii=False, indent=2)
    request_body_literal = json.dumps(request_body_schemas, ensure_ascii=False, indent=2)
    component_types_text, _, _ = _render_component_types(component_schemas)

    return (
        "// Auto-generated by scripts/contracts/sync_openapi_types.py\n"
        "// Do not edit manually.\n\n"
        f'export const OPENAPI_SCHEMA_HASH = "{schema_hash}";\n'
        f'export const OPENAPI_GENERATED_AT = "{generated_at}";\n\n'
        f"export const OPENAPI_PATH_METHODS = {path_methods_literal} as const;\n\n"
        "export type OpenApiPath = keyof typeof OPENAPI_PATH_METHODS;\n"
        "export type OpenApiMethod<P extends OpenApiPath> = (typeof OPENAPI_PATH_METHODS)[P][number];\n\n"
        f"export const OPENAPI_OPERATION_IDS = {operation_ids_literal} as const;\n"
        "export type OpenApiOperationPath = keyof typeof OPENAPI_OPERATION_IDS;\n\n"
        f"export const OPENAPI_REQUEST_BODY_SCHEMAS = {request_body_literal} as const;\n"
        "export type OpenApiRequestBodyPath = keyof typeof OPENAPI_REQUEST_BODY_SCHEMAS;\n\n"
        f"{component_types_text}"
    )


def sync_contract_artifacts(openapi_output: Path, types_output: Path) -> dict[str, Any]:
    schema = _load_live_schema()
    hash_value = _schema_hash(schema)

    openapi_output.parent.mkdir(parents=True, exist_ok=True)
    types_output.parent.mkdir(parents=True, exist_ok=True)

    openapi_output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    types_output.write_text(_render_types(schema, hash_value), encoding="utf-8")

    paths = schema.get("paths", {})
    methods_count = 0
    if isinstance(paths, dict):
        for item in paths.values():
            if isinstance(item, dict):
                methods_count += sum(1 for key in item if key in HTTP_METHODS)

    components = _extract_components(schema)
    request_refs = _extract_request_schema_refs(schema)
    request_ref_count = sum(len(methods) for methods in request_refs.values())

    return {
        "ok": True,
        "mode": "sync",
        "openapi_output": str(openapi_output),
        "types_output": str(types_output),
        "schema_hash": hash_value,
        "path_count": len(paths) if isinstance(paths, dict) else 0,
        "method_count": methods_count,
        "component_schema_count": len(components),
        "request_schema_ref_count": request_ref_count,
    }


def check_contract_artifacts(openapi_output: Path, types_output: Path) -> dict[str, Any]:
    schema = _load_live_schema()
    expected_hash = _schema_hash(schema)

    openapi_exists = openapi_output.exists()
    types_exists = types_output.exists()

    actual_openapi_hash = ""
    if openapi_exists:
        try:
            actual_schema = json.loads(openapi_output.read_text(encoding="utf-8"))
            if isinstance(actual_schema, dict):
                actual_openapi_hash = _schema_hash(actual_schema)
        except Exception:  # noqa: BLE001
            actual_openapi_hash = ""

    types_text = types_output.read_text(encoding="utf-8") if types_exists else ""
    hash_in_types = ""
    if types_text:
        marker = 'export const OPENAPI_SCHEMA_HASH = "'
        for line in types_text.splitlines():
            if marker in line:
                hash_in_types = line.split(marker, 1)[1].split('"', 1)[0]
                break

    checks = {
        "openapi_exists": openapi_exists,
        "types_exists": types_exists,
        "openapi_hash_matches_live": bool(actual_openapi_hash and actual_openapi_hash == expected_hash),
        "types_hash_matches_live": bool(hash_in_types and hash_in_types == expected_hash),
        "types_has_component_schema_names": "OPENAPI_COMPONENT_SCHEMA_NAMES" in types_text,
        "types_has_component_schema_map": "OpenApiComponentSchemaMap" in types_text,
        "types_has_request_schema_refs": "OPENAPI_REQUEST_BODY_SCHEMAS" in types_text,
    }
    ok = all(checks.values())

    return {
        "ok": ok,
        "mode": "check",
        "openapi_output": str(openapi_output),
        "types_output": str(types_output),
        "expected_schema_hash": expected_hash,
        "actual_openapi_hash": actual_openapi_hash,
        "actual_types_hash": hash_in_types,
        "checks": checks,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync/check OpenAPI snapshot and frontend type artifacts.")
    parser.add_argument("--openapi-output", default=str(DEFAULT_OPENAPI_OUTPUT))
    parser.add_argument("--types-output", default=str(DEFAULT_TYPES_OUTPUT))
    parser.add_argument("--check", action="store_true", help="Only check drift, do not write artifacts.")
    parser.add_argument("--report-output", default="", help="Optional JSON report output path.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    openapi_output = _resolve_path(args.openapi_output)
    types_output = _resolve_path(args.types_output)

    result = check_contract_artifacts(openapi_output, types_output) if args.check else sync_contract_artifacts(
        openapi_output, types_output
    )

    if args.report_output:
        report_path = _resolve_path(args.report_output)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
