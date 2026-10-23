"""Tests for install.py: target validation, no silent overwrite, symlink refusal."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import install  # noqa: E402


@pytest.fixture
def career_ops(tmp_path):
    t = tmp_path / "career-ops"
    (t / "modes" / "ko").mkdir(parents=True)
    (t / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    return t


def test_rejects_non_career_ops_dir(tmp_path):
    assert install.main([str(tmp_path)]) == 2
    assert install.main([str(tmp_path / "missing")]) == 2


def test_dry_run_writes_nothing(career_ops):
    assert install.main([str(career_ops), "--dry-run"]) == 0
    assert not (career_ops / "scripts" / "kr_offer.py").exists()


def test_install_copies_all_pack_files(career_ops):
    assert install.main([str(career_ops)]) == 0
    for rel in install.pack_files():
        assert (career_ops / rel).is_file(), rel
    # Second run: everything identical, still success.
    assert install.main([str(career_ops)]) == 0


def test_existing_different_file_is_not_overwritten(career_ops):
    user_file = career_ops / "modes" / "ko" / "offer-prep.md"
    user_file.write_text("user's own version\n", encoding="utf-8")
    assert install.main([str(career_ops)]) == 1
    assert user_file.read_text(encoding="utf-8") == "user's own version\n"
    assert install.main([str(career_ops), "--force"]) == 0
    assert user_file.read_text(encoding="utf-8") != "user's own version\n"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_symlinked_destination_refused(career_ops, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (career_ops / "templates").symlink_to(outside, target_is_directory=True)
    assert install.main([str(career_ops)]) == 2
    assert not any(outside.iterdir())
