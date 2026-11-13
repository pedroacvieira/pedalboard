"""Per-pedal preference profiles of a project: `project.json` `pedals.<pedal id>` (all mm; pure: no files, no GUI).

One place for every per-pedal wish: board position (`position`: side across the board, depth front / back), `pin`,
`rotations`, ordering wishes (`order.<name>`, the old `rules` entries of that pedal), power wishes (`power`), `toppers`,
`note`. Every field is optional (a missing field = no wish). Schema and meaning: docs/plans/pedal-preferences.md
(section 3) and CLAUDE.md.

The OLD keys stay readable (`merge_legacy`): `rules` entries with "pedal", `layout.pins` (pedal ids), `layout.rotations.<id>`,
`layout.access.pedals.<id>`, `footswitches.toppers`. `lower(project)` is the core trick: it returns a copy whose OLD keys are
FILLED from the profiles, so every existing reader (the rule engine, `layout.settings`, `layout.Model`,
`footswitches.topper_settings`) stays untouched and a project builds the same whichever way it is written. A wish set
in both places is an error only when the values differ (`validate`). Supply instances are no pedals: their pins and
rotations stay in `layout.pins` / `layout.rotations`.
"""
import copy
import re

KEYS = ("position", "pin", "rotations", "order", "power", "toppers", "note")
SIDES = ("left", "right", "any")
DEPTHS = ("front", "back", "avoid_front", "any")
STRENGTHS = ("required", "preferred")
ROTATIONS = (0, 90, 270)
DEFAULT_WEIGHT = 0.3
DEFAULT_STRENGTH = "preferred"
NAME_RE = re.compile(r"^[a-z0-9_]+$")
RULE_TYPES = ("after", "before", "after_group", "before_group", "position", "no_buffered_before", "as_early_as_possible")
POSITION_KEYS = ("side", "depth", "weight", "strength")
POWER_KEYS = ("own_output", "supply", "port", "voltage_v", "strength")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _instance_ids(project):
    return {i.get("id") for i in (project.get("power") or {}).get("supplies", []) if isinstance(i, dict)}


def _order_key(chain, ids):
    """Pedals in chain order, then the others alphabetically."""
    rank = {p: i for i, p in enumerate(chain)}
    return sorted(ids, key=lambda p: (rank.get(p, len(chain)), p if p not in rank else ""))


def _rule_norm(r):
    return {"priority": 0, **r}


def _rule_name(r):
    """The `order` name of an old `rules` entry (its id is "<pedal>.<name>"), None when it has no such form (it stays a rule)."""
    if not isinstance(r, dict) or not isinstance(r.get("pedal"), str) or not isinstance(r.get("id"), str):
        return None
    pid, rid = r["pedal"], r["id"]
    name = rid[len(pid) + 1:] if rid.startswith(pid + ".") else None
    return name if name and NAME_RE.match(name) else None


def order_problems(body):
    """What is wrong with one `order.<name>` entry (a rule without id / pedal): [] when usable. Unknown rule types are
    NOT reported here (the build's rule loop does, with the derived rule id)."""
    if not isinstance(body, dict):
        return [f"must be an object, got {body!r}"]
    out = [f"must not have '{k}' (the rule id is <pedal>.<name>)" for k in ("id", "pedal") if k in body]
    kind = body.get("type")
    if not isinstance(kind, str):
        out.append("needs a 'type'")
    if body.get("strength") not in STRENGTHS:
        out.append(f"strength must be required or preferred, got {body.get('strength')!r}")
    if "priority" in body and not _num(body["priority"]):
        out.append(f"priority must be a number, got {body['priority']!r}")
    if kind in ("after", "before"):
        ps = body.get("pedals")
        if not isinstance(ps, list) or not all(isinstance(x, str) for x in ps):
            out.append(f"{kind} needs 'pedals' (a list of pedal ids)")
    elif kind in ("after_group", "before_group"):
        if not isinstance(body.get("group"), str):
            out.append(f"{kind} needs 'group' (a tag)")
    elif kind == "position" and body.get("value") not in ("first", "last"):
        out.append(f"position needs 'value' first or last, got {body.get('value')!r}")
    return out


