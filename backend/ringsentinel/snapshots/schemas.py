"""JSON schemas for every file in the snapshot bundle (data stage D12).

One schema per file name. The bundle is the only thing the API and the frontend read, so these
schemas are the contract between the offline pipeline and the online side. Bump
`SCHEMA_VERSION` whenever a schema changes in a way a reader would notice.
"""

SCHEMA_VERSION = "1"
ACTIONS = ("confirm", "dismiss", "hold")
RING_ID_PATTERN = "^R-[0-9a-f]{12}$"
_SHA256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_NUM = {"type": "number"}
_NUM_OR_NULL = {"type": ["number", "null"]}

_FEATURE = {
    "type": "object",
    "required": ["feature", "mean_contribution"],
    "additionalProperties": False,
    "properties": {"feature": {"type": "string"}, "mean_contribution": _NUM},
}

_COST = {
    "type": "object",
    "required": ["review_cost_inr", "fp_cost_inr", "loss_capture_rate"],
    "properties": {
        "review_cost_inr": _NUM, "fp_cost_inr": _NUM, "loss_capture_rate": _NUM,
        "note": {"type": "string"},
    },
}  # fmt: skip

META = {
    "type": "object",
    "required": [
        "schema_version", "bundle_id", "dataset_variant", "seed", "git_commit",
        "evaluation_frozen", "detector", "split", "n_rings_total", "n_rings_exported",
        "max_rings", "sources", "files",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "bundle_id": _SHA256,
        "dataset_variant": {"type": "string"},
        "seed": {"type": "integer"},
        "git_commit": {"type": "string"},
        "evaluation_frozen": {"type": "boolean"},
        "detector": {"type": "string"},
        "split": {"type": "string"},
        "n_rings_total": {"type": "integer", "minimum": 0},
        "n_rings_exported": {"type": "integer", "minimum": 0},
        "max_rings": {"type": "integer", "minimum": 1},
        "sources": {"type": "object", "additionalProperties": _SHA256},
        "files": {"type": "object", "additionalProperties": _SHA256},
    },
}  # fmt: skip

QUEUE = {
    "type": "object",
    "required": [
        "schema_version", "detector", "split", "threshold", "threshold_kind",
        "score_calibrated", "value_formula", "cost_assumptions", "items",
    ],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "detector": {"type": "string"},
        "split": {"type": "string"},
        "threshold": _NUM_OR_NULL,
        "threshold_kind": {"type": "string"},
        "score_calibrated": {"const": False},
        "value_formula": {"type": "string"},
        "cost_assumptions": _COST,
        "note": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "ring_id", "rank", "score", "expected_value_inr", "n_members",
                    "n_transfers", "amount_inr", "oversized", "top_features",
                ],
                "additionalProperties": False,
                "properties": {
                    "ring_id": {"type": "string", "pattern": RING_ID_PATTERN},
                    "rank": {"type": "integer", "minimum": 1},
                    "score": _NUM,
                    "expected_value_inr": _NUM,
                    "n_members": {"type": "integer", "minimum": 1},
                    "n_transfers": {"type": "integer", "minimum": 1},
                    "amount_inr": _NUM,
                    "oversized": {"type": "boolean"},
                    "top_features": {"type": "array", "items": _FEATURE},
                },
            },
        },
    },
}  # fmt: skip

_EDGE = {
    "type": "object",
    "required": ["src", "dst", "n_transfers", "total_inr", "first_ts", "last_ts"],
    "additionalProperties": False,
    "properties": {
        "src": {"type": "string"}, "dst": {"type": "string"},
        "n_transfers": {"type": "integer", "minimum": 1}, "total_inr": _NUM,
        "first_ts": {"type": "string"}, "last_ts": {"type": "string"},
    },
}  # fmt: skip

_AI_PLACEHOLDER = {
    "type": "object",
    "required": ["status", "built_in_stage"],
    "properties": {
        "status": {"enum": ["not_built", "ready"]},
        "built_in_stage": {"type": "string"},
        "investigator": {"type": ["object", "null"]},
        "verifier": {"type": ["object", "null"]},
        "benign_explanation": {"type": ["object", "null"]},
    },
}  # fmt: skip

CASES = {
    "type": "object",
    "required": ["schema_version", "cases"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "cases": {
            "type": "object",
            "propertyNames": {"pattern": RING_ID_PATTERN},
            "additionalProperties": {
                "type": "object",
                "required": [
                    "ring_id", "rank", "score", "expected_value_inr", "amount_inr", "n_members",
                    "n_transfers", "oversized", "members", "members_truncated", "top_features",
                    "edges", "edges_available", "edges_truncated", "ai",
                ],
                "additionalProperties": False,
                "properties": {
                    "ring_id": {"type": "string", "pattern": RING_ID_PATTERN},
                    "rank": {"type": "integer", "minimum": 1},
                    "score": _NUM,
                    "expected_value_inr": _NUM,
                    "amount_inr": _NUM,
                    "n_members": {"type": "integer", "minimum": 1},
                    "n_transfers": {"type": "integer", "minimum": 1},
                    "oversized": {"type": "boolean"},
                    "members": {"type": "array", "items": {"type": "string"}},
                    "members_truncated": {"type": "boolean"},
                    "top_features": {"type": "array", "items": _FEATURE},
                    "edges": {"type": "array", "items": _EDGE},
                    "edges_available": {"type": "boolean"},
                    "edges_truncated": {"type": "boolean"},
                    "ai": _AI_PLACEHOLDER,
                },
            },
        },
    },
}  # fmt: skip

METRICS = {
    "type": "object",
    "required": ["schema_version", "meta", "detectors", "cost_sweep"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "meta": {"type": "object"},
        "detectors": {"type": "object"},
        "cost_sweep": {"type": ["object", "array"]},
        "ablations": {"type": "object"},
        "robustness": {"type": "object"},
        "latency": {"type": "object"},
        "results_table_md": {"type": ["string", "null"]},
    },
}  # fmt: skip

DRIFT = {
    "type": "object",
    "required": ["schema_version", "status", "built_in_stage", "windows"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "status": {"enum": ["not_built", "ready"]},
        "built_in_stage": {"type": "string"},
        "psi_alert_level": _NUM_OR_NULL,
        "windows": {"type": "array", "items": {"type": "object"}},
    },
}  # fmt: skip

REPLAY = {
    "type": "object",
    "required": ["schema_version", "status", "built_in_stage", "events"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "status": {"enum": ["not_built", "ready"]},
        "built_in_stage": {"type": "string"},
        "events": {"type": "array", "items": {"type": "object"}},
    },
}  # fmt: skip

SCHEMAS = {
    "meta.json": META, "queue.json": QUEUE, "cases.json": CASES,
    "metrics.json": METRICS, "drift.json": DRIFT, "replay.json": REPLAY,
}  # fmt: skip
