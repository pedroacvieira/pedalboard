#!/usr/bin/env python3
"""Fetch the owner's layout from Pedal Playground (v2 site) into projects/<name>/playground_design.json.

    uv run scripts/fetch_playground.py <project>                 the share link in project.json (`playground.share`)
    uv run scripts/fetch_playground.py <project> --share URL     a share link (https://pedalplayground.com/?p=<slug>, or the slug);
                                                                 saved in project.json when the project has none yet
    uv run scripts/fetch_playground.py <project> --dry-run       fetch and compare, write nothing

The share link must be public (Share in Pedal Playground). Read-only: the latest saved version of the playground is
read from the site's own database (Supabase REST, with the public key the site ships in its scripts). The document is
the site's schema 3 JSON (`design.parse_design` reads it). An existing playground_design.json that differs is moved to
projects/<name>/playground_history/ (git-ignored: every version the owner iterated over) before the new one is written.
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import design
from common import ROOT, load_json, project_dirs

SITE = "https://pedalplayground.com"
SUPABASE = "https://ookpbdtmqbkapzcnzstv.supabase.co/rest/v1"
DESIGN_FILE = "playground_design.json"
HISTORY_DIR = "playground_history"
KEY_RE = re.compile(r"eyJhbGciOi[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def slug_of(share):
    """'https://pedalplayground.com/?p=cf30yjde' or 'cf30yjde' -> 'cf30yjde'; ValueError otherwise."""
    share = (share or "").strip()
    if "://" in share:
        share = (urllib.parse.parse_qs(urllib.parse.urlparse(share).query).get("p") or [""])[0]
    if not re.fullmatch(r"[a-z0-9]{4,32}", share):
        raise ValueError(f"not a Pedal Playground share link or slug: {share!r}")
    return share


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "pedalboard-planner", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001  (callers only need the message)
        raise RuntimeError(f"Could not download {url}: {e}") from e


def site_key(get=_get):
    """The site's public (anon) Supabase key, from the scripts its home page loads (their names change per release)."""
    for js in sorted(set(re.findall(r"/assets/[A-Za-z0-9_.-]+\.js", get(SITE + "/")))):
        m = KEY_RE.search(get(SITE + js))
        if m:
            return m.group(0)
    raise RuntimeError("could not find the site's public key in its scripts (did Pedal Playground change its backend?)")


def fetch_document(slug, get=_get):
    """(playground row {id, name, updated_at}, the latest saved document) of a public share link."""
    key = site_key(get)
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows = json.loads(get(f"{SUPABASE}/playgrounds?select=id,name,updated_at&slug=eq.{slug}&is_public=eq.true", h))
    if not rows:
        raise RuntimeError(f"no public playground with the share link {slug} (is it still shared?)")
    pg = rows[0]
    vers = json.loads(get(f"{SUPABASE}/playground_versions?select=created_at,document"
                          f"&playground_id=eq.{pg['id']}&order=created_at.desc&limit=1", h))
    if not vers or not isinstance(vers[0].get("document"), dict):
        raise RuntimeError(f"the playground {pg['name']!r} has no saved version")
    doc = vers[0]["document"]
    if doc.get("schemaVersion") != 3 or not isinstance(doc.get("items"), list):
        raise RuntimeError(f"unexpected document format (schemaVersion {doc.get('schemaVersion')!r}): update design.parse_doc")
    return pg, doc


def share_url(slug):
    """The canonical share link of a slug."""
    return f"{SITE}/?p={slug}"


PLAYGROUND_RE = re.compile(r'"playground"\s*:\s*\{[^{}]*\}')


def set_share(pdir, url):
    """Store `url` as `playground.share` in pdir/project.json, editing only the "playground" object (the file's hand
    formatting is kept). Returns False when the file has no "playground" object (nothing written)."""
    path = pdir / "project.json"
    text = path.read_text()
    m = PLAYGROUND_RE.search(text)
    if not m:
        return False
    obj = json.loads(m.group(0).split(":", 1)[1])
    obj["share"] = url
    new = '"playground": { ' + ", ".join(f"{json.dumps(k)}: {json.dumps(v)}" for k, v in obj.items()) + " }"
    path.write_text(text[:m.start()] + new + text[m.end():])
    return True