# ---------------------------------------------------------------------------
# reading: the profiles merged with the old keys
# ---------------------------------------------------------------------------
def _legacy(project):
    """{pedal id: partial profile} read from the OLD keys (supply instances excluded: they are no pedals)."""
    out = {}
    inst = _instance_ids(project)
    lay = project.get("layout") or {}

    def mine(pid):
        return out.setdefault(pid, {})

    for r in project.get("rules") or []:
        name = _rule_name(r)
        if name:
            mine(r["pedal"]).setdefault("order", {})[name] = {k: v for k, v in r.items() if k not in ("id", "pedal")}
    pins = lay.get("pins")
    for pid in pins if isinstance(pins, list) else []:
        if isinstance(pid, str) and pid not in inst:
            mine(pid)["pin"] = True
    rots = lay.get("rotations")
    for pid, v in (rots.items() if isinstance(rots, dict) else []):
        if pid != "default" and pid not in inst:
            mine(pid)["rotations"] = v
    acc = (lay.get("access") or {}).get("pedals") if isinstance(lay.get("access"), dict) else None
    for pid, v in (acc.items() if isinstance(acc, dict) else []):
        if isinstance(v, dict):
            pos = mine(pid).setdefault("position", {})
            if "want" in v:
                pos["depth"] = v["want"]
            if "weight" in v:
                pos["weight"] = v["weight"]
    tops = (project.get("footswitches") or {}).get("toppers")
    for t in tops if isinstance(tops, list) else []:
        if isinstance(t, str) and "." in t:
            pid, sw = t.split(".", 1)
            mine(pid).setdefault("toppers", []).append(sw)
    return out


def _merge(pid, prof, old, conflicts):
    """`prof` (the raw profile) + `old` (the partial profile read from old keys) -> merged profile; values that differ are
    appended to `conflicts` as (pid, field path, old key, profile value, old value)."""
    out = copy.deepcopy(prof) if isinstance(prof, dict) else {}

    def put(node, path, key, value, old_key):
        if key in node and node[key] != value:
            conflicts.append((pid, path, old_key, node[key], value))
        else:
            node[key] = value

    if isinstance(out.get("position", {}), dict):   # (a position that is no object is a schema error, `validate`)
        for k, v in (old.get("position") or {}).items():
            put(out.setdefault("position", {}), f"position.{k}", k, v, f"layout.access.pedals.{pid}")
    if "pin" in old:
        put(out, "pin", "pin", old["pin"], "layout.pins")
    if "rotations" in old:
        put(out, "rotations", "rotations", old["rotations"], f"layout.rotations.{pid}")
    if isinstance(out.get("order", {}), dict):
        for name, body in (old.get("order") or {}).items():
            out.setdefault("order", {}).setdefault(name, body)   # an id in both places that differs: the build's "duplicate rule id" (see `lower`)
    if old.get("toppers"):
        have = out.get("toppers") if isinstance(out.get("toppers"), list) else []
        out["toppers"] = have + [t for t in old["toppers"] if t not in have]
    return out


def _collect(project):
    """({pedal id: merged profile}, conflicts) of `project["pedals"]` and the old keys."""
    raw = project.get("pedals")
    raw = raw if isinstance(raw, dict) else {}
    leg = _legacy(project)
    conflicts = []
    out = {}
    for pid in list(raw) + [p for p in leg if p not in raw]:
        out[pid] = _merge(pid, raw.get(pid), leg.get(pid, {}), conflicts)
    return out, conflicts


def merge_legacy(project):
    """{pedal id: profile} with the old keys merged in (a wish in both places must agree; see `validate`)."""
    return _collect(project)[0]


def profiles(project):
    """{pedal id: profile}: `project["pedals"]` merged with the old keys, fields normalised (position: weight and strength
    defaults filled in when it has a side or a depth; rotations as given)."""
    out = merge_legacy(project)
    for prof in out.values():
        pos = prof.get("position")
        if isinstance(pos, dict) and (pos.get("side") is not None or pos.get("depth") is not None):
            pos.setdefault("weight", DEFAULT_WEIGHT)
            pos.setdefault("strength", DEFAULT_STRENGTH)
    return out


