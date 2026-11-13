#!/usr/bin/env python3
"""Move a project's per-pedal wishes from the old keys into `pedals.<pedal id>` (one-off migration; --dry-run shows the diff).

    uv run pb migrate-preferences <project...> [--dry-run]

Moves the `rules` entries "<pedal>.<name>", `layout.pins` / `layout.rotations.<id>` / `layout.access.pedals` of pedals and
`footswitches.toppers` into the pedal's profile (supply instances stay in `layout`), and writes project.json in the repo's style
(`common.dump_project`). The old keys stay readable, so a project that is not migrated keeps working; a migrated one builds the
same (the rule list is only ordered per pedal). Proposals: project.json changes, so `proposals/meta.json` would be stale; when it
was fresh before and nothing the layout search reads changed, its `inputs_sha1` is stamped again (otherwise run the proposals again).
"""
import argparse
import difflib
import json
import re
import sys

import preferences
from common import dump_project, load_json, project_dirs, proposal_inputs_sha1

META = "meta.json"


def effective(project):
    """What the layout search and the build read from `project` (old keys filled from the profiles), normalised so that an
    order that does not matter is ignored: rules by id, pins / toppers sorted."""
    low = preferences.lower(project)
    out = {k: v for k, v in low.items() if k != "pedals"}
    out["rules"] = sorted(out.get("rules") or [], key=lambda r: r.get("id", ""))
    lay = dict(out.get("layout") or {})
    if "pins" in lay:
        lay["pins"] = sorted(lay["pins"])
    out["layout"] = lay
    fs = dict(out.get("footswitches") or {})
    if "toppers" in fs:
        fs["toppers"] = sorted(fs["toppers"])
    out["footswitches"] = fs
    return out


def same_wishes(old, new):
    """True when nothing the search reads differs between the old project and the migrated one."""
    return effective(old) == effective(new)


def migrate_dir(pdir, dry_run=False, out=print):
    """Migrate one project folder; returns True when project.json changes (or would)."""
    path = pdir / "project.json"
    text = path.read_text()
    old = load_json(path)
    catalog = _catalog()
    chain = [p for p in old.get("signal_chain", []) if isinstance(p, str)]
    errors = preferences.validate(old, *catalog, chain)[0]   # the profiles as written, and a wish that old keys and profiles state differently
    if errors:
        out(f"{pdir.name}: nothing migrated, fix these first:\n  " + "\n  ".join(errors))
        return False
    new = preferences.migrate(old)
    errors = preferences.validate(new, *catalog, chain)[0]
    if errors:
        out(f"{pdir.name}: the migrated project has errors, nothing written:\n  " + "\n  ".join(errors))
        return False
    body = dump_project(new)
    if json.loads(text) == new:   # already migrated (whatever its formatting)
        out(f"{pdir.name}: nothing to migrate")
        return False
    if not same_wishes(old, new):
        out(f"{pdir.name}: BUG: the migrated project reads differently, nothing written")
        return False
    n = len(new.get("pedals") or {})
    meta = pdir / "proposals" / META
    fresh = meta.exists() and (load_json(meta).get("inputs_sha1") == proposal_inputs_sha1(pdir))
    out(f"{pdir.name}: {len(old.get('rules') or []) - len(new.get('rules') or [])} rule(s), {n} profile(s) in pedals; proposals: "
        + ("fresh, stamped again after the write" if fresh else "none or stale already, left as they are"))
    if dry_run:
        out("".join(difflib.unified_diff(text.splitlines(True), body.splitlines(True), f"{pdir.name}/project.json", f"{pdir.name}/project.json (migrated)")))
        return True
    path.write_text(body)
    if fresh:
        mt = meta.read_text()
        meta.write_text(re.sub(r'("inputs_sha1": ")[0-9a-f]{40}(")', lambda m: m.group(1) + proposal_inputs_sha1(pdir) + m.group(2), mt, count=1))
    return True


def _catalog():
    from common import load_catalog
    import footswitches
    pedals, supplies = load_catalog()
    return pedals, supplies, footswitches.usable(footswitches.read_file()["footswitches"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projects", nargs="*", help="project names (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    args = ap.parse_args(argv)
    for pdir in project_dirs(args.projects or None):
        migrate_dir(pdir, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
