"""Layout search (scripts/layout.py search), proposals (scripts/propose_layout.py) and their README section.
Synthetic boards with tiny iteration budgets; one opt-in full run on guitar-gig (PEDALBOARD_SLOW=1)."""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import common  # noqa: E402
import design  # noqa: E402
import layout  # noqa: E402
import propose_layout as pl  # noqa: E402
from common import load_catalog  # noqa: E402
from test_layout import at, model, ped, sw  # noqa: E402

GIG = ROOT / "projects" / "guitar-gig"
QUIET = {"layout": {"weights": {"io": 0, "flow": 0, "access": 0}}}   # isolate the terms a test looks at


def blocked(m, state):
    return m.score(state, margin=0, detail=True)[1]["blocked"]


def test_fix_separates_a_blocked_plug_pair_and_moves_little():
    m = model([ped("T A", 0), ped("T B", 100)], project_extra=QUIET)   # gap 5.6 mm: both plug heads blocked
    assert blocked(m, m.owner)
    res = layout.search(m, "fix", seed=1, iterations=300, restarts=1)
    best = res[0][1]
    assert best != m.owner and blocked(m, best) == [] and m.feasible(best)
    moved = pl.moved_list(m, best)
    assert len(moved) <= 2 and all(mv["distance_mm"] <= 40.5 for mv in moved) and all(mv["rot_to"] == 0 for mv in moved)


def test_pins_are_respected():
    m = model([ped("T A", 0), ped("T B", 100)], project_extra={"layout": {"pins": ["a"], **QUIET["layout"]}})
    for _, st in layout.search(m, "fix", seed=3, iterations=200, restarts=2):
        assert st[0] == m.owner[0]
    assert blocked(m, layout.search(m, "fix", seed=3, iterations=200, restarts=2)[0][1]) == []


def test_results_are_feasible_and_snapped_over_20_seeds():
    m = model([ped("T A", 0), ped("T B", 100), ped("T C", 300, 0)], chain=("a", "b", "c"))
    for seed in range(20):
        for _, st in layout.search(m, "rearrange", seed=seed, iterations=60, restarts=1):
            assert m.feasible(st)                                    # TOL_MM, as the build
            for it in m.items_for(st, snap=False):                   # whole px already
                assert abs(it["left_px"] - round(it["left_px"])) < 1e-6 and abs(it["top_px"] - round(it["top_px"])) < 1e-6


def test_search_is_deterministic():
    m = model([ped("T A", 0), ped("T B", 100)])
    a = layout.search(m, "rearrange", seed=7, iterations=150, restarts=2)
    b = layout.search(m, "rearrange", seed=7, iterations=150, restarts=2)
    assert a == b


def test_footswitch_pair_is_pushed_apart():
    extra = {"footswitches": {"min_distance_mm": 100}, **QUIET}
    m = model([ped("T A", 0), ped("T B", 160)], fs={"a": [sw()], "b": [sw()]}, project_extra=extra)  # 90.3 mm apart
    assert m.score(m.owner, detail=True)[1]["fs_close"]
    best = layout.search(m, "fix", seed=1, iterations=300, restarts=1)[0][1]
    assert m.score(best, detail=True)[1]["fs_close"] == []


def test_rearrange_fixes_a_wrong_order_with_a_swap():
    """Chain a -> b -> c with left-to-right jacks, laid out a, c, b: swapping b and c shortens the cables."""
    extra = {"layout": {"weights": {"io": 0, "flow": 0, "access": 0, "move": 0, "move_pedal": 0}}}
    m = model([ped("T A", 0), ped("T C", 150), ped("T B", 300)], chain=("a", "b", "c"), project_extra=extra)
    owner_sig = m.score(m.owner, detail=True)[1]["terms"]["signal"][0]
    best = layout.search(m, "rearrange", seed=1, iterations=600, restarts=2)[0][1]
    assert m.score(best, detail=True)[1]["terms"]["signal"][0] < owner_sig - 100
    assert best[1][0] < best[2][0]                                   # b now left of c


def test_gating():
    owner = {"errors": 0, "blocked": 3, "blocked_mm": 24.7, "unroutable": 0, "squeezed": 0, "overflow": 0, "fs_close": 1, "score": 4000}
    better = {**owner, "blocked": 0, "blocked_mm": 0.0, "score": 4100}
    assert pl.acceptable(better, owner)
    assert not pl.acceptable({**better, "squeezed": 1}, owner)          # worse routing
    assert not pl.acceptable({**better, "fs_close": 2}, owner)          # more footswitch pairs too close
    assert not pl.acceptable({**better, "errors": 1}, owner)
    assert not pl.acceptable(dict(owner), owner)                        # not better at all
    assert pl.acceptable({**owner, "score": 3990}, owner)               # same tiers, lower score