# ---------------------------------------------------------------------------
# lowering: fill the old keys from the profiles
# ---------------------------------------------------------------------------
def lower(project, fs_data=None):
    """A copy of `project` whose OLD keys are filled from `pedals` (a project without profiles is returned as is):
    `rules` (the old entries first in their order, then the profiles': pedals in chain order, then the others
    alphabetically, names in their dict order; an equal duplicate is dropped, a different one with the same id stays and
    the build reports the duplicate id), `layout.pins`, `layout.rotations.<id>`, `layout.access.pedals.<id>` (from
    `position.depth` + `weight`; depth `any` -> want "none"), `footswitches.toppers`. Only pedals of the signal chain get
    pins, rotations, depth and toppers (the others are dormant); order entries with problems (`order_problems`) are
    left out (`validate` reports them). `fs_data` (catalog footswitches, `footswitches.usable`, optional): a topper on a pedal without data or naming a
    switch the pedal's data lacks is left out (`validate` reports it). Idempotent."""
    if not isinstance(project.get("pedals"), dict) or not project["pedals"]:
        return project
    merged, _ = _collect(project)
    out = copy.deepcopy(project)
    chain = [p for p in project.get("signal_chain") or [] if isinstance(p, str)]
    ordered = _order_key(chain, merged)
    # rules
    rules = list(out.get("rules") or [])
    seen = {r["id"]: _rule_norm(r) for r in rules if isinstance(r, dict) and "id" in r}
    for pid in ordered:
        order = merged[pid].get("order")
        for name, body in (order.items() if isinstance(order, dict) else []):
            if not NAME_RE.match(str(name)) or order_problems(body):
                continue
            rule = {"id": f"{pid}.{name}", "pedal": pid, **body}
            if rule["id"] in seen and _rule_norm(seen[rule["id"]]) == _rule_norm(rule):
                continue
            rules.append(rule)
            seen.setdefault(rule["id"], rule)
    if rules or "rules" in out:
        out["rules"] = rules
    lay = out.setdefault("layout", {}) if isinstance(out.get("layout", {}), dict) else out["layout"]
    live = [p for p in ordered if p in chain]
    pins = list(lay.get("pins") or [])
    pins += [p for p in live if merged[p].get("pin") is True and p not in pins]
    if pins:
        lay["pins"] = pins
    for p in live:
        rot = merged[p].get("rotations")
        if rot is not None:
            lay.setdefault("rotations", {})[p] = rot
        pos = merged[p].get("position")
        if isinstance(pos, dict) and pos.get("depth") is not None:
            w = pos.get("weight", DEFAULT_WEIGHT)
            lay.setdefault("access", {}).setdefault("pedals", {})[p] = {"want": "none" if pos["depth"] == "any" else pos["depth"], "weight": w}
    tops = list((out.get("footswitches") or {}).get("toppers") or [])
    for p in live:
        data = None if fs_data is None else fs_data.get(p)   # None: no data given / the pedal has none yet
        known = {f.get("id") for f in data or []}
        mine = merged[p].get("toppers")
        for sw in (mine if isinstance(mine, list) else []):
            key = f"{p}.{sw}"
            if key not in tops and (fs_data is None or (data is not None and sw in known)):
                tops.append(key)
    if tops:
        out.setdefault("footswitches", {})["toppers"] = tops
    if not lay:
        del out["layout"]
    return out


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def validate(project, cat_pedals, cat_supplies, fs_data, chain):
    """(errors, warnings, notes) of `project["pedals"]` (the schema, references and old-key conflicts, docs/plans/pedal-preferences.md
    section 7). notes: ["dormant: <id>", ...] for profiles of catalog pedals that are not in the signal chain."""
    errors, warnings, notes = [], [], []
    raw = project.get("pedals")
    if raw is None:
        return errors, warnings, notes
    if not isinstance(raw, dict):
        return [f"pedals must be an object {{pedal id: profile}}, got {raw!r}"], warnings, notes
    insts = {i["id"]: i for i in (project.get("power") or {}).get("supplies", []) if isinstance(i, dict) and "id" in i}
    for pid, prof in raw.items():
        at = f"pedals.{pid}"
        if pid not in cat_pedals:
            errors.append(f"pedals: '{pid}' is not in catalog/pedals.json")
            continue
        if pid not in chain:
            notes.append(f"dormant: {pid}")
        if not isinstance(prof, dict):
            errors.append(f"{at} must be an object, got {prof!r}")
            continue
        for k in prof:
            if k not in KEYS:
                errors.append(f"{at}: unknown key '{k}' (known: {', '.join(KEYS)})")
        _position(at, prof.get("position"), errors)
        if "pin" in prof and not isinstance(prof["pin"], bool):
            errors.append(f"{at}.pin must be true or false, got {prof['pin']!r}")
        _rotations(at, prof, errors, warnings)
        _order(at, pid, prof.get("order"), errors)
        _power(at, cat_pedals[pid], prof.get("power"), insts, cat_supplies, errors)
        _toppers(at, pid, prof.get("toppers"), fs_data, errors, warnings)
        if "note" in prof and not isinstance(prof["note"], str):
            errors.append(f"{at}.note must be a string, got {prof['note']!r}")
    for pid, field, old_key, mine, old in _collect(project)[1]:
        errors.append(f"pedals.{pid}.{field} and {old_key} disagree: {mine!r} vs {old!r}")
    return errors, warnings, notes


