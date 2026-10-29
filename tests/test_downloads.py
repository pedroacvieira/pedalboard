"""Pedal Playground downloads (common.catalog_json / database / fetch_image): no network, urlopen is mocked."""
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import common  # noqa: E402

HTML = b"<!doctype html><html><body>Pedal Playground</body></html>"
CATALOG = {
    "schema": 1, "generatedAt": "2026-10-29",
    "pedals": [{"brand": "Analogman", "name": "Sun Face", "width": 2.5, "height": 4.5, "image": "analogman-sunface", "added": "2020-01-01"}],
    "pedalboards": [{"brand": "Fender", "name": "Pro Medium", "width": 22.0, "height": 9.0, "image": "fender-pro-medium", "added": "2020-01-01"}],
    "assets": {"pedals": {"analogman-sunface": {"thumb": "thumb/a.1.webp", "img": "img/analogman-sunface.1.webp"}},
               "pedalboards": {"fender-pro-medium": {"thumb": "thumb/b.1.webp", "img": "img/fender-pro-medium.1.webp"}}},
}


class Resp:
    def __init__(self, data, ctype):
        self.data, self.headers = data, {"Content-Type": ctype}

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def webp(size=(8, 12)):
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    for x in range(2, 6):
        for y in range(3, 9):
            im.putpixel((x, y), (200, 10, 10, 255))
    buf = io.BytesIO()
    im.save(buf, "WEBP", lossless=True)
    return im, buf.getvalue()


@pytest.fixture
def net(tmp_path, monkeypatch):
    """Isolated cache + a fake urlopen serving `net.routes` {url: (bytes, content type)}; `net.calls` lists the URLs."""
    monkeypatch.setattr(common, "CACHE", tmp_path / ".cache")
    monkeypatch.setattr(common, "IMAGE_DIR", tmp_path / ".cache" / "images")

    class Net:
        routes = {common.CATALOG_URL: (json.dumps(CATALOG).encode(), "application/json")}
        calls = []

    def fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        Net.calls.append(url)
        if url not in Net.routes:
            return Resp(HTML, "text/html")
        return Resp(*Net.routes[url])

    monkeypatch.setattr(common.urllib.request, "urlopen", fake)
    return Net


def test_html_instead_of_image_is_rejected(net):
    net.routes[common.CATALOG_BASE + "img/analogman-sunface.1.webp"] = (HTML, "text/html")
    with pytest.raises(RuntimeError, match="not an image"):
        common.fetch_image("analogman-sunface.png")
    assert not list(common.IMAGE_DIR.glob("*"))


def test_html_with_image_content_type_is_rejected(net):
    net.routes[common.CATALOG_BASE + "img/analogman-sunface.1.webp"] = (HTML, "image/webp")
    with pytest.raises(RuntimeError, match="did not answer an image"):
        common.fetch_image("analogman-sunface.png")
    assert not list(common.IMAGE_DIR.glob("*"))


def test_webp_is_cached_as_png_with_alpha(net):
    im, data = webp()
    net.routes[common.CATALOG_BASE + "img/analogman-sunface.1.webp"] = (data, "image/webp")
    path = common.fetch_image("analogman-sunface.png")
    assert path == common.IMAGE_DIR / "analogman-sunface.png"
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    with Image.open(path) as out:
        assert out.mode == "RGBA" and out.size == im.size
        assert out.getpixel((0, 0))[3] == 0 and out.getpixel((3, 5)) == (200, 10, 10, 255)
    assert not list(common.IMAGE_DIR.glob("*.part"))


def test_board_image_uses_the_pedalboards_assets(net):
    _, data = webp((20, 10))
    net.routes[common.CATALOG_BASE + "img/fender-pro-medium.1.webp"] = (data, "image/webp")
    with Image.open(common.fetch_image("fender-pro-medium.png", kind="pedalboards")) as out:
        assert out.size == (20, 10)
    with pytest.raises(RuntimeError, match="analogman-sunface"):
        common.fetch_image("analogman-sunface.png", kind="pedalboards")


def test_unknown_name_names_it_and_refreshes_a_cached_catalog_once(net):
    common.catalog_json()  # cached now
    n = len(net.calls)
    with pytest.raises(RuntimeError, match="no-such-pedal"):
        common.fetch_image("no-such-pedal.png")
    assert net.calls.count(common.CATALOG_URL) == 2 and len(net.calls) == n + 1


def test_unknown_name_with_fresh_catalog_downloads_it_once(net):
    with pytest.raises(RuntimeError, match="no-such-pedal"):
        common.fetch_image("no-such-pedal.png")
    assert net.calls == [common.CATALOG_URL]


def test_cached_image_is_not_downloaded(net):
    common.IMAGE_DIR.mkdir(parents=True)
    (common.IMAGE_DIR / "analogman-sunface.png").write_bytes(b"cached")
    assert common.fetch_image("analogman-sunface.png").read_bytes() == b"cached"
    assert net.calls == []


def test_refresh_downloads_again(net):
    _, data = webp()
    net.routes[common.CATALOG_BASE + "img/analogman-sunface.1.webp"] = (data, "image/webp")
    common.IMAGE_DIR.mkdir(parents=True)
    (common.IMAGE_DIR / "analogman-sunface.png").write_bytes(b"old")
    common.fetch_image("analogman-sunface.png", refresh=True)
    assert common.IMAGE_DIR.joinpath("analogman-sunface.png").read_bytes()[:4] == b"\x89PNG"


def test_failed_download_is_a_runtime_error(net, monkeypatch):
    def boom(req, timeout=None):
        raise OSError("offline")
    monkeypatch.setattr(common.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="offline"):
        common.fetch_image("analogman-sunface.png")


def test_database_from_catalog_has_the_legacy_shape(net):
    db = common.database("pedals.json")
    assert db == {"Analogman Sun Face": {"Brand": "Analogman", "Name": "Sun Face", "Width": 2.5, "Height": 4.5,
                                         "Image": "analogman-sunface.png"}}
    assert list(common.database("pedalboards.json")) == ["Fender Pro Medium"]
    assert json.loads((common.CACHE / "pedals.json").read_text())[0]["Image"] == "analogman-sunface.png"
    assert net.calls == [common.CATALOG_URL]  # catalog.json cached, downloaded once for both


def test_existing_legacy_database_file_is_used_as_is(net):
    common.CACHE.mkdir()
    legacy = [{"Brand": "Old", "Name": "One", "Width": 1, "Height": 2, "Image": "old-one.png"}]
    (common.CACHE / "pedals.json").write_text(json.dumps(legacy))
    assert common.database("pedals.json") == {"Old One": legacy[0]}
    assert net.calls == []


def test_html_catalog_is_rejected_and_not_cached(net):
    net.routes[common.CATALOG_URL] = (HTML, "text/html")
    with pytest.raises(RuntimeError, match="not JSON"):
        common.database("pedals.json")
    assert not (common.CACHE / "pedals.json").exists() and not (common.CACHE / "catalog.json").exists()


def test_cached_html_database_is_ignored(net):
    common.CACHE.mkdir()
    (common.CACHE / "pedals.json").write_bytes(HTML)
    assert list(common.database("pedals.json")) == ["Analogman Sun Face"]
    assert json.loads((common.CACHE / "pedals.json").read_text())[0]["Brand"] == "Analogman"
