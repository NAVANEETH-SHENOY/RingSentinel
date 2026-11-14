"""Stage 05: the demo bundle and the frontend sync script, checked against the real loader."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "frontend" / "public" / "demo-snapshots"


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo_script = _load_script("make_demo_bundle")
sync_script = _load_script("sync_frontend_snapshots")

from ringsentinel.snapshots.bundle import SnapshotError, load_bundle  # noqa: E402


def test_committed_demo_bundle_passes_the_real_loader():
    bundle = load_bundle(DEMO)
    assert bundle.meta["dataset_variant"] == "DEMO-SYNTHETIC"
    assert bundle.meta["evaluation_frozen"] is False
    assert bundle.meta["n_rings_exported"] == len(bundle.queue["items"]) >= 10


def test_committed_demo_bundle_equals_a_fresh_build():
    assert demo_script.main(["--check", "--out", str(DEMO)]) == 0


def test_demo_build_is_deterministic(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    assert demo_script.main(["--out", str(first)]) == 0
    assert demo_script.main(["--out", str(second)]) == 0
    for name in sorted(p.name for p in first.iterdir()):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_demo_has_a_ring_larger_than_the_display_cap():
    cases = load_bundle(DEMO).cases["cases"]
    nodes = {
        a
        for c in cases.values()
        for e in c["edges"]
        for a in (e["src"], e["dst"])
        if c["oversized"]
    }
    assert len(nodes) > 500


def test_demo_is_marked_as_demo_everywhere_it_matters():
    bundle = load_bundle(DEMO)
    assert "DEMO" in bundle.queue["note"]
    assert bundle.metrics["meta"]["dataset_variant"] == "DEMO-SYNTHETIC"
    assert "DEMO" in bundle.metrics["results_table_md"]
    assert bundle.queue["score_calibrated"] is False


def test_check_flags_a_stale_demo_bundle(tmp_path):
    copy = tmp_path / "demo"
    shutil.copytree(DEMO, copy)
    (copy / "queue.json").write_text("{}", encoding="utf-8")
    assert demo_script.main(["--check", "--out", str(copy)]) == 1


def test_sync_copies_a_valid_bundle(tmp_path):
    dst = tmp_path / "out"
    meta = sync_script.sync(DEMO, dst)
    assert sorted(p.name for p in dst.iterdir()) == sorted(p.name for p in DEMO.iterdir())
    assert meta["bundle_id"] == load_bundle(dst).bundle_id


def test_sync_refuses_a_tampered_bundle_and_copies_nothing(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(DEMO, src)
    doc = json.loads((src / "queue.json").read_text(encoding="utf-8"))
    doc["items"][0]["score"] = 0.123
    (src / "queue.json").write_text(json.dumps(doc), encoding="utf-8")
    dst = tmp_path / "dst"
    with pytest.raises(SnapshotError):
        sync_script.sync(src, dst)
    assert not dst.exists()
    assert sync_script.main(["--src", str(src), "--dst", str(dst)]) == 1


def test_sync_main_reports_success(tmp_path, capsys):
    assert sync_script.main(["--src", str(DEMO), "--dst", str(tmp_path / "x")]) == 0
    assert "bundle_id" in capsys.readouterr().out
