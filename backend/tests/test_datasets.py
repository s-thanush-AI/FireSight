import tarfile
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from firesight.datasets.archive import UnsafeArchiveError, safe_extract
from firesight.datasets.figlib import FiglibError, validate_official_url
from firesight.datasets.inspect import inspect_dataset
from firesight.datasets.manifest import SequenceManifest, load_manifest, write_manifest
from firesight.datasets.paths import PathSafetyError, resolve_under
from firesight.datasets.pyrosdis import group_frames_by_event, make_event_split, prepare_pyrosdis


def _img(path: Path, w=16, h=16):
    ok, enc = cv2.imencode(".png", np.zeros((h, w, 3), np.uint8))
    assert ok
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(enc.tobytes())


class TestPathSafety:
    def test_within_root_ok(self, tmp_path):
        (tmp_path / "sub").mkdir()
        p = resolve_under(tmp_path, "sub/file.png")
        assert p == (tmp_path / "sub/file.png").resolve()

    def test_absolute_rejected(self, tmp_path):
        with pytest.raises(PathSafetyError):
            resolve_under(tmp_path, "/etc/passwd")

    def test_traversal_rejected(self, tmp_path):
        with pytest.raises(PathSafetyError):
            resolve_under(tmp_path, "../outside.png")

    def test_nested_traversal_rejected(self, tmp_path):
        with pytest.raises(PathSafetyError):
            resolve_under(tmp_path, "a/../../outside.png")

    def test_symlink_escape_rejected(self, tmp_path):
        outside = tmp_path.parent / "outside_dir"
        outside.mkdir(exist_ok=True)
        link = tmp_path / "link"
        link.symlink_to(outside)
        with pytest.raises(PathSafetyError):
            resolve_under(tmp_path, "link/x.png")