def _position(at, pos, errors):
    if pos is None:
        return
    if not isinstance(pos, dict):
        errors.append(f"{at}.position must be an object, got {pos!r}")
        return
    for k in pos:
        if k not in POSITION_KEYS:
            errors.append(f"{at}.position: unknown key '{k}' (known: {', '.join(POSITION_KEYS)})")
    for k, allowed in (("side", SIDES), ("depth", DEPTHS), ("strength", STRENGTHS)):
        if pos.get(k) is not None and pos[k] not in allowed:
            errors.append(f"{at}.position.{k} must be {_or(allowed)}, got {pos[k]!r}")
    if pos.get("weight") is not None and (not _num(pos["weight"]) or pos["weight"] < 0):
        errors.append(f"{at}.position.weight must be a number >= 0, got {pos['weight']!r}")


def _or(items):
    return ", ".join(items[:-1]) + f" or {items[-1]}"


def _rotations(at, prof, errors, warnings):
    if "rotations" not in prof:
        return
    rot = prof["rotations"]
    ok = rot in ("any", "current") if not isinstance(rot, list) else True
    if isinstance(rot, list):
        for r in rot:
            if _num(r) and r == 180:
                errors.append(f"{at}.rotations: 180 is never allowed")
            elif isinstance(r, bool) or not _num(r) or r not in ROTATIONS:
                ok = False
    if not ok:
        errors.append(f"{at}.rotations must be a list of 0, 90, 270, or \"any\" / \"current\", got {rot!r}")
    elif prof.get("pin") is True:
        warnings.append(f"{at}: pinned, so its rotations wish has no effect")


def _order(at, pid, order, errors):
    if order is None:
        return
    if not isinstance(order, dict):
        errors.append(f"{at}.order must be an object {{name: rule}}, got {order!r}")
        return
    for name, body in order.items():
        if not NAME_RE.match(str(name)):
            errors.append(f"{at}.order: '{name}' is not a valid name ([a-z0-9_]+)")
            continue
        errors += [f"rules: {pid}.{name}: {p}" for p in order_problems(body)]


def _power(at, ped, power, insts, cat_supplies, errors):
    if power is None:
        return
    if not isinstance(power, dict):
        errors.append(f"{at}.power must be an object, got {power!r}")
        return
    for k in power:
        if k not in POWER_KEYS:
            errors.append(f"{at}.power: unknown key '{k}' (known: {', '.join(POWER_KEYS)})")
    if "own_output" in power and not isinstance(power["own_output"], bool):
        errors.append(f"{at}.power.own_output must be true or false, got {power['own_output']!r}")
    if power.get("strength") is not None and power["strength"] not in STRENGTHS:
        errors.append(f"{at}.power.strength must be {_or(STRENGTHS)}, got {power['strength']!r}")
    sup, port, v = power.get("supply"), power.get("port"), power.get("voltage_v")
    inst = None
    if sup is not None:
        if sup not in insts:
            errors.append(f"{at}.power.supply '{sup}' is not a supply instance of power.supplies ({', '.join(insts) or 'none'})")
        else:
            inst = insts[sup]
    if port is not None:
        if sup is None:
            errors.append(f"{at}.power.port '{port}' needs power.supply")
        elif inst is not None:
            ports = [o["port"] for o in (cat_supplies.get(inst.get("supply")) or {}).get("outputs") or []]
            if port not in ports:
                errors.append(f"{at}.power.port '{port}' is not a port of {inst.get('supply')} ({', '.join(ports)})")
    if v is not None:
        if not _num(v):
            errors.append(f"{at}.power.voltage_v must be a number, got {v!r}")
            return
        pc = ped.get("power_consumption") or {}
        lo, hi = pc.get("min_voltage_v"), pc.get("max_voltage_v")
        if lo is not None and hi is not None and not lo <= v <= hi:
            errors.append(f"{at}.power.voltage_v {v:g} is outside the pedal's range {lo:g}-{hi:g} V")
            return
        pool = [inst] if inst is not None else ([] if sup is not None else list(insts.values()))
        outs = []
        for i in pool:
            outs += [o for o in (cat_supplies.get(i.get("supply")) or {}).get("outputs") or [] if port is None or o["port"] == port]
        if (pool or sup is None) and not any(op.get("voltage_v") == v for o in outs for op in o.get("options", [])):
            errors.append(f"{at}.power.voltage_v: no output of the project's supplies offers {v:g} V")


