# Handover: fix the Pedal Playground downloads (`fix/image-download`)

## Goal
Pedal Playground moved its data and images. Make `scripts/common.py` download them from the new place again, and
never cache an HTML page as an image or a database.

## Where you work
- Git worktree `/home/pvieira/projects/pedalboard-fix-image-download`, branch `fix/image-download` (already checked
  out). Work ONLY in this directory, never in `/home/pvieira/projects/pedalboard` (the owner works there).
- Its `.cache/` is a copy of the main checkout's cache (git-ignored): `pedals.json`, `pedalboards.json` (old database,
  legacy shape) and `images/*.png` (39 images). You may delete / refresh files in THIS copy to test downloads.
- Python 3.12 via uv: `uv sync` once, then `uv run ...`; never `pip install`. Tests: `uv run pytest tests -q`
  (~60 s, must stay green). New dependencies: not needed (Pillow already reads WebP).
- Do NOT commit; leave the changes in the working tree and report. The owner reviews first.

## What broke (checked 2026-10-29)
- `common.IMAGE_URLS` / `BOARD_IMAGE_URLS` (`https://pedalplayground.com/app/images/pedals/<name>.png`, `.../public/...`)
  and `common.SITE + "pedals.json"` (`https://pedalplayground.com/public/data/pedals.json`) all answer HTTP 200 with a
  2886-byte `text/html` page. `fetch_image` writes that page as `<name>.png`; `database()` would cache it as JSON.
- New source: `https://pedalplayground.com/catalog/catalog.json` (application/json, ~2.2 MB):
  `{"schema", "generatedAt", "pedals": [...], "pedalboards": [...], "assets": {"pedals": {...}, "pedalboards": {...}}}`.
  - `pedals[i]` = `{"brand", "name", "width", "height", "image": "1981-inventions-drv", "added"}` (image WITHOUT `.png`;
    pedalboards the same shape).
  - `assets.pedals["<image>"]` = `{"thumb": "thumb/<image>.<hash>.webp", "img": "img/<image>.<hash>.webp"}`, relative to
    `https://pedalplayground.com/catalog/` (the `img` is 350 px wide, same aspect as before). `assets.pedalboards` alike.
- The six newest pedals' images were fetched by hand that way and saved as PNG in `.cache/images/` (e.g.
  `boss-dd8.png`, 350 x 621 RGBA).

## Required behaviour
1. `fetch_image(image_name, refresh=False, kind="pedals"|"pedalboards")` keeps its signature and its cached file name
   `.cache/images/<image_name>` (`image_name` is the legacy name WITH `.png`, e.g. `analogman-sunface.png`; the
   catalog keys `catalog/outlines.json`, `catalog/boards.json` use these names, do not change them). Look the name
   (minus `.png`) up in catalog.json's `assets.<kind>`, download the `img` URL, convert to PNG with Pillow (keep
   RGBA / alpha, the outlines depend on alpha > 128) and write atomically (`.part` then `os.replace`, as today).
   An unknown name or a failed download raises `RuntimeError` with a clear message (callers rely on that:
   `pedal_editor.py` exits with it).
2. Reject non-image responses everywhere: check the bytes (PNG / WebP / JPEG magic or Pillow can open them) and/or the
   Content-Type; an HTML answer is an error, never written to the cache. The old URLs may stay as a fallback only if
   they still go through this check (your call; drop them if they are dead).
3. Cache catalog.json in `.cache/catalog.json` (download once; a refresh path for it, e.g. when an image name is
   missing from the cached copy, or a small `refresh` flag: keep it simple).
4. `database(name)` (`"pedals.json"` / `"pedalboards.json"`) keeps returning `{"Brand Name": entry}` with entries in
   the LEGACY shape `{"Brand", "Name", "Width", "Height", "Image": "<image>.png"}`; callers: `to_playground.py`,
   `jacks.py`, `outlines.py`, `boards.py`, `board_editor.py`, `pedal_editor.py`. If `.cache/<name>` exists (legacy
   file), keep using it unchanged (no data drift for the existing projects). If it does not exist, build the legacy
   shape from catalog.json (lowercase keys -> legacy keys, `image` + `.png`) and cache it under the same name. Validate
   that what is cached is a JSON list, never HTML.
5. Report (do not fix data): for every `playground_title` in `catalog/pedals.json`, and the boards used by
   `projects/*/project.json`, whether the old cached entry and the catalog.json entry agree (width, height, image). A
   difference would move outlines / layouts; the owner decides.

## Tests (`tests/`, no network: mock `urllib.request.urlopen`, use `tmp_path`, monkeypatch `common.CACHE` /
`common.IMAGE_DIR` or whatever the module uses)
- HTML response -> RuntimeError, nothing written to the image cache.
- WebP response -> cached file is a PNG with the same size and alpha.
- Name missing from the assets -> RuntimeError naming it.
- Cached image present and `refresh=False` -> no download.
- `database()` from catalog.json produces the legacy shape and keys; an existing legacy cache file is used as is; an
  HTML answer is rejected.

## Acceptance
- `uv run pytest tests -q` green; `uv run scripts/build.py` exits as before (same output as on main).
- Live check in the worktree: delete `.cache/images/analogman-sunface.png` (and one board image, e.g. the gig's
  `fender-pro-medium.png`), run `uv run python -c "import sys; sys.path.insert(0,'scripts'); import common;
  print(common.fetch_image('analogman-sunface.png'))"` (and `kind="pedalboards"`), and confirm a valid RGBA PNG; then
  `uv run scripts/outlines.py --image analogman-sunface.png` produces the same rects as `catalog/outlines.json` has
  today (or report the difference: the old image may have been a different resolution; do NOT write a changed
  outlines.json, revert it if the script wrote one).
- Update `CLAUDE.md` only where it describes the download / cache (one or two lines) and tick the item in
  `docs/TODO.md` section 5 ("Pedal Playground moved its images") with a one-line note.

## Do not touch
`catalog/*.json` data (except reporting), `projects/`, the routing / layout code, generated READMEs and SVGs.

## Report back
Files changed, the design of the fetch / database code in 3-5 lines, test results, the live check, the data
comparison from point 5, and anything left open.
