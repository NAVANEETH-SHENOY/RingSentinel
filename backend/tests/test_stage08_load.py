"""Stage 08: the Elliptic loader and its schema checks (synthetic files in the real layout)."""

import numpy as np
import pandas as pd
import pytest
from ringsentinel.elliptic import schema as sc
from ringsentinel.elliptic.load import assemble, load_elliptic, read_classes, read_features
from ringsentinel.elliptic.settings import load_elliptic_settings
from s08_world import make_settings


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ell")
    settings, facts = make_settings(tmp, per_step=30)
    return settings, facts, load_elliptic(settings)


def test_load_counts_and_labels(world):
    settings, facts, data = world
    assert data.n == facts["nodes"] == 49 * 30
    assert data.x.shape == (data.n, 165) and data.x.dtype == np.float32
    assert data.local.shape[1] == sc.N_LOCAL_FEATURES
    assert set(np.unique(data.y)) == {-1, 0, 1}
    assert data.report["illicit"] == int((data.y == 1).sum()) == facts["labelled_illicit"]
    assert data.report["edges_dropped_unknown_endpoint"] == 0
    assert data.report["edges_across_time_steps"] == 0


def test_nodes_sorted_by_step_then_id(world):
    _, _, data = world
    order = np.lexsort((data.tx_id, data.step))
    assert (order == np.arange(data.n)).all()
    assert data.step.min() == 1 and data.step.max() == 49


def test_edges_point_at_existing_rows(world):
    _, _, data = world
    assert data.edge_src.max() < data.n and data.edge_dst.max() < data.n
    assert data.edge_src.min() >= 0


def test_header_in_features_file_is_tolerated(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=10, header_in_features=True)
    assert load_elliptic(settings).n == 490


def test_cross_step_edges_are_counted(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=20, cross_step_edges=5)
    assert load_elliptic(settings).report["edges_across_time_steps"] == 5


def test_wrong_feature_width_is_rejected_before_reading(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=5)
    settings.features_path.write_text("1,1,0.5,0.5\n", encoding="utf-8")
    with pytest.raises(sc.EllipticSchemaError, match="167"):
        read_features(settings.features_path)


def test_missing_file_is_a_clear_error(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=5)
    settings.classes_path.unlink()
    with pytest.raises(FileNotFoundError, match="elliptic_txs_classes"):
        load_elliptic(settings)


def test_unknown_class_value_is_rejected(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=5)
    classes = read_classes(settings.classes_path)
    classes.loc[0, "class"] = "3"
    features = read_features(settings.features_path)
    edges = pd.DataFrame({"txId1": [1], "txId2": [2]})
    with pytest.raises(sc.EllipticSchemaError, match="class values"):
        assemble(features, classes, edges)


def test_transaction_without_class_row_is_rejected(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=5)
    classes = read_classes(settings.classes_path).iloc[1:]
    with pytest.raises(sc.EllipticSchemaError, match="no class row"):
        assemble(read_features(settings.features_path), classes,
                 pd.DataFrame({"txId1": [], "txId2": []}, dtype="int64"))  # fmt: skip


def test_duplicate_tx_id_is_rejected(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=5)
    features = read_features(settings.features_path)
    features.loc[1, 0] = features.loc[0, 0]
    with pytest.raises(sc.EllipticSchemaError, match="Duplicate"):
        assemble(features, read_classes(settings.classes_path),
                 pd.DataFrame({"txId1": [], "txId2": []}, dtype="int64"))  # fmt: skip


def test_dangling_edges_are_dropped_and_reported(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=5)
    with settings.edgelist_path.open("a", encoding="utf-8") as out:
        out.write("999999999,1000000\n")
    report = load_elliptic(settings).report
    assert report["edges_dropped_unknown_endpoint"] == 1


def test_time_step_outside_range_is_rejected(tmp_path):
    settings, _ = make_settings(tmp_path, per_step=5)
    features = read_features(settings.features_path)
    features.loc[0, 1] = 50
    with pytest.raises(sc.EllipticSchemaError, match="Time steps"):
        assemble(features, read_classes(settings.classes_path),
                 pd.DataFrame({"txId1": [], "txId2": []}, dtype="int64"))  # fmt: skip


def test_settings_defaults_and_validation(tmp_path, monkeypatch):
    for name in ("RS_ELLIPTIC_DIR", "RS_ELLIPTIC_TRAIN_LAST_STEP", "RS_ELLIPTIC_VAL_LAST_STEP",
                 "RS_ELLIPTIC_HUB_CAP", "RS_HUB_CAP"):  # fmt: skip
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RS_DATA_DIR", str(tmp_path))
    s = load_elliptic_settings(load_env_file=False)
    assert (s.train_last_step, s.val_last_step) == (29, 34)
    assert s.raw_dir == tmp_path / "raw" / "elliptic"
    assert s.metrics_path == tmp_path / "processed" / "elliptic" / "metrics.json"
    monkeypatch.setenv("RS_ELLIPTIC_TRAIN_LAST_STEP", "34")
    with pytest.raises(ValueError, match="non-empty"):
        load_elliptic_settings(load_env_file=False)
    monkeypatch.setenv("RS_ELLIPTIC_TRAIN_LAST_STEP", "10")
    monkeypatch.setenv("RS_ELLIPTIC_VAL_LAST_STEP", "20")
    monkeypatch.setenv("RS_ELLIPTIC_HUB_CAP", "1")
    with pytest.raises(ValueError, match="HUB_CAP"):
        load_elliptic_settings(load_env_file=False)