def gig_copy(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    shutil.copytree(GIG, root / "guitar-gig", ignore=shutil.ignore_patterns("proposals"))
    monkeypatch.setattr(common, "PROJECTS", root)
    return root / "guitar-gig"


def test_propose_writes_loadable_proposals_and_the_readme_section(tmp_path, monkeypatch, capsys):
    pdir = gig_copy(tmp_path, monkeypatch)
    design_before = (pdir / "playground_design.json").read_bytes()
    assert pl.main(["guitar-gig", "--iterations", "400", "--restarts", "2", "--top", "2"]) == 0
    assert (pdir / "playground_design.json").read_bytes() == design_before   # never written
    meta = json.loads((pdir / "proposals" / "meta.json").read_text())
    assert meta["command"].endswith("--iterations 400 --restarts 2 --top 2") and 1 <= len(meta["proposals"]) <= 2
    owner_items = {i["id"]: i for i in design.parse_design(pdir / "playground_design.json")}
    for p in meta["proposals"]:
        items = design.parse_design(pdir / "proposals" / p["file"])
        changed = {i["id"] for i in items if (i["left_px"], i["top_px"], i["rot"]) !=
                   (owner_items[i["id"]]["left_px"], owner_items[i["id"]]["top_px"], owner_items[i["id"]]["rot"])}
        assert len(changed) == len(p["moved"])                       # only the moved pedals differ
        assert (pdir / "proposals" / p["svg"]).read_text().startswith("<svg")
        assert p["metrics"]["blocked"] <= meta["owner"]["blocked"] and p["metrics"]["errors"] == 0
        assert sorted(x for s in p["power"]["supplies"] for o in s["outputs"] for x in o["pedals"]) == sorted(meta["chain"])


def test_no_better_layout_writes_no_proposal(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch)
    project = json.loads((pdir / "project.json").read_text())
    project["layout"] = {"pins": list(project["signal_chain"])}         # nothing may move
    (pdir / "project.json").write_text(json.dumps(project))
    assert pl.main(["guitar-gig", "--iterations", "50", "--restarts", "1"]) == 0
    meta = json.loads((pdir / "proposals" / "meta.json").read_text())
    assert meta["proposals"] == [] and not list((pdir / "proposals").glob("1.*"))


def test_score_prints_the_breakdown(capsys):
    assert pl.main(["guitar-gig", "--score"]) == 0
    out = capsys.readouterr().out
    assert "Blocked plugs (no margin, as the build): 3" in out and "footswitch" in out and "clearance" in out


# --- README section (build.proposals_section) ------------------------------------------------------
def test_readme_section_lists_proposals_and_detects_stale_ones(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch)
    pedals, supplies = load_catalog()
    ctx = build.validate(pdir, pedals, supplies)
    assert "None yet" in "\n".join(build.proposals_section(ctx, pedals))
    assert pl.main(["guitar-gig", "--iterations", "300", "--restarts", "1"]) == 0
    md = "\n".join(build.proposals_section(ctx, pedals))
    assert "## Layout proposals" in md and "| Blocked plugs | 3 (24.7 mm) |" in md and "Stale" not in md
    assert "![Proposal 1](proposals/1.svg)" in md and "Daisy chain" in md and "--iterations 300 --restarts 1" in md
    design_path = pdir / "playground_design.json"
    doc = json.loads(design_path.read_text())
    design_path.write_text(json.dumps({**doc, "canvas": doc["canvas"] + " "}))   # the owner saved a new layout
    assert "**Stale:**" in "\n".join(build.proposals_section(ctx, pedals))


def test_readme_section_without_a_better_layout(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch)
    meta = {"command": "x", "max_change": "fix", "max_move_mm": 40, "seed": 1, "iterations": 1, "restarts": 1,
            "runtime_s": 0.1, "design_sha1": pl.design_sha1(pdir), "finalists": 2, "owner": {}, "proposals": [],
            "chain": json.loads((pdir / "project.json").read_text())["signal_chain"]}
    (pdir / "proposals").mkdir()
    (pdir / "proposals" / "meta.json").write_text(json.dumps(meta))
    pedals, supplies = load_catalog()
    md = "\n".join(build.proposals_section(build.validate(pdir, pedals, supplies), pedals))
    assert "No better layout found (2 finalist(s)" in md and "Stale" not in md


@pytest.mark.skipif(not os.environ.get("PEDALBOARD_SLOW"), reason="full search on guitar-gig (~10 s): PEDALBOARD_SLOW=1")
def test_gig_fix_level_removes_todays_findings(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch)
    assert pl.main(["guitar-gig"]) == 0
    meta = json.loads((pdir / "proposals" / "meta.json").read_text())
    best = meta["proposals"][0]
    assert best["metrics"]["blocked"] == 0 and len(best["moved"]) <= 5
