"""`pb`: one entry point for the repo's scripts (uv run pb <command> ...; uv run pb --help lists them).

Each command runs an existing script's main() with its own arguments (scripts/<name>.py keeps working as before); the
scripts import each other as top-level modules, so scripts/ goes on sys.path first.
"""
import ast
import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# command -> script module (scripts/<module>.py); order = the help listing
COMMANDS = {
    "build": "build",
    "fetch": "fetch_playground",
    "propose": "propose_layout",
    "new": "new_project",
    "pedal-editor": "pedal_editor",
    "board-editor": "board_editor",
    "outlines": "outlines",
    "boards": "boards",
}


def summary(module):
    """The first line of a script's docstring (read without importing it)."""
    doc = ast.get_docstring(ast.parse((SCRIPTS / f"{module}.py").read_text())) or ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def usage():
    width = max(len(c) for c in [*COMMANDS, "test"])
    lines = ["usage: uv run pb <command> [args...]   (uv run pb <command> --help: the command's options)", "", "commands:"]
    lines += [f"  {c:<{width}}  {summary(m)}" for c, m in COMMANDS.items()]
    lines.append(f"  {'test':<{width}}  Run the tests (pytest tests -q; extra args go to pytest).")
    return "\n".join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "test":
        return subprocess.call([sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q", *rest], cwd=ROOT)
    if cmd not in COMMANDS:
        print(f"pb: unknown command {cmd!r}\n\n{usage()}", file=sys.stderr)
        return 2
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    module = importlib.import_module(COMMANDS[cmd])
    sys.argv = [f"pb {cmd}", *rest]   # the scripts' argparse reads sys.argv (some main() take no argv)
    try:
        result = module.main()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) or e.code is None else (print(e.code, file=sys.stderr) or 1)
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