class TestArchiveSafety:
    def test_zip_ok(self, tmp_path):
        src = tmp_path / "a.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("dir/file.txt", "hello")
            zf.writestr("top.txt", "hi")
        dest = tmp_path / "out"
        n = safe_extract(src, dest)
        assert n == 2
        assert (dest / "dir/file.txt").read_text() == "hello"

    def test_zip_traversal_rejected(self, tmp_path):
        src = tmp_path / "evil.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("../evil.txt", "boom")
        with pytest.raises(UnsafeArchiveError):
            safe_extract(src, tmp_path / "out")

    def test_tar_ok(self, tmp_path):
        src = tmp_path / "a.tar"
        with tarfile.open(src, "w") as tf:
            f = tmp_path / "x.txt"
            f.write_text("data")
            tf.add(f, arcname="x.txt")
        n = safe_extract(src, tmp_path / "out2")
        assert n == 1

    def test_tar_traversal_rejected(self, tmp_path):
        src = tmp_path / "evil.tar"
        with tarfile.open(src, "w") as tf:
            f = tmp_path / "y.txt"
            f.write_text("data")
            tf.add(f, arcname="../y.txt")
        with pytest.raises(UnsafeArchiveError):
            safe_extract(src, tmp_path / "out3")

    def test_tar_symlink_rejected(self, tmp_path):
        src = tmp_path / "link.tar"
        with tarfile.open(src, "w") as tf:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        with pytest.raises(UnsafeArchiveError):
            safe_extract(src, tmp_path / "out4")

    def test_unknown_format(self, tmp_path):
        p = tmp_path / "file.rar"
        p.write_bytes(b"x")
        with pytest.raises(UnsafeArchiveError):
            safe_extract(p, tmp_path / "out5")

    def test_missing_archive(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            safe_extract(tmp_path / "nope.zip", tmp_path / "out6")


class TestInspect:
    def test_basic_report(self, tmp_path):
        for i in range(4):
            _img(tmp_path / "seq1" / f"2024-07-12_15-30-{i:02d}_000000.png")
        _img(tmp_path / "seq2" / "plain_000.jpg")
        report = inspect_dataset(tmp_path, name="testset")
        assert report.image_count == 5
        assert report.name == "testset"
        assert len(report.sequences) == 2
        assert report.annotation_format is None
        assert any("No YOLO labels" in i for i in report.issues)

    def test_missing_dir(self, tmp_path):
        report = inspect_dataset(tmp_path / "nope")
        assert report.image_count == 0
        assert report.issues

    def test_yolo_labels_detected(self, tmp_path):
        _img(tmp_path / "images" / "a.png")
        (tmp_path / "labels").mkdir()
        (tmp_path / "labels" / "a.txt").write_text("0 0.5 0.5 0.2 0.2")
        (tmp_path / "data.yaml").write_text("names:\n  0: smoke\n")
        report = inspect_dataset(tmp_path)
        assert report.annotation_format == "yolo_txt"
        assert report.classes == ["smoke"]
        assert report.yolo_config is not None

    def test_corrupt_image_reported(self, tmp_path):
        _img(tmp_path / "good.png")
        (tmp_path / "bad.png").write_bytes(b"garbage")
        report = inspect_dataset(tmp_path)
        assert any("Unreadable" in i or "Error reading" in i for i in report.issues)


class TestManifest:
    def test_round_trip(self, tmp_path):
        m = SequenceManifest(
            sequence_id="s1", name="S1", dataset="test", root_path="/x",
            frame_count=10, provenance="real", splits={"train": ["a.png"]},
        )
        path = write_manifest(m, tmp_path / "manifest.json")
        loaded = load_manifest(path)
        assert loaded.sequence_id == "s1"
        assert loaded.splits == {"train": ["a.png"]}
        assert loaded.provenance == "real"


class TestFiglibUrlValidation:
    def test_official_https_ok(self):
        url = "https://www.hpwren.ucsd.edu/FIgLib/archive.tar"
        assert validate_official_url(url) == url

    def test_http_rejected(self):
        with pytest.raises(FiglibError):
            validate_official_url("http://www.hpwren.ucsd.edu/x.tar")

    def test_wrong_host_rejected(self):
        with pytest.raises(FiglibError):
            validate_official_url("https://evil.example.com/x.tar")
        with pytest.raises(FiglibError):
            validate_official_url("https://hpwren.ucsd.edu.evil.com/x.tar")


class TestPyroSdisHelpers:
    def test_group_by_event(self):
        names = [
            "cam1_2023-05-21_12-00-00_000000.jpg",
            "cam1_2023-05-21_12-00-01_000000.jpg",
            "cam2_2023-06-01_09-15-00_000000.jpg",
        ]
        groups = group_frames_by_event(names)
        assert set(groups) == {"cam1", "cam2"}
        assert len(groups["cam1"]) == 2

    def test_event_split_no_leakage(self):
        names = []
        for event in range(10):
            for i in range(5):
                names.append(f"cam{event}_2023-05-{i+1:02d}_12-00-00_000000.jpg")
        splits = make_event_split(names, seed=7)
        all_files = splits["train"] + splits["val"] + splits["test"]
        assert sorted(all_files) == sorted(names)
        assert len(all_files) == len(set(all_files))
        # no event prefix shared across splits
        def prefixes(files):
            return {f.split("_2023")[0] for f in files}
        assert not (prefixes(splits["train"]) & prefixes(splits["val"]))
        assert not (prefixes(splits["train"]) & prefixes(splits["test"]))

    def test_split_fractions_validated(self):
        with pytest.raises(ValueError):
            make_event_split(["a_2023-05-01_x.jpg"], train=0.5, val=0.5, test=0.5)

    def test_prepare_requires_images(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            prepare_pyrosdis(tmp_path / "empty", tmp_path / "out")

    def test_prepare_writes_manifest(self, tmp_path):
        src = tmp_path / "ds"
        for event in range(4):
            for i in range(3):
                _img(src / "images" / f"cam{event}_2023-05-{i+1:02d}_12-00-00_000000.jpg")
        (src / "labels").mkdir(parents=True)
        manifest = prepare_pyrosdis(
            src, tmp_path / "out", revision="abc123", license_name="cc-by-4.0", seed=7
        )
        assert manifest.dataset_revision == "abc123"
        assert manifest.dataset_license == "cc-by-4.0"
        assert (tmp_path / "out" / "manifest.json").exists()
        total = sum(len(v) for v in manifest.splits.values())
        assert total == 12