def history_name(path, doc):
    """File name for an old design in the history: its save time (`savedAt`, else the file's mtime) + its name."""
    stamp = None
    if isinstance(doc, dict) and doc.get("savedAt"):
        try:
            stamp = datetime.fromisoformat(doc["savedAt"].replace("Z", "+00:00"))
        except ValueError:
            stamp = None
    if stamp is None:
        stamp = datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc)
    name = re.sub(r"[^A-Za-z0-9]+", "-", (doc.get("name") if isinstance(doc, dict) else None) or "design").strip("-").lower()
    return f"{stamp.strftime('%Y-%m-%dT%H%M%S')}_{name or 'design'}.json"


def changes(old_items, new_items):
    """Lines: pedals added / removed / moved / rotated between two parsed layouts (matched by image, in order)."""
    def key(items):
        out = {}
        for it in items:
            n = sum(1 for k in out if k[0] == it.get("image"))
            out[(it.get("image"), n)] = it
        return out
    old, new = key(old_items), key(new_items)
    lines = [f"  + {new[k]['title']}" for k in new if k not in old]
    lines += [f"  - {old[k]['title']}" for k in old if k not in new]
    for k in new:
        if k in old:
            a, b = old[k], new[k]
            d = ((b["left_mm"] - a["left_mm"]) ** 2 + (b["top_mm"] - a["top_mm"]) ** 2) ** 0.5
            if d > 0.5 or a["rot"] != b["rot"]:
                lines.append(f"  ~ {b['title']}: moved {d:.0f} mm" + (f", rotated {a['rot']} -> {b['rot']}" if a["rot"] != b["rot"] else ""))
    return lines


def save(pdir, doc, dry_run=False):
    """Write `doc` as pdir/playground_design.json, moving a different existing one into pdir/playground_history/.
    Returns "unchanged" | "new" | "replaced"."""
    path = pdir / DESIGN_FILE
    old_doc = None
    if path.exists():
        old_doc = json.loads(path.read_text())
        if old_doc == doc:
            return "unchanged"
    if dry_run:
        return "replaced" if old_doc is not None else "new"
    if old_doc is not None:
        hist = pdir / HISTORY_DIR
        hist.mkdir(exist_ok=True)
        target = hist / history_name(path, old_doc)
        if target.exists():
            target = target.with_name(target.stem + f"-{datetime.now().strftime('%H%M%S%f')}.json")
        path.replace(target)
        print(f"  previous version -> {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return "replaced" if old_doc is not None else "new"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--share", help="share link or slug (default: project.json playground.share)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and compare, write nothing")
    args = ap.parse_args(argv)
    pdir = project_dirs([args.project])[0]
    stored = (load_json(pdir / "project.json").get("playground") or {}).get("share")
    share = args.share or stored
    if not share:
        sys.exit(f"{pdir.name}: no share link: pass --share <link> (it is then saved in project.json)")
    try:
        slug = slug_of(share)
        pg, doc = fetch_document(slug)
    except (RuntimeError, ValueError) as e:
        sys.exit(f"{pdir.name}: {e}")
    if args.share and not args.dry_run:
        if not stored:
            ok = set_share(pdir, share_url(slug))
            print(f"  share link saved in project.json: {share_url(slug)}" if ok else
                  f"  note: add \"playground\": {{\"share\": \"{share_url(slug)}\"}} to project.json to keep the link")
        elif slug_of(stored) != slug:
            print(f"  note: project.json keeps its share link {stored} (this run used {share_url(slug)})")
    items = design.parse_doc(doc)
    print(f"{pdir.name}: {pg['name']!r}, saved {doc.get('savedAt') or pg.get('updated_at')}, {len(items)} items")
    path = pdir / DESIGN_FILE
    if path.exists():
        lines = changes(design.parse_design(path), items)
        print("\n".join(lines) if lines else "  no pedal moved, added or removed")
    result = save(pdir, doc, args.dry_run)
    print(f"  {DESIGN_FILE}: {result}{' (dry run: nothing written)' if args.dry_run and result != 'unchanged' else ''}")
    if result != "unchanged" and not args.dry_run:
        print(f"  next: uv run scripts/build.py {pdir.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
