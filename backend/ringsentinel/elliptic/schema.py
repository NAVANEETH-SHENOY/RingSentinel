"""Expected layout of the three Elliptic files, and the checks that fail loudly if it differs.

Every fact below is from the dataset paper and its public descriptions, NOT from inspecting the
real files in this build environment (they could not be downloaded here). Anything marked
VERIFY must be confirmed by the owner with `python scripts\\run_stage08.py verify`, which prints the
real header and shapes.
"""

from __future__ import annotations

FEATURES_FILE = "elliptic_txs_features.csv"
CLASSES_FILE = "elliptic_txs_classes.csv"
EDGELIST_FILE = "elliptic_txs_edgelist.csv"
RAW_FILES = (FEATURES_FILE, CLASSES_FILE, EDGELIST_FILE)

# VERIFY: features file has no header row; columns are txId, time step (1..49), then 165 features
# (93 local transaction features followed by 72 one-hop aggregates).
N_FEATURE_COLUMNS = 167
N_LOCAL_FEATURES = 93
N_AGGREGATE_FEATURES = 72
# VERIFY: classes file header is "txId,class"; class is "1" (illicit), "2" (licit) or "unknown".
CLASS_ILLICIT = "1"
CLASS_LICIT = "2"
CLASS_UNKNOWN = "unknown"
# VERIFY: edgelist header is "txId1,txId2" (a directed payment flow from txId1 to txId2).
EDGE_COLUMNS = ("txId1", "txId2")
CLASS_COLUMNS = ("txId", "class")

LABEL_UNKNOWN = -1  # internal label for an unlabelled transaction (never used to fit or score)


class EllipticSchemaError(ValueError):
    """The files do not look like the Elliptic data set; the message says what was found."""
