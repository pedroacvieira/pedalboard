"""The README table "Preferences" (build.preferences_section) and the proposal metrics / gate (propose_layout) for the profiles' wishes."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import common  # noqa: E402
import preferences as pref  # noqa: E402
import propose_layout as pl  # noqa: E402
from common import load_catalog, load_json  # noqa: E402
from conftest import gig_copy  # noqa: E402


def built(pdir, profiles, **extra):
    pedals, supplies = load_catalog()
    project = {**load_json(pdir / "project.json"), "pedals": profiles, **extra}
    ctx = build.validate(pdir, pedals, supplies, project=project, route=False)
    return pedals, ctx


def rightmost(pdir):
    pedals, supplies = load_catalog()
    ctx = build.validate(pdir, pedals, supplies, route=False)
    lay = ctx["layout"]
    return max(lay["placed"], key=lambda p: lay["placed"][p]["left_mm"] + lay["placed"][p]["w_mm"] / 2)


def table(md):
    return [line for line in md if line.startswith("|")]


# --- 12: the table -------------------------------------------------------------------------------------------------------------------
def test_table_lists_the_owners_column_and_the_dormant_pedals_and_the_old_keys(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch)
    right = rightmost(pdir)
    pedals, ctx = built(pdir, {right: {"position": {"side": "left", "strength": "required"}, "pin": True, "note": "n"}, "double_dragon": {"pin": True}})
    md = build.preferences_section(ctx, pedals)
    rows = table(md)
    assert rows[0] == "| Pedal | Wish | Strength | Owner's layout |" and rows[1] == "|---|---|---|---|"
    name = common.pedal_name(pedals[right])
    mine = [r for r in rows if r.startswith(f"| {name} |") and "position" in r]
    assert len(mine) == 1 and mine[0].startswith(f"| {name} | position side: left half | required | **not met** (") and mine[0].endswith(" mm past the middle) |")
    assert f"| {name} | pin: does not move in the search | - | applied |" in rows
    assert any(r.endswith("| required | met |") and "order:" in r for r in rows)                                    # the old rules are rows too
    assert "Dormant (pedals not in the signal chain): `double_dragon`." in md
    assert any(line.startswith("Old keys in use (`rules`)") and "migrate-preferences guitar-gig" in line for line in md)
    pedals, ctx = built(pdir, {})
    assert table(build.preferences_section(ctx, pedals))[0] == "| Pedal | Wish | Strength | Owner's layout |"       # the old rules alone
    ctx = build.validate(pdir, *load_catalog(), project={**load_json(pdir / "project.json"), "rules": []}, route=False)
    assert build.preferences_section(ctx, pedals)[-1] == "No preferences set (`pedals.<pedal id>` in project.json)."


def test_proposal_columns_follow_the_fresh_meta_and_say_unknown_for_older_proposals(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch, proposals=True)
    right = rightmost(pdir)
    profiles = {right: {"position": {"side": "left"}}}
    pedals, ctx = built(pdir, profiles)
    meta_path = pdir / "proposals" / "meta.json"
    meta = json.loads(meta_path.read_text())
    key = pref.row_key({"pedal": right, "kind": "position.side"})
    # stale (the fixture's hash does not match): no proposal columns
    meta["inputs_sha1"] = "0" * 40
    meta_path.write_text(json.dumps(meta))
    assert table(build.preferences_section(ctx, pedals))[0] == "| Pedal | Wish | Strength | Owner's layout |"
    # fresh, proposals made before the feature: `?` for the wishes the layout decides, the chain's order the same as the owner's
    project_file = pdir / "project.json"
    project_file.write_text(json.dumps({**load_json(project_file), "pedals": profiles}))
    meta["inputs_sha1"], meta["chain"] = common.proposal_inputs_sha1(pdir), ctx["chain"]
    n = len(meta["proposals"])
    assert n >= 2
    meta_path.write_text(json.dumps(meta))
    pedals, ctx = built(pdir, profiles)
    rows = table(build.preferences_section(ctx, pedals))
    assert rows[0] == "| Pedal | Wish | Strength | Owner's layout | " + " | ".join(f"Proposal {p['n']}" for p in meta["proposals"]) + " |"
    side = next(r for r in rows if "position side" in r)
    assert side.endswith("| " + " | ".join(["?"] * n) + " |") and side.count("**not met**") == 1
    order = next(r for r in rows if "order:" in r)
    assert order.endswith("| " + " | ".join(["met"] * (n + 1)) + " |")
    # with the figures of the feature: met / not met per proposal
    for i, p in enumerate(meta["proposals"]):
        p["metrics"]["preferences"] = {key: i == 0}
    meta_path.write_text(json.dumps(meta))
    pedals, ctx = built(pdir, profiles)
    side = next(r for r in table(build.preferences_section(ctx, pedals)) if "position side" in r)
    cells = [c.strip() for c in side.strip("|").split("|")][3:]
    assert cells[1:] == ["met"] + ["**not met**"] * (n - 1)
    # the table row on required wishes appears once the owner's figures carry it
    meta["owner"]["pref_required_unmet"] = 1
    meta_path.write_text(json.dumps(meta))
    md = "\n".join(build.proposals_section(ctx, pedals))
    assert "| Required preference wishes not met | 1 | " in md


# --- 13: the proposal gate and the metrics ----------------------------------------------------------------------------------------
def test_gate_rejects_more_unmet_required_wishes_than_the_owners_layout():
    owner = {"errors": 0, "blocked": 1, "blocked_mm": 3.0, "collisions": 0, "fs_close": 0, "score": 100.0, "unroutable": 0, "squeezed": 0,
             "overflow": 0, "pref_required_unmet": 1}
    better = {**owner, "score": 50.0}
    assert pl.acceptable(better, owner) and pl.acceptable({**better, "pref_required_unmet": 0}, owner)
    assert not pl.acceptable({**better, "pref_required_unmet": 2}, owner)
    assert pl.acceptable({k: v for k, v in better.items() if k != "pref_required_unmet"}, {k: v for k, v in owner.items() if k != "pref_required_unmet"})   # old meta
    # ranks after the footswitch pairs, before the score
    assert pl.rank_key({**better, "pref_required_unmet": 0}) < pl.rank_key({**better, "pref_required_unmet": 1})
    assert pl.rank_key({**better, "fs_close": 1, "pref_required_unmet": 0}) > pl.rank_key({**better, "pref_required_unmet": 3})
    assert pl.rank_key({**better, "pref_required_unmet": 1, "score": 99.0}) < pl.rank_key({**better, "pref_required_unmet": 2, "score": 1.0})


def test_propose_records_the_wishes_and_never_does_worse_than_the_owner(tmp_path, monkeypatch):
    pdir = gig_copy(tmp_path, monkeypatch)
    right = rightmost(pdir)
    project = load_json(pdir / "project.json")
    project["pedals"] = {right: {"position": {"side": "left", "strength": "required"}}, "monk": {"power": {"own_output": True, "strength": "required"}}}
    (pdir / "project.json").write_text(common.dump_project(project))
    assert pl.main(["guitar-gig", "--iterations", "120", "--restarts", "1", "--top", "2"]) == 0
    meta = json.loads((pdir / "proposals" / "meta.json").read_text())
    key = f"{right}.position.side"
    owner = meta["owner"]
    assert owner["preferences"][key] is False and owner["preferences"]["monk.power"] is True and owner["pref_required_unmet"] >= 1
    assert owner["terms"]["position"] > 100                                                              # the penalty of the miss
    for p in meta["proposals"]:
        assert key in p["metrics"]["preferences"] and p["metrics"]["pref_required_unmet"] <= owner["pref_required_unmet"]
    assert meta["inputs_sha1"] == common.proposal_inputs_sha1(pdir)
