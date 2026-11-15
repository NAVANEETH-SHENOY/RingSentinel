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

_VERIFIER = {
    "type": "object",
    "required": ["status", "issues", "warnings", "checked", "coverage", "attempts"],
    "properties": {
        "status": {"enum": ["verified", "unverified"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "checked": {"type": "object"},
        "coverage": {"enum": ["full", "partial", "none"]},
        "attempts": {"type": "integer", "minimum": 1},
    },
}  # fmt: skip

# The AI block of one case (Stage 06). `not_built` is the Stage 04 placeholder. A `ready` block
# always carries a case file and a verifier result; the benign (devil's advocate) pass is
# optional because it only runs when the first pass verified.
_AI = {
    "type": "object",
    "required": ["status", "built_in_stage"],
    "additionalProperties": False,
    "properties": {
        "status": {"enum": ["not_built", "ready"]},
        "built_in_stage": {"type": "string"},
        "source": {"enum": ["llm", "cache", "template"]},
        "input_hash": _SHA256,
        "prompt_version": {"type": "string"},
        "provider": {"type": ["object", "null"]},
        "investigator": {"type": ["object", "null"]},
        "verifier": {"anyOf": [_VERIFIER, {"type": "null"}]},
        "benign_explanation": {"type": ["object", "null"]},
        "benign_failure_reason": {"type": ["string", "null"]},
        "benign_verifier": {"anyOf": [_VERIFIER, {"type": "null"}]},
        "contested": {"type": "boolean"},
        "contested_reason": {"type": ["string", "null"]},
        "trace": {"type": "object"},
        "fallback_kind": {
            "enum": [None, "no_provider", "outside_limit", "provider_error", "no_valid_output"]
        },
        "fallback_reason": {"type": ["string", "null"]},
    },
    "if": {"properties": {"status": {"const": "ready"}}, "required": ["status"]},
    "then": {
        "required": [
            "source", "input_hash", "prompt_version", "investigator", "verifier", "contested",
            "trace",
        ],
        "properties": {"investigator": {"type": "object"}, "verifier": {"type": "object"}},
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
                    "ai": _AI,
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

# Drift (Stage 07, data stage D11). `not_built` is the Stage 04 placeholder; a `ready` document
# carries the windows, the PSI levels and a summary. Added fields are optional so old placeholders
# stay valid and SCHEMA_VERSION stays "1".
_DRIFT_WINDOW = {
    "type": "object",
    "required": ["index", "start_ts", "end_ts", "n_events", "psi", "level"],
    "properties": {
        "index": {"type": "integer", "minimum": 0},
        "start_ts": {"type": "string"}, "end_ts": {"type": "string"},
        "n_events": {"type": "integer", "minimum": 0},
        "psi": _NUM_OR_NULL,
        "level": {"enum": ["ok", "warn", "alert", "insufficient"]},
        "mean_score": _NUM_OR_NULL, "n_positives": {"type": "integer", "minimum": 0},
        "n_flagged": {"type": "integer", "minimum": 0}, "flagged_rate": _NUM_OR_NULL,
        "precision_at_threshold": _NUM_OR_NULL, "recall_at_threshold": _NUM_OR_NULL,
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
        "psi_warn_level": _NUM_OR_NULL,
        "detector": {"type": "string"},
        "threshold": _NUM_OR_NULL,
        "reference": {"type": "object"},
        "bins": {"type": "object"},
        "windows": {"type": "array", "items": {"type": "object"}},
        "summary": {"type": "object"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "if": {"properties": {"status": {"const": "ready"}}, "required": ["status"]},
    "then": {
        "required": [
            "detector", "psi_warn_level", "psi_alert_level", "reference", "bins", "summary",
            "notes",
        ],
        "properties": {
            "psi_alert_level": _NUM, "psi_warn_level": _NUM,
            "windows": {"type": "array", "items": _DRIFT_WINDOW},
        },
    },
}  # fmt: skip

_REPLAY_EVENT = {
    "type": "object",
    "required": [
        "ring_id", "rank", "first_ts", "detected_ts", "partial", "assembly_minutes",
        "assembly_events", "n_members", "n_transfers", "score",
    ],
    "properties": {
        "ring_id": {"type": "string", "pattern": RING_ID_PATTERN},
        "rank": {"type": "integer", "minimum": 1},
        "score": _NUM, "expected_value_inr": _NUM,
        "n_members": {"type": "integer", "minimum": 1},
        "n_transfers": {"type": "integer", "minimum": 1},
        "first_ts": {"type": "string"}, "detected_ts": {"type": "string"},
        "partial": {"type": "boolean"},
        "assembly_minutes": _NUM, "assembly_events": {"type": "integer", "minimum": 0},
        "truth_ring_id": {"type": ["integer", "null"]}, "truth_share": _NUM_OR_NULL,
        "truth_first_ts": {"type": ["string", "null"]},
        "latency_minutes": _NUM_OR_NULL, "latency_events": {"type": ["integer", "null"]},
    },
}  # fmt: skip

_TIMELINE = {
    "type": "object",
    "required": [
        "start_ts", "end_ts", "n_steps", "step_minutes", "events", "ring_transfers", "detected",
    ],
    "properties": {
        "start_ts": {"type": "string"}, "end_ts": {"type": "string"},
        "n_steps": {"type": "integer", "minimum": 1}, "step_minutes": _NUM,
        "events": {"type": "array", "items": {"type": "integer", "minimum": 0}},
        "ring_transfers": {"type": "array", "items": {"type": "integer", "minimum": 0}},
        "detected": {"type": "array", "items": {"type": "integer", "minimum": 0}},
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
        "detector": {"type": "string"},
        "threshold": _NUM_OR_NULL,
        "min_ring_members": {"type": "integer", "minimum": 1},
        "timeline": {"type": "object"},
        "events": {"type": "array", "items": {"type": "object"}},
        "summary": {"type": "object"},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "if": {"properties": {"status": {"const": "ready"}}, "required": ["status"]},
    "then": {
        "required": ["detector", "min_ring_members", "timeline", "summary", "notes"],
        "properties": {
            "timeline": _TIMELINE, "events": {"type": "array", "items": _REPLAY_EVENT},
        },
    },
}  # fmt: skip

SCHEMAS = {
    "meta.json": META, "queue.json": QUEUE, "cases.json": CASES,
    "metrics.json": METRICS, "drift.json": DRIFT, "replay.json": REPLAY,
}  # fmt: skip