def _toppers(at, pid, tops, fs_data, errors, warnings):
    if tops is None:
        return
    if not isinstance(tops, list) or not all(isinstance(t, str) for t in tops):
        errors.append(f"{at}.toppers must be a list of switch ids, got {tops!r}")
        return
    data = (fs_data or {}).get(pid)
    if data is None:
        if tops:
            warnings.append(f"{at}.toppers: ignored, the footswitch data of {pid} is missing")
        return
    ids = [f.get("id") for f in data]
    for t in tops:
        if t not in ids:
            errors.append(f"{at}.toppers: '{t}' is not a footswitch of {pid} ({', '.join(map(str, ids))})")


# ---------------------------------------------------------------------------
# migration (the one-off script scripts/migrate_preferences.py, and the tests)
# ---------------------------------------------------------------------------
def migrate(project):
    """A copy of `project` with the OLD keys moved into `pedals.<id>` (profiles merged with what `pedals` already holds):
    `rules` entries of the form "<pedal>.<name>" (the others stay), `layout.pins` / `layout.rotations.<id>` /
    `layout.access.pedals` of pedals (supply instances stay), `footswitches.toppers` ("<pedal>.<switch>"). Profile fields in
    the order of `KEYS`, pedals in chain order then alphabetically; empty containers left behind are removed (`rules` stays a
    list). `lower(migrate(p))` has the same wishes as `lower(p)`; the rule list is only ordered per pedal."""
    merged, _ = _collect(project)
    out = copy.deepcopy(project)
    inst = _instance_ids(project)
    chain = [p for p in project.get("signal_chain") or [] if isinstance(p, str)]
    pedals = {}
    for pid in _order_key(chain, merged):
        prof = merged[pid]
        ordered = {k: prof[k] for k in KEYS if k in prof}
        ordered.update({k: v for k, v in prof.items() if k not in ordered})
        if ordered:
            pedals[pid] = ordered
    if pedals:
        if "pedals" in out:
            out["pedals"] = pedals
        else:   # right after `rules`, where the wishes came from
            keys = list(out)
            at = keys.index("rules") + 1 if "rules" in out else len(keys)
            out = {**{k: out[k] for k in keys[:at]}, "pedals": pedals, **{k: out[k] for k in keys[at:]}}
    if isinstance(out.get("rules"), list):
        out["rules"] = [r for r in out["rules"] if not _rule_name(r)]
    lay = out.get("layout")
    if isinstance(lay, dict):
        if isinstance(lay.get("pins"), list):
            kept = [p for p in lay["pins"] if not (isinstance(p, str) and p not in inst)]
            if kept or not lay["pins"]:
                lay["pins"] = kept
            else:
                del lay["pins"]   # (an empty list the owner wrote stays)
        if isinstance(lay.get("rotations"), dict):
            kept = {k: v for k, v in lay["rotations"].items() if k == "default" or k in inst}
            if kept or not lay["rotations"]:
                lay["rotations"] = kept
            else:
                del lay["rotations"]
        acc = lay.get("access")
        if isinstance(acc, dict) and isinstance(acc.get("pedals"), dict):
            kept = {k: v for k, v in acc["pedals"].items() if not isinstance(v, dict)}
            if kept or not acc["pedals"]:
                acc["pedals"] = kept
            else:
                del acc["pedals"]
                if not acc:
                    del lay["access"]
        if not lay:
            del out["layout"]
    fs = out.get("footswitches")
    if isinstance(fs, dict) and isinstance(fs.get("toppers"), list):
        kept = [t for t in fs["toppers"] if not (isinstance(t, str) and "." in t)]
        if kept or not fs["toppers"]:
            fs["toppers"] = kept
        else:
            del fs["toppers"]
            if not fs:
                del out["footswitches"]
    return out
