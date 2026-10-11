"""Build the Windows program package dist/PartForge (PyInstaller onedir, windowed) and test it.

    .venv\\Scripts\\python.exe scripts\\build.py                 # frontend + package + licences + smoke test
    .venv\\Scripts\\python.exe scripts\\build.py --no-frontend   # use the existing build in partforge\\web
    further options: --distpath/--workpath DIR, --no-smoke, --sign [--cert-sha1 SHA1], --rust-writer PATH

Steps: (1) frontend (``npm run build`` into partforge/web) unless ``--no-frontend``; (2) app icon; (3) version
resource from ``partforge.__version__``; (4) PyInstaller: hidden imports, all ``partforge`` submodules plus its data
files (no ``.py`` sources), development modules excluded; (5) package files: README.md (the package manual
``docs/handbuch/README.md``), LICENSE, THIRD_PARTY_NOTICES.md, CHANGELOG.md, Start-PartForge.cmd and the user manual
``docs/handbuch/BEDIENUNG.md`` rendered as ``Handbuch/Bedienung.html`` with its images (``Handbuch/bilder/``; links
between the two manuals point at the package files, every link is checked); (6) THIRD_PARTY_LICENSES.txt
(``scripts/third_party.py``); (7) optional code signing (signtool); (8) smoke test (``scripts/smoke_test.py``:
starts the exe isolated, creates a library with examples, checks layers/heights/logs) – every failed check fails
the build (exit code 1).

Needs the build extra (``pip install -e .[build]``: PyInstaller, python-markdown) and, for the smoke test's library
check, altium-designer-mcp.exe (GPL-3.0, NOT bundled – PartForge finds it via Einstellungen > Altium or its default
paths).
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
NAME = "PartForge"
PACKAGE_README = ROOT / "docs" / "handbuch" / "README.md"
PACKAGE_FILES = ("LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "CHANGELOG.de.md", "Start-PartForge.cmd")
#: the user manual (Markdown with images in ``bilder/``) – in the package ``Handbuch/Bedienung.html``
MANUAL_SOURCE = ROOT / "docs" / "handbuch" / "BEDIENUNG.md"
MANUAL_DIR = "Handbuch"
MANUAL_HTML = "Bedienung.html"
#: links between the two manuals: repository target -> package target (README.md of the package is the package
#: manual ``docs/handbuch/README.md``, ``Handbuch/Bedienung.html`` the rendered user manual)
PACKAGE_README_LINKS = {"BEDIENUNG.md": f"{MANUAL_DIR}/{MANUAL_HTML}"}
MANUAL_LINKS = {"README.md": "../README.md"}
COMPANY = "Tobias Rosenbusch"
DESCRIPTION = "PartForge – Altium-Datenbankbibliotheken"
TIMESTAMP_URL = "http://timestamp.digicert.com"

HIDDEN_IMPORTS = [
    # uvicorn picks these at runtime
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.protocols", "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl", "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on",
    # pywin32: pywintypes turns FILETIMEs (IStorage.EnumElements in partforge/altium/compound.py) into datetimes
    # through a C-level import of win32timezone that PyInstaller cannot see – without it every PcbLib layer/height
    # patch fails in the package
    "win32timezone", "win32crypt", "pythoncom", "pywintypes",
    "sqlalchemy.dialects.sqlite",
]
# partforge: every submodule (the routers are imported by name) plus the data files (web build, assets, bridge
# scripts, data) – without the .py sources, which --collect-all would copy next to the PYZ
COLLECT_SUBMODULES = ["partforge"]
COLLECT_DATA = ["partforge", "certifi", "webview"]
COPY_METADATA = ["anthropic", "fastapi", "pydantic", "sqlalchemy", "pypdfium2"]
# reached only through optional code paths (anyio's pytest plugin, httpx's CLI, cffi's compiler shim) or not
# used at all – development tools stay out of the package
EXCLUDE_MODULES = ["pytest", "_pytest", "pygments", "setuptools", "pdfminer", "pdfplumber"]


class BuildError(RuntimeError):
    """The build cannot continue (German message)."""


# --------------------------------------------------------------------------- version resource


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """``"1.2.3"`` / ``"1.2"`` / ``"1.0.0rc1"`` -> ``(1, 2, 3, 0)`` (release numbers only, four fields)."""
    match = re.match(r"^\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?", version)
    if not match:
        raise BuildError(f"Version {version!r} ist keine Versionsnummer (z. B. 1.0.0).")
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def legal_copyright(license_file: Path = ROOT / "LICENSE") -> str:
    """``© <Jahr> <Name>`` from the copyright line of LICENSE."""
    text = license_file.read_text(encoding="utf-8") if license_file.is_file() else ""
    match = re.search(r"Copyright \(c\)\s*(.+)", text, re.IGNORECASE)
    return f"© {match.group(1).strip()}" if match else f"© {COMPANY}"


def version_file_text(version: str, *, copyright: str | None = None) -> str:
    """PyInstaller version file (``--version-file``): file/product version, name, description, company, copyright."""
    from packaging.version import InvalidVersion, Version

    numbers = version_tuple(version)
    version = version.strip()
    try:
        parsed_version = Version(version)
    except InvalidVersion as exc:
        raise BuildError(f"Version {version!r} ist keine gültige Paketversion.") from exc
    # The fixed resource requires four integers. Its string table can retain the full beta/RC version,
    # which Explorer and the smoke test must not mistake for a final release.
    flags = 0x2 if parsed_version.is_prerelease else 0x0  # VS_FF_PRERELEASE
    strings = [
        ("CompanyName", COMPANY),
        ("FileDescription", DESCRIPTION),
        ("FileVersion", version),
        ("InternalName", NAME),
        ("LegalCopyright", copyright or legal_copyright()),
        ("OriginalFilename", f"{NAME}.exe"),
        ("ProductName", NAME),
        ("ProductVersion", version),
    ]
    table = ",\n".join(f"          StringStruct({key!r}, {value!r})" for key, value in strings)
    return (
        "# -*- coding: utf-8 -*-\n"
        "# Generated by scripts/build.py from partforge.__version__ – do not edit.\n"
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags={flags:#x}, OS=0x40004,\n"
        "                    fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('040704B0', [\n"
        f"{table}\n"
        "      ])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [0x0407, 1200])])\n"
        "  ]\n"
        ")\n"
    )


# --------------------------------------------------------------------------- PyInstaller


def pyinstaller_command(*, icon: Path, version_file: Path, distpath: Path, workpath: Path) -> list[str]:
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", NAME, "--icon", str(icon), "--version-file", str(version_file), "--paths", str(ROOT),
        "--distpath", str(distpath), "--workpath", str(workpath), "--specpath", str(workpath),
    ]
    for module in HIDDEN_IMPORTS:
        command += ["--hidden-import", module]
    for package in COLLECT_SUBMODULES:
        command += ["--collect-submodules", package]
    for package in COLLECT_DATA:
        command += ["--collect-data", package]
    for package in COPY_METADATA:
        command += ["--copy-metadata", package]
    for module in EXCLUDE_MODULES:
        command += ["--exclude-module", module]
    command.append(str(SCRIPTS / "frozen_entry.py"))
    return command


def build_env() -> dict[str, str]:
    """Environment of PyInstaller: ``partforge`` importable from ROOT in every (isolated) subprocess, whatever the
    working directory – otherwise collect_data_files skips it ("not a package") and the package has no UI."""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(ROOT), env.get("PYTHONPATH", "")) if p)
    return env


def check_build_environment(env: dict[str, str]) -> None:
    for module, name in (("PyInstaller", "PyInstaller"), ("markdown", "python-markdown")):
        if importlib.util.find_spec(module) is None:
            raise BuildError(
                f"{name} fehlt in dieser Python-Umgebung – bitte zuerst "
                "„.venv\\Scripts\\python.exe -m pip install -e .[build]“ ausführen."
            )
    probe = subprocess.run(
        [sys.executable, "-c", "import partforge; print(partforge.__file__)"],
        env=env, cwd=tempfile.gettempdir(), capture_output=True, text=True, check=False,
    )
    found = Path(probe.stdout.strip()).resolve() if probe.returncode == 0 and probe.stdout.strip() else None
    expected = (ROOT / "partforge" / "__init__.py").resolve()
    if found != expected:
        raise BuildError(
            f"partforge wird nicht aus {ROOT} importiert (gefunden: {found or probe.stderr.strip()[-300:]}). "
            "Bitte eine andere PartForge-Installation aus dieser Python-Umgebung entfernen."
        )


def build_frontend() -> None:
    npm = shutil.which("npm")
    if not npm:
        raise BuildError("npm wurde nicht gefunden – bitte Node.js installieren oder --no-frontend verwenden.")
    if not (FRONTEND / "node_modules").exists():
        subprocess.run([npm, "ci"], cwd=FRONTEND, check=True)
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def copy_package_files(target: Path, *, version: str = "") -> None:
    """README (the package manual – no repository links), LICENSE, notices, the start script and the user manual
    (``Handbuch/Bedienung.html`` with its images)."""
    if not PACKAGE_README.is_file():
        raise BuildError(f"{PACKAGE_README} fehlt – das Programmpaket braucht sein Handbuch.")
    (target / "README.md").write_text(package_readme_text(), encoding="utf-8", newline="\n")
    for name in PACKAGE_FILES:
        source = ROOT / name
        if not source.is_file():
            raise BuildError(f"{source} fehlt.")
        shutil.copy2(source, target / name)
    write_manual(target, version=version)


# --------------------------------------------------------------------------- user manual (HTML)

_MD_LINK = re.compile(r"(\]\()([^)\s#]+)(#[^)\s]*)?(\))")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_HTML_REF = re.compile(r'\b(?:href|src)="([^"]*)"')
_IMAGE_PARAGRAPH = re.compile(r"<p>(<img\b[^>]*>)</p>")


def rewrite_links(text: str, mapping: dict[str, str]) -> str:
    """Markdown link targets ``](a.md)`` / ``](a.md#x)`` -> ``](b)`` / ``](b#x)`` for every ``a.md`` in ``mapping``."""

    def replace(match: re.Match[str]) -> str:
        target = mapping.get(match.group(2))
        if target is None:
            return match.group(0)
        return f"{match.group(1)}{target}{match.group(3) or ''}{match.group(4)}"

    return _MD_LINK.sub(replace, text)


def package_readme_text() -> str:
    """README.md of the package: ``docs/handbuch/README.md`` with its link to the user manual pointing at
    ``Handbuch/Bedienung.html``."""
    return rewrite_links(PACKAGE_README.read_text(encoding="utf-8"), PACKAGE_README_LINKS)


def _png_size(path: Path) -> tuple[int, int] | None:
    head = path.read_bytes()[:24] if path.is_file() else b""
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _figure(match: re.Match[str], image_root: Path) -> str:
    """An image alone in its paragraph -> figure with the alt text as caption, linked to the full-size image."""
    tag = match.group(1)
    src = re.search(r'\bsrc="([^"]*)"', tag)
    alt = re.search(r'\balt="([^"]*)"', tag)
    if src is None:
        return match.group(0)
    caption = alt.group(1) if alt else ""
    size = _png_size(image_root / html.unescape(src.group(1)))
    dims = f' width="{size[0]}" height="{size[1]}"' if size else ""
    image = f'<img src="{src.group(1)}" alt="{caption}"{dims} loading="lazy">'
    caption_html = f"<figcaption>{caption}</figcaption>" if caption else ""
    return f'<figure><a href="{src.group(1)}">{image}</a>{caption_html}</figure>'


MANUAL_TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="generator" content="PartForge {version} – scripts/build.py">
<title>{title}</title>
<style>
:root {{
  --bg: #ffffff; --fg: #1c2230; --muted: #5d6677; --line: #e2e5eb; --soft: #f4f5f8; --code: #eef0f4;
  --link: #1f63d6; --accent: #e8590c; --shadow: 0 4px 18px rgba(16, 24, 40, 0.10);
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0f1218; --fg: #e5e8ee; --muted: #9aa2b1; --line: #262c37; --soft: #161a22; --code: #1b2029;
    --link: #74b1ff; --accent: #ff8a3d; --shadow: 0 4px 18px rgba(0, 0, 0, 0.45);
  }}
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{ margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.6 "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; }}
.top {{ position: sticky; top: 0; z-index: 1; background: var(--bg); border-bottom: 1px solid var(--line); }}
.top div {{ max-width: 1120px; margin: 0 auto; padding: 10px 24px; display: flex; gap: 16px; align-items: baseline;
  font-size: 14px; color: var(--muted); }}
.top b {{ color: var(--fg); }}
.top b span {{ color: var(--accent); }}
.top a {{ margin-left: auto; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 8px 24px 72px; }}
h1 {{ font-size: 2rem; line-height: 1.25; margin: 1.1em 0 0.5em; }}
h2 {{ font-size: 1.5rem; line-height: 1.3; margin: 2.4em 0 0.7em; padding-bottom: 0.3em;
  border-bottom: 1px solid var(--line); scroll-margin-top: 64px; }}
h3 {{ font-size: 1.15rem; margin: 1.8em 0 0.5em; scroll-margin-top: 64px; }}
p, li {{ max-width: 82ch; }}
li + li {{ margin-top: 0.25em; }}
a {{ color: var(--link); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
strong {{ font-weight: 600; }}
code {{ font-family: "Cascadia Mono", Consolas, "Courier New", monospace; font-size: 0.9em; background: var(--code);
  padding: 0.1em 0.35em; border-radius: 4px; }}
pre {{ background: var(--code); padding: 12px 16px; border-radius: 8px; overflow-x: auto; }}
pre code {{ padding: 0; background: none; }}
table {{ border-collapse: collapse; margin: 1em 0 1.4em; font-size: 0.95em; }}
th, td {{ border: 1px solid var(--line); padding: 6px 12px; text-align: left; vertical-align: top; }}
th {{ background: var(--soft); font-weight: 600; }}
hr {{ border: 0; border-top: 1px solid var(--line); margin: 2.4em 0; }}
figure {{ margin: 1.2em 0 1.8em; }}
figure img {{ display: block; max-width: 100%; height: auto; border: 1px solid var(--line); border-radius: 8px;
  box-shadow: var(--shadow); }}
figcaption {{ margin-top: 0.5em; font-size: 0.875rem; color: var(--muted); }}
footer {{ margin-top: 4em; padding-top: 1em; border-top: 1px solid var(--line); font-size: 0.875rem; color: var(--muted); }}
@media (max-width: 640px) {{ main, .top div {{ padding-left: 16px; padding-right: 16px; }} table {{ display: block;
  overflow-x: auto; }} }}
@media print {{ .top {{ display: none; }} figure img {{ box-shadow: none; }} a {{ color: inherit; }}
  figure {{ break-inside: avoid; }} }}
</style>
</head>
<body>
<header class="top"><div><b>Part<span>Forge</span> {version}</b><span>Bedienungsanleitung</span><a href="#inhalt">Inhalt</a></div></header>
<main>
{body}
<footer>PartForge {version} · Installation, Datenablage und Deinstallation: <a href="../README.md">README.md</a> im Programmordner</footer>
</main>
</body>
</html>
"""


def render_manual_html(text: str, *, version: str = "", image_root: Path | None = None) -> str:
    """The user manual (Markdown) as a standalone HTML page: German, light and dark, no external resources; the
    heading anchors are GitHub's (``#1-überblick``), so the table of contents of the Markdown file works."""
    try:
        import markdown
        from markdown.extensions.toc import slugify_unicode
    except ImportError as exc:  # pragma: no cover - checked by check_build_environment
        raise BuildError("python-markdown fehlt – bitte „.venv\\Scripts\\python.exe -m pip install -e .[build]“ "
                         "ausführen.") from exc
    converter = markdown.Markdown(extensions=["tables", "sane_lists", "fenced_code", "toc"],
                                  extension_configs={"toc": {"slugify": slugify_unicode}}, output_format="html")
    body = converter.convert(rewrite_links(text, MANUAL_LINKS))
    root = image_root or MANUAL_SOURCE.parent
    body = _IMAGE_PARAGRAPH.sub(lambda match: _figure(match, root), body)
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", heading.group(1)).strip() if heading else f"{NAME} – Bedienungsanleitung"
    return MANUAL_TEMPLATE.format(title=title, version=html.escape(version), body=body)


def manual_link_problems(page: str, folder: Path) -> list[str]:
    """Dead references of a rendered page in ``folder``: ``#anker`` without its heading, missing files."""
    ids = set(re.findall(r'\bid="([^"]+)"', page))
    problems = []
    for ref in dict.fromkeys(_HTML_REF.findall(page)):
        target = html.unescape(ref)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        if not path:
            if anchor not in ids:
                problems.append(f"#{anchor} (keine Überschrift)")
        elif not (folder / path).is_file():
            problems.append(f"{path} (Datei fehlt)")
    return problems


def write_manual(target: Path, *, version: str = "") -> Path:
    """``docs/handbuch/BEDIENUNG.md`` -> ``<target>/Handbuch/Bedienung.html`` plus the images it shows."""
    if not MANUAL_SOURCE.is_file():
        raise BuildError(f"{MANUAL_SOURCE} fehlt – das Programmpaket braucht die Bedienungsanleitung.")
    text = MANUAL_SOURCE.read_text(encoding="utf-8")
    folder = target / MANUAL_DIR
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    images = list(dict.fromkeys(_MD_IMAGE.findall(text)))
    missing = [image for image in images if not (MANUAL_SOURCE.parent / image).is_file()]
    if missing:
        raise BuildError(f"Bilder der Bedienungsanleitung fehlen: {', '.join(missing)}")
    for image in images:
        destination = folder / image
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MANUAL_SOURCE.parent / image, destination)
    page = render_manual_html(text, version=version)
    problems = manual_link_problems(page, folder)
    if problems:
        raise BuildError(f"Tote Verweise in der Bedienungsanleitung: {', '.join(problems)}")
    out = folder / MANUAL_HTML
    out.write_text(page, encoding="utf-8", newline="\n")
    return out


# --------------------------------------------------------------------------- signing


def find_signtool() -> str | None:
    found = shutil.which("signtool")
    if found:
        return found
    kits = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"

    def key(path: Path) -> tuple[int, ...]:
        return tuple(int(n) for n in re.findall(r"\d+", path.parent.parent.name))

    candidates = sorted(kits.glob("10.*/x64/signtool.exe"), key=key)
    return str(candidates[-1]) if candidates else None


def signing_options(args: argparse.Namespace) -> dict[str, str] | None:
    """How to sign (``--sign``/``--cert-sha1`` or PARTFORGE_SIGN_CERT_SHA1 / PARTFORGE_SIGN_PFX), else ``None``."""
    sha1 = args.cert_sha1 or os.environ.get("PARTFORGE_SIGN_CERT_SHA1")
    pfx = os.environ.get("PARTFORGE_SIGN_PFX")
    if not (args.sign or sha1 or pfx):
        return None
    options = {"timestamp_url": args.timestamp_url}
    if sha1:
        options["sha1"] = sha1
    elif pfx:
        options["pfx"] = pfx
        options["password"] = os.environ.get("PARTFORGE_SIGN_PFX_PASSWORD", "")
    return options


def sign_command(signtool: str, exe: Path, *, sha1: str | None = None, pfx: str | None = None,
                 password: str | None = None, timestamp_url: str | None = TIMESTAMP_URL) -> list[str]:
    command = [signtool, "sign", "/fd", "sha256", "/d", NAME]
    if timestamp_url:
        command += ["/tr", timestamp_url, "/td", "sha256"]
    if sha1:
        command += ["/sha1", sha1]
    elif pfx:
        command += ["/f", pfx] + (["/p", password] if password else [])
    else:
        command.append("/a")  # best code-signing certificate of the certificate store
    return [*command, str(exe)]


def sign_exe(exe: Path, options: dict[str, str], *, verify: bool = True) -> None:
    signtool = find_signtool()
    if not signtool:
        raise BuildError("signtool.exe wurde nicht gefunden – bitte das Windows SDK installieren oder ohne --sign bauen.")
    command = sign_command(signtool, exe, sha1=options.get("sha1"), pfx=options.get("pfx"),
                           password=options.get("password"), timestamp_url=options.get("timestamp_url"))
    if subprocess.run(command, check=False).returncode != 0:
        raise BuildError(f"Signieren von {exe.name} fehlgeschlagen (signtool, siehe Meldung oben).")
    if verify and subprocess.run([signtool, "verify", "/pa", str(exe)], check=False).returncode != 0:
        raise BuildError(f"Die Signatur von {exe.name} ist ungültig (signtool verify).")


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Programmpaket dist\\PartForge bauen und prüfen")
    parser.add_argument("--no-frontend", action="store_true", help="vorhandenen Frontend-Build (partforge\\web) verwenden")
    parser.add_argument("--distpath", type=Path, default=ROOT / "dist", help="Zielordner (Standard: dist)")
    parser.add_argument("--workpath", type=Path, default=ROOT / "build", help="Arbeitsordner (Standard: build)")
    parser.add_argument("--no-smoke", action="store_true", help="Smoke-Test des Pakets überspringen")
    parser.add_argument("--rust-writer", help="altium-designer-mcp.exe für den Smoke-Test (Standard: wie PartForge sucht)")
    parser.add_argument("--smoke-dir", type=Path, help="Arbeitsordner des Smoke-Tests (Standard: temporär)")
    parser.add_argument("--sign", action="store_true", help="PartForge.exe signieren (signtool, Zertifikatsspeicher)")
    parser.add_argument("--cert-sha1", help="Fingerabdruck des Code-Signing-Zertifikats (sonst automatisch)")
    parser.add_argument("--timestamp-url", default=TIMESTAMP_URL, help="RFC-3161-Zeitstempeldienst")
    args = parser.parse_args(argv)
    try:
        return _build(args)
    except BuildError as exc:
        print(f"\nFEHLER: {exc}", file=sys.stderr, flush=True)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"\nFEHLER: {Path(str(exc.cmd[0])).name} ist mit Code {exc.returncode} abgebrochen (siehe oben).",
              file=sys.stderr, flush=True)
        return 1


def _build(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(ROOT))
    from partforge import __version__

    distpath = args.distpath.resolve()
    workpath = args.workpath.resolve()
    env = build_env()
    check_build_environment(env)
    if not args.no_frontend:
        build_frontend()
    if not (ROOT / "partforge" / "web" / "index.html").is_file():
        raise BuildError("partforge/web/index.html fehlt – Frontend zuerst bauen (ohne --no-frontend).")
    icon = ROOT / "partforge" / "assets" / "app.ico"
    if not icon.is_file():
        subprocess.run([sys.executable, str(SCRIPTS / "make_icon.py")], check=True)
    workpath.mkdir(parents=True, exist_ok=True)
    version_file = workpath / "version_info.txt"
    version_file.write_text(version_file_text(__version__), encoding="utf-8")

    command = pyinstaller_command(icon=icon, version_file=version_file, distpath=distpath, workpath=workpath)
    subprocess.run(command, cwd=ROOT, env=env, check=True)

    target = distpath / NAME
    if not (target / "_internal" / "partforge" / "web" / "index.html").is_file():
        raise BuildError(f"{target}\\_internal\\partforge\\web\\index.html fehlt – das Paket hätte keine Oberfläche.")
    copy_package_files(target, version=__version__)
    print(f"Bedienungsanleitung: {target / MANUAL_DIR / MANUAL_HTML}")

    sys.path.insert(0, str(SCRIPTS))
    import third_party

    try:
        licenses, counts = third_party.write_licenses(target, workpath / NAME, FRONTEND, version=__version__)
    except third_party.LicenseError as exc:
        raise BuildError(str(exc)) from exc
    print(f"\nLizenzhinweise: {licenses.name} ({counts['python']} Python-Komponenten, {counts['frontend']} npm-Pakete)")

    exe = target / f"{NAME}.exe"
    signing = signing_options(args)
    if signing is not None:
        sign_exe(exe, signing)
        print(f"{exe.name} signiert.")
    else:
        print(f"Hinweis: {exe.name} ist nicht signiert (--sign oder PARTFORGE_SIGN_CERT_SHA1/PARTFORGE_SIGN_PFX).")

    if not args.no_smoke:
        import smoke_test

        print("\nSmoke-Test des Pakets …", flush=True)
        result = smoke_test.run_smoke(target, work_dir=args.smoke_dir, writer=args.rust_writer)
        print(result.report(), flush=True)
        if not result.ok:
            raise BuildError("Der Smoke-Test des Programmpakets ist fehlgeschlagen – das Paket nicht weitergeben.")
    print(f"\nProgrammpaket: {exe}\nBitte immer den gesamten Ordner {NAME} weitergeben.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
