"""Shared test helpers: the frozen copy of the guitar-gig project (tests/fixtures/guitar-gig).

Tests that depend on the gig's layout, wiring or proposals use it instead of the live projects/guitar-gig (the owner
changes that one all the time). The fixture directory is read-only by convention: a test that writes copies it first
(`gig_copy`)."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

GIG_FIXTURE = ROOT / "tests" / "fixtures" / "guitar-gig"


def gig_copy(tmp_path, monkeypatch, proposals=False):
    """Copy the frozen gig into <tmp_path>/projects/guitar-gig, point common.PROJECTS at <tmp_path>/projects (so project
    names resolve there, as in the CLIs) and return the copy. `proposals=True` keeps the fixture's proposals/ folder."""
    import common
    root = tmp_path / "projects"
    shutil.copytree(GIG_FIXTURE, root / "guitar-gig", ignore=None if proposals else shutil.ignore_patterns("proposals"))
    monkeypatch.setattr(common, "PROJECTS", root)
    return root / "guitar-gig"
