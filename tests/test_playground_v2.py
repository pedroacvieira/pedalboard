"""Pedal Playground v2 (schema 3 documents): parsing, writing, the fetch command (no network: a fake `get`)."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import design  # noqa: E402
import fetch_playground as fp  # noqa: E402

IN = 25.4


def doc(*items, name="Board"):
    return {"schemaVersion": 3, "savedAt": "2026-10-29T13:47:00.917Z", "name": name, "view": {"x": 1, "y": 2, "zoom": 3},
            "signal": {"nodes": [], "cables": []}, "items": list(items)}


def item(iid, x, y, w=2.0, h=4.0, rot=0, image="a.png", kind="pedal", label="Brand A"):
    return {"id": iid, "kind": kind, "label": label, "image": image, "width": w, "height": h, "x": x, "y": y,
            "rotation": rot, "flipX": False, "custom": False, "color": None}


# --- parsing ---------------------------------------------------------------------------------------
def test_a_v3_item_parses_to_mm_like_a_legacy_one():
    (it,) = design.parse_doc(doc(item("p1", 1.0, 2.0, w=2.0, h=4.0, rot=270)))
    assert it["title"] == "Brand A" and it["kind"] == "pedal" and it["rot"] == 270 and it["image"] == "a.png"
    assert (it["left_mm"], it["top_mm"], it["w_mm"], it["h_mm"]) == pytest.approx((IN, 2 * IN, 2 * IN, 4 * IN))
    assert design.footprint(it) == pytest.approx((IN + IN - 2 * IN, 2 * IN + 2 * IN - IN, IN + IN + 2 * IN, 2 * IN + 2 * IN + IN))
    legacy = design.parse_canvas('<div id="p1" class="item pedal rotate-270" title="Brand A" data-width="2" data-height="4" '
                                 'data-scale="45" style="left: 45px; top: 90px;"><div class="artwork" '
                                 'style="background-image: url(&quot;public/images/pedals/a.png&quot;);"></div></div>')[0]
    for k in ("left_mm", "top_mm", "w_mm", "h_mm", "rot", "image", "title", "kind"):
        assert it[k] == pytest.approx(legacy[k]) if isinstance(it[k], float) else it[k] == legacy[k]


def test_parse_doc_adds_png_drops_sizeless_items_and_maps_kinds():
    items = design.parse_doc(doc(item("b", 0, 0, w=24, h=13.06, kind="pedalboard", image="fender-pro-medium.png"),
                                 item("p", 1, 1, image="ehx-pico-pitch-fork"), item("z", 1, 1, w=0)))
    assert [i["id"] for i in items] == ["b", "p"]
    assert items[0]["kind"] == "pedalboard" and items[1]["image"] == "ehx-pico-pitch-fork.png"


def test_parse_design_reads_both_formats_and_rejects_others(tmp_path):
    v3 = tmp_path / "v3.json"
    v3.write_text(json.dumps(doc(item("p", 1, 1))))
    assert [i["id"] for i in design.parse_design(v3)] == ["p"]
    v1 = tmp_path / "v1.json"
    v1.write_text(json.dumps({"canvas": '<div id="q" class="item pedal" data-width="1" data-height="1" style="left: 0px; top: 0px;"></div>'}))
    assert [i["id"] for i in design.parse_design(v1)] == ["q"]
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(ValueError):
        design.parse_design(bad)


# --- writing (proposals) -----------------------------------------------------------------------------
def test_write_doc_moves_and_rotates_only_the_given_items():
    d = doc(item("p1", 1.0, 2.0), item("p2", 5.0, 5.0))
    items = design.parse_doc(d)
    moved = design.move(items[0], 100.0, 120.0, 90, snap=False)
    out = design.write_doc(d, [moved], name="Board - proposal 1")
    a, b = out["items"]
    assert a["x"] * IN == pytest.approx(100.0 - IN) and a["y"] * IN == pytest.approx(120.0 - 2 * IN) and a["rotation"] == 90
    assert b == d["items"][1] and out["view"] == d["view"] and out["name"] == "Board - proposal 1"
    assert d["items"][0]["x"] == 1.0                                         # the input is not changed
    again = design.parse_doc(out)[0]
    assert design.centre(again) == pytest.approx((100.0, 120.0)) and again["rot"] == 90
    with pytest.raises(KeyError):
        design.write_doc(d, [{**moved, "id": "nope"}])


def test_write_design_keeps_legacy_saves_legacy():
    data = {"canvas": '<div id="q" class="item pedal" data-width="1" data-height="1" data-scale="45" style="left: 0px; top: 0px;"></div>'}
    it = design.parse_data(data)[0]
    out = design.write_design(data, [design.move(it, 50.0, 50.0)])
    assert "canvas" in out and design.parse_data(out)[0]["left_mm"] > 30


# --- fetch ---------------------------------------------------------------------------------------------
def test_slug_of_accepts_links_and_slugs():
    assert fp.slug_of("https://pedalplayground.com/?p=cf30yjde") == "cf30yjde" == fp.slug_of(" cf30yjde ")
    for bad in ("https://pedalplayground.com/", "x", "../etc"):
        with pytest.raises(ValueError):
            fp.slug_of(bad)


KEY = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYW5vbiJ9.c2lnbmF0dXJlLXRoYXQtaXMtbG9uZw"


def fake_site(document, rows=True):
    calls = []

    def get(url, headers=None):
        calls.append((url, headers))
        if url == fp.SITE + "/":
            return '<script src="/assets/main-1.js"></script><link href="/assets/specs-2.js">'
        if url.endswith("main-1.js"):
            return "no key here"
        if url.endswith("specs-2.js"):
            return f'createClient("https://x.supabase.co","{KEY}")'
        assert headers == {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
        if "/playgrounds?" in url:
            assert "slug=eq.cf30yjde" in url and "is_public=eq.true" in url
            return json.dumps([{"id": "pg1", "name": "Gig Board", "updated_at": "t"}] if rows else [])
        if "/playground_versions?" in url:
            assert "playground_id=eq.pg1" in url and "order=created_at.desc" in url and "limit=1" in url
            return json.dumps([{"created_at": "t", "document": document}])
        raise AssertionError(url)
    return get, calls


def test_fetch_finds_the_key_in_any_script_and_reads_the_latest_version():
    d = doc(item("p", 1, 1))
    get, calls = fake_site(d)
    pg, got = fp.fetch_document("cf30yjde", get)
    assert pg["name"] == "Gig Board" and got == d
    assert not [c for c in calls if c[1] and "supabase" not in c[0] and "/rest/v1/" not in c[0]]


def test_fetch_reports_a_missing_share_and_an_unknown_format():
    get, _ = fake_site(doc(), rows=False)
    with pytest.raises(RuntimeError, match="no public playground"):
        fp.fetch_document("cf30yjde", get)
    get, _ = fake_site({"schemaVersion": 4, "items": []})
    with pytest.raises(RuntimeError, match="schemaVersion"):
        fp.fetch_document("cf30yjde", get)
    with pytest.raises(RuntimeError, match="public key"):
        fp.site_key(lambda url, headers=None: "<html></html>")


def test_save_moves_a_different_design_into_the_history(tmp_path):
    pdir = tmp_path / "proj"
    pdir.mkdir()
    first = doc(item("p", 1, 1), name="Gig Board")
    assert fp.save(pdir, first) == "new"
    assert fp.save(pdir, first) == "unchanged" and not (pdir / fp.HISTORY_DIR).exists()
    second = doc(item("p", 2, 1), name="Gig Board")
    assert fp.save(pdir, second, dry_run=True) == "replaced" and json.loads((pdir / fp.DESIGN_FILE).read_text()) == first
    assert fp.save(pdir, second) == "replaced"
    assert json.loads((pdir / fp.DESIGN_FILE).read_text()) == second
    (old,) = (pdir / fp.HISTORY_DIR).iterdir()
    assert old.name == "2026-10-29T134700_gig-board.json" and json.loads(old.read_text()) == first


def test_a_legacy_design_goes_to_the_history_under_its_file_time(tmp_path):
    pdir = tmp_path / "proj"
    pdir.mkdir()
    legacy = pdir / fp.DESIGN_FILE
    legacy.write_text(json.dumps({"canvas": ""}))
    t = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1))
    os.utime(legacy, (t, t))
    fp.save(pdir, doc(item("p", 1, 1)))
    (old,) = (pdir / fp.HISTORY_DIR).iterdir()
    assert old.name.startswith("2026-10-01T") and old.name.endswith("_design.json")


def test_changes_lists_added_removed_moved_and_rotated_pedals():
    a = design.parse_doc(doc(item("1", 1, 1, image="x.png", label="X"), item("2", 3, 3, image="y.png", label="Y")))
    b = design.parse_doc(doc(item("1", 2, 1, image="x.png", label="X", rot=90), item("3", 5, 5, image="z.png", label="Z")))
    lines = fp.changes(a, b)
    assert "  + Z" in lines and "  - Y" in lines and "  ~ X: moved 25 mm, rotated 0 -> 90" in lines


# --- share links in project.json -----------------------------------------------------------------------
def test_set_share_edits_only_the_playground_object(tmp_path):
    pdir = tmp_path / "proj"
    pdir.mkdir()
    text = '{\n  "name": "X",\n  "playground": { "scale": 45 },\n  "rules": []\n}\n'
    (pdir / "project.json").write_text(text)
    assert fp.set_share(pdir, fp.share_url("abc12345"))
    out = (pdir / "project.json").read_text()
    assert out == text.replace('{ "scale": 45 }', '{ "scale": 45, "share": "https://pedalplayground.com/?p=abc12345" }')
    (pdir / "project.json").write_text('{"name": "X"}\n')
    assert not fp.set_share(pdir, fp.share_url("abc12345")) and (pdir / "project.json").read_text() == '{"name": "X"}\n'


def test_new_project_stores_a_valid_share_link(tmp_path, monkeypatch):
    import new_project
    monkeypatch.setattr(new_project, "PROJECTS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["new", "b1", "--instrument", "bass", "--share", "abc12345"])
    new_project.main()
    proj = json.loads((tmp_path / "b1" / "project.json").read_text())
    assert proj["playground"] == {"scale": 45, "share": "https://pedalplayground.com/?p=abc12345"}
    assert fp.set_share(tmp_path / "b1", fp.share_url("zzz99999"))                 # the scaffold's multi-line object is found too
    assert json.loads((tmp_path / "b1" / "project.json").read_text())["playground"]["share"].endswith("zzz99999")
    monkeypatch.setattr(sys, "argv", ["new", "b2", "--instrument", "bass", "--share", "https://example.com/"])
    with pytest.raises(SystemExit):
        new_project.main()
    assert not (tmp_path / "b2").exists()


def test_pb_lists_the_commands_and_rejects_unknown_ones(capsys):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import pb
    assert pb.main(["--help"]) == 0 and "fetch" in capsys.readouterr().out
    assert pb.main(["nope"]) == 2
    assert set(pb.COMMANDS.values()) <= {p.stem for p in pb.SCRIPTS.glob("*.py")}
