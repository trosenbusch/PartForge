"""Write ``constraints.txt``: the exact versions of PartForge's dependencies in the tested ``.venv``.

    .venv\\Scripts\\python.exe scripts\\update_constraints.py

Start-PartForge.cmd (scripts/bootstrap.py) installs with ``pip install -e . -c constraints.txt``, so a source
installation gets the versions the tests ran with (and the program package bundles) instead of whatever is newest.
Run it after updating packages in ``.venv`` and passing the tests. Covers the dependencies of ``pyproject.toml``
including the extras ``test`` and ``build`` and everything they pull in (extras not installed here, such as
``postgres``, stay unpinned).
"""
from __future__ import annotations

import importlib.metadata as md
import re
import sys
import tomllib
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "constraints.txt"
EXTRAS = ("test", "build")
HEADER = """\
# Getestete Versionen der Python-Abhängigkeiten von PartForge (aus .venv erzeugt mit
# scripts/update_constraints.py – nicht von Hand ändern). Start-PartForge.cmd installiert mit
# "pip install -e . -c constraints.txt"; Python {python}.
"""


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def closure(requirements: list[str]) -> dict[str, str]:
    """``{normalised name: installed version}`` of the requirements and their dependencies (markers evaluated)."""
    environment = default_environment()
    pending = [(Requirement(r), "") for r in requirements]
    pinned: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    while pending:
        requirement, extra = pending.pop()
        if requirement.marker and not requirement.marker.evaluate({**environment, "extra": extra}):
            continue
        key = (_norm(requirement.name), ",".join(sorted(requirement.extras)))
        if key in seen:
            continue
        seen.add(key)
        try:
            dist = md.distribution(requirement.name)
        except md.PackageNotFoundError:
            continue  # optional dependency not installed in the tested environment
        pinned[_norm(dist.metadata["Name"])] = dist.version
        for sub in dist.requires or []:
            sub_req = Requirement(sub)
            for wanted in ("", *requirement.extras):
                pending.append((sub_req, wanted))
    return pinned


def main() -> int:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = list(project["dependencies"])
    for extra in EXTRAS:
        requirements += project.get("optional-dependencies", {}).get(extra, [])
    pinned = closure(requirements)
    pinned.pop("partforge", None)
    lines = [HEADER.format(python=".".join(map(str, sys.version_info[:3])))]
    lines += [f"{name}=={version}\n" for name, version in sorted(pinned.items())]
    OUT.write_text("".join(lines), encoding="utf-8", newline="\n")  # LF, as in the repository (.gitattributes)
    print(f"{OUT}: {len(pinned)} Pakete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
