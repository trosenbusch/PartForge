"""Program package build (scripts/build.py), licence file (scripts/third_party.py) and smoke test helpers
(scripts/smoke_test.py) – regression tests for the packaging findings PKG-01, PKG-05, PKG-07 and PKG-10.

The real build (PyInstaller, several minutes) is not run here; ``scripts/build.py`` runs the smoke test against
every package it builds.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load(name: str) -> ModuleType:
    module_name = f"pf_scripts_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


build = _load("build")
third_party = _load("third_party")
smoke = _load("smoke_test")


# --------------------------------------------------------------------------- build.py (PKG-01, PKG-07, PKG-10)


def _command(tmp_path: Path) -> list[str]:
    return build.pyinstaller_command(icon=tmp_path / "app.ico", version_file=tmp_path / "v.txt",
                                     distpath=tmp_path / "dist", workpath=tmp_path / "build")


def _option_values(command: list[str], option: str) -> list[str]:
    return [command[i + 1] for i, part in enumerate(command[:-1]) if part == option]


def test_win32timezone_is_a_hidden_import(tmp_path: Path) -> None:
    """PKG-01: pywintypes imports win32timezone from C (FILETIME -> datetime); PyInstaller cannot see it, and
    without it every PcbLib layer/height patch of the package fails."""
    assert "win32timezone" in build.HIDDEN_IMPORTS
    assert "win32timezone" in _option_values(_command(tmp_path), "--hidden-import")


def test_partforge_is_collected_without_sources(tmp_path: Path) -> None:
    """PKG-10: submodules into the PYZ and data files (web, assets, bridge scripts) – no --collect-all, which
    copies the .py sources next to the PYZ."""
    command = _command(tmp_path)
    assert "--collect-all" not in command
    assert "partforge" in _option_values(command, "--collect-submodules")
    assert "partforge" in _option_values(command, "--collect-data")
    assert "pdfminer" not in _option_values(command, "--collect-data")


@pytest.mark.parametrize("module", ["pytest", "_pytest", "pygments", "setuptools"])
def test_development_modules_are_excluded(tmp_path: Path, module: str) -> None:
    assert module in _option_values(_command(tmp_path), "--exclude-module")


def test_command_has_version_file_and_entry_point(tmp_path: Path) -> None:
    command = _command(tmp_path)
    assert _option_values(command, "--version-file") == [str(tmp_path / "v.txt")]
    assert command[-1] == str(SCRIPTS / "frozen_entry.py")
    assert "--windowed" in command and "--onedir" in command


def test_pdfplumber_is_no_runtime_dependency() -> None:
    """PKG-10: the program imports neither pdfplumber nor pdfminer; only the corpus tools do (test extra)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert not any(dep.lower().startswith(("pdfplumber", "pdfminer")) for dep in project["dependencies"])
    assert any(dep.startswith("pdfplumber") for dep in project["optional-dependencies"]["test"])
    imports = ("import pdfplumber", "from pdfplumber", "import pdfminer", "from pdfminer")
    users = [p.name for p in (ROOT / "partforge").rglob("*.py") if any(i in p.read_text(encoding="utf-8") for i in imports)]
    assert users == []


def test_build_env_makes_partforge_importable_from_any_directory() -> None:
    """PKG-10: PyInstaller's isolated subprocesses must find partforge whatever the working directory."""
    env = build.build_env()
    assert env["PYTHONPATH"].split(";")[0] == str(ROOT)


def test_check_build_environment_rejects_a_foreign_partforge(monkeypatch: pytest.MonkeyPatch) -> None:
    class Probe:
        returncode = 0
        stdout = r"C:\Elsewhere\site-packages\partforge\__init__.py"
        stderr = ""

    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: Probe())
    with pytest.raises(build.BuildError, match="nicht aus"):
        build.check_build_environment({})


@pytest.mark.parametrize(("version", "expected"), [
    ("1.0.0", (1, 0, 0, 0)), ("1.0.0b1", (1, 0, 0, 0)), ("2.3", (2, 3, 0, 0)), ("1.0.0rc1", (1, 0, 0, 0)), ("4.5.6.7", (4, 5, 6, 7)),
])
def test_version_tuple(version: str, expected: tuple[int, ...]) -> None:
    assert build.version_tuple(version) == expected


def test_version_file_is_valid_for_pyinstaller(tmp_path: Path) -> None:
    """PKG-07: file/product version, product name, description, company and copyright in the exe resource."""
    versioninfo = pytest.importorskip("PyInstaller.utils.win32.versioninfo")
    path = tmp_path / "version_info.txt"
    path.write_text(build.version_file_text("1.2.3"), encoding="utf-8")
    info = versioninfo.load_version_info_from_text_file(str(path))
    assert (info.ffi.fileVersionMS, info.ffi.fileVersionLS) == ((1 << 16) | 2, 3 << 16)
    text = str(info)
    for expected in ("'ProductName', 'PartForge'", "'FileVersion', '1.2.3'", "'ProductVersion', '1.2.3'",
                     "'OriginalFilename', 'PartForge.exe'", "'CompanyName', 'Tobias Rosenbusch'",
                     "PartForge – Altium-Datenbankbibliotheken", "© 2026 Tobias Rosenbusch"):
        assert expected in text


@pytest.mark.parametrize(("version", "flags"), [
    ("1.0.0b1", 0x2), ("1.0.0rc1", 0x2), ("1.0.0.dev1", 0x2), ("1.0.0", 0x0),
])
def test_version_resource_preserves_prerelease_and_windows_flag(tmp_path: Path, version: str, flags: int) -> None:
    """Explorer and the package smoke test see the beta label, while the fixed resource remains numeric."""
    versioninfo = pytest.importorskip("PyInstaller.utils.win32.versioninfo")
    path = tmp_path / "version_info.txt"
    path.write_text(build.version_file_text(version), encoding="utf-8")
    info = versioninfo.load_version_info_from_text_file(str(path))
    assert (info.ffi.fileVersionMS, info.ffi.fileVersionLS) == (1 << 16, 0)
    assert info.ffi.fileFlags == flags
    text = str(info)
    assert f"'FileVersion', '{version}'" in text
    assert f"'ProductVersion', '{version}'" in text


def test_copy_package_files_ships_the_package_manual(tmp_path: Path) -> None:
    """PKG-08: the package gets its own README (docs/handbuch) – not the repository README with dead links; its
    link to the user manual points at the HTML manual of the package."""
    build.copy_package_files(tmp_path, version="1.2.3")
    source = (ROOT / "docs/handbuch/README.md").read_text(encoding="utf-8")
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "](BEDIENUNG.md)" in source
    assert readme == source.replace("](BEDIENUNG.md)", "](Handbuch/Bedienung.html)")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "CHANGELOG.de.md", "Start-PartForge.cmd"):
        assert (tmp_path / name).is_file()
    assert (tmp_path / "Start-PartForge.cmd").read_bytes() == (ROOT / "Start-PartForge.cmd").read_bytes()
    relative = [t for t in re.findall(r"!?\[[^\]]*\]\(([^)\s]+)\)", readme) if not t.startswith(("http", "mailto:"))]
    assert relative and all((tmp_path / t.partition("#")[0]).is_file() for t in relative), relative


def test_user_manual_is_rendered_into_the_package(tmp_path: Path) -> None:
    """docs/handbuch/BEDIENUNG.md -> Handbuch/Bedienung.html: German standalone page, every image copied and sized,
    the table of contents (GitHub anchors such as #1-überblick) and the link to README.md work in the package."""
    build.copy_package_files(tmp_path, version="1.2.3")
    page = tmp_path / "Handbuch" / "Bedienung.html"
    text = page.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>") and '<html lang="de">' in text
    assert "<title>PartForge – Bedienungsanleitung</title>" in text and "PartForge 1.2.3" in text
    assert build.manual_link_problems(text, page.parent) == []
    source = (ROOT / "docs/handbuch/BEDIENUNG.md").read_text(encoding="utf-8")
    images = set(re.findall(r"!\[[^\]]*\]\((bilder/[^)\s]+)\)", source))
    assert images and images == {p.relative_to(page.parent).as_posix() for p in (page.parent / "bilder").iterdir()}
    for image in images:
        assert (page.parent / image).read_bytes() == (ROOT / "docs/handbuch" / image).read_bytes()
        assert re.search(rf'<a href="{re.escape(image)}"><img src="{re.escape(image)}" alt="[^"]+" width="\d+" '
                         rf'height="\d+" loading="lazy"></a><figcaption>', text), image
    assert 'href="#1-überblick"' in text and 'id="1-überblick"' in text
    assert 'id="11-häufige-fragen-und-fehlerbehebung"' in text
    assert 'href="../README.md"' in text and 'href="README.md"' not in text
    assert "<table>" in text and "<ol>" in text and "<code>" in text
    assert not re.search(r'\b(?:src|href)="(?:https?:)?//', text)  # no external resources (offline)
    assert "docs/" not in text and "BEDIENUNG.md" not in text


def test_rewrite_links_only_touches_mapped_targets() -> None:
    text = "[A](README.md) [B](README.md#x) ![C](README.md) [D](other.md) `](README.md)` [E](README.mdx)"
    assert build.rewrite_links(text, {"README.md": "../README.md"}) == (
        "[A](../README.md) [B](../README.md#x) ![C](../README.md) [D](other.md) `](../README.md)` [E](README.mdx)")


def test_manual_link_problems_names_dead_anchors_and_files(tmp_path: Path) -> None:
    (tmp_path / "da.png").write_bytes(b"x")
    page = ('<h2 id="a">A</h2><a href="#a">ok</a><a href="#b">tot</a><img src="da.png"><img src="weg.png">'
            '<a href="https://example.org/">extern</a>')
    assert build.manual_link_problems(page, tmp_path) == ["#b (keine Überschrift)", "weg.png (Datei fehlt)"]


def test_missing_manual_image_fails_the_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "src" / "BEDIENUNG.md"
    source.parent.mkdir()
    source.write_text("# Anleitung\n\n![Fehlt](bilder/fehlt.png)\n", encoding="utf-8")
    monkeypatch.setattr(build, "MANUAL_SOURCE", source)
    with pytest.raises(build.BuildError, match="fehlt.png"):
        build.write_manual(tmp_path / "pkg")


def test_sign_command_variants() -> None:
    """PKG-07: signtool with a store certificate (fingerprint or automatic) or a PFX file, SHA-256, timestamp."""
    exe = Path("PartForge.exe")
    auto = build.sign_command("signtool.exe", exe)
    assert auto[:2] == ["signtool.exe", "sign"] and "/a" in auto and auto[-1] == "PartForge.exe"
    assert auto[auto.index("/fd") + 1] == "sha256" and auto[auto.index("/tr") + 1] == build.TIMESTAMP_URL
    by_hash = build.sign_command("signtool.exe", exe, sha1="ABC123")
    assert by_hash[by_hash.index("/sha1") + 1] == "ABC123" and "/a" not in by_hash
    pfx = build.sign_command("signtool.exe", exe, pfx="cert.pfx", password="pw", timestamp_url=None)
    assert pfx[pfx.index("/f") + 1] == "cert.pfx" and pfx[pfx.index("/p") + 1] == "pw" and "/tr" not in pfx


def test_signing_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PARTFORGE_SIGN_CERT_SHA1", "PARTFORGE_SIGN_PFX", "PARTFORGE_SIGN_PFX_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    args = build.argparse.Namespace(sign=False, cert_sha1=None, timestamp_url=build.TIMESTAMP_URL)
    assert build.signing_options(args) is None
    monkeypatch.setenv("PARTFORGE_SIGN_PFX", "cert.pfx")
    monkeypatch.setenv("PARTFORGE_SIGN_PFX_PASSWORD", "pw")
    assert build.signing_options(args) == {"timestamp_url": build.TIMESTAMP_URL, "pfx": "cert.pfx", "password": "pw"}


# --------------------------------------------------------------------------- third_party.py (PKG-05)


def _site_file(module: str) -> Path:
    spec = importlib.util.find_spec(module)
    assert spec is not None and spec.origin
    return Path(spec.origin)


def _write_tocs(workpath: Path, pyz: list[Path], binaries: list[Path]) -> None:
    workpath.mkdir(parents=True, exist_ok=True)
    pyz_entries = [(p.stem, str(p), "PYMODULE") for p in pyz]
    (workpath / "PYZ-00.toc").write_text(repr((str(workpath / "PYZ-00.pyz"), pyz_entries)), encoding="utf-8")
    pkg = (str(workpath / "PartForge.pkg"), {"PYMODULE": True},
           [("pyi-contents-directory _internal", "", "OPTION"), ("PYZ-00.pyz", str(workpath / "PYZ-00.pyz"), "PYZ")])
    (workpath / "PKG-00.toc").write_text(repr(pkg), encoding="utf-8")
    collect = ([(p.name, str(p), "BINARY") for p in binaries], False)
    (workpath / "COLLECT-00.toc").write_text(repr(collect), encoding="utf-8")


def test_frozen_sources_reads_every_toc(tmp_path: Path) -> None:
    a, b = tmp_path / "a.py", tmp_path / "b.dll"
    _write_tocs(tmp_path / "w", [a], [b])
    assert {a, b} <= third_party.frozen_sources(tmp_path / "w")


def test_python_components_cover_bundled_files(tmp_path: Path) -> None:
    """Every bundled file maps to a component with licence texts: distributions (certifi MPL-2.0, pywin32 without
    the texts of parts it does not bundle), CPython with OpenSSL & co. and the WebView2 SDK."""
    webview_dir = _site_file("webview").parent / "lib"
    files = [_site_file("certifi"), _site_file("win32timezone"), Path(sys.base_prefix) / "Lib" / "json" / "__init__.py"]
    binaries = sorted(webview_dir.glob("Microsoft.Web.WebView2.Core.dll"))
    _write_tocs(tmp_path / "w", files, binaries)
    components, unknown = third_party.python_components(tmp_path / "w")
    assert unknown == []
    by_name = {c.name.lower(): c for c in components}
    certifi = by_name["certifi"]
    assert certifi.license == "MPL-2.0" and any("Mozilla Public License" in t for _s, t in certifi.texts)
    pywin32 = by_name["pywin32"]
    sources = [s for s, _t in pywin32.texts]
    assert sources and not any(s.startswith(("adodbapi/", "pythonwin/", "isapi/")) for s in sources)
    cpython = "\n".join(text for _s, text in by_name["python (cpython-laufzeit)"].texts)
    assert "PYTHON SOFTWARE FOUNDATION LICENSE" in cpython and "Microsoft Distributable Code" in cpython
    if third_party.cpython_acknowledgements() is not None:  # HTML docs installed with Python
        assert all(name in cpython for name in ("OpenSSL", "expat", "libffi", "zlib", "libmpdec"))
    if binaries:
        assert "Redistribution and use" in by_name["microsoft edge webview2 sdk"].texts[0][1]


def test_python_components_report_files_of_unknown_origin(tmp_path: Path) -> None:
    stray = tmp_path / "fremd.dll"
    stray.write_bytes(b"MZ")
    _write_tocs(tmp_path / "w", [], [stray])
    _components, unknown = third_party.python_components(tmp_path / "w")
    assert unknown == [str(stray)]


def test_bundled_distribution_without_any_text_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(third_party, "python_license_texts", lambda dist, files: [])
    _write_tocs(tmp_path / "w", [_site_file("certifi")], [])
    with pytest.raises(third_party.LicenseError, match="certifi"):
        third_party.python_components(tmp_path / "w")


def test_fallback_texts_for_distributions_without_licence_file(tmp_path: Path) -> None:
    """odfpy (no licence file in the wheel) is used under Apache-2.0 – its statement plus the full Apache text."""
    _write_tocs(tmp_path / "w", [_site_file("odf")], [])
    components, _ = third_party.python_components(tmp_path / "w")
    odfpy = next(c for c in components if c.name == "odfpy")
    assert odfpy.license.startswith("Apache-2.0")
    joined = "\n".join(t for _s, t in odfpy.texts)
    assert "Apache License 2.0" in joined and "Version 2.0, January 2004" in joined


def _fake_npm(root: Path) -> Path:
    frontend = root / "frontend"
    lock = {"packages": {
        "": {"name": "frontend"},
        "node_modules/with-file": {"version": "1.0.0", "license": "Apache-2.0"},
        "node_modules/no-file": {"version": "2.0.0", "license": "MIT"},
        "node_modules/vendoring": {"version": "3.0.0", "license": "MIT AND ISC"},
        "node_modules/dev-tool": {"version": "1.0.0", "dev": True, "license": "MIT"},
        "node_modules/other-platform": {"version": "1.0.0", "optional": True, "license": "MPL-2.0"},
    }}
    frontend.mkdir(parents=True)
    (frontend / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    packages = {
        "with-file": {"name": "with-file", "version": "1.0.0", "license": "Apache-2.0"},
        "no-file": {"name": "no-file", "version": "2.0.0", "license": "MIT", "author": "Jane Doe <jane@example.org>"},
        "vendoring": {"name": "vendoring", "version": "3.0.0", "license": "MIT AND ISC", "author": "Vendor Inc."},
        "dev-tool": {"name": "dev-tool", "version": "1.0.0", "license": "MIT"},
    }
    for name, pkg in packages.items():
        folder = frontend / "node_modules" / name
        folder.mkdir(parents=True)
        (folder / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    (frontend / "node_modules/with-file/LICENSE").write_text("Apache License\nVersion 2.0, January 2004\n…",
                                                             encoding="utf-8")
    (frontend / "node_modules/vendoring/lib-vendor/d3-x").mkdir(parents=True)
    (frontend / "node_modules/vendoring/lib-vendor/d3-x/LICENSE").write_text("ISC License\nCopyright Mike",
                                                                             encoding="utf-8")
    (frontend / "node_modules/vendoring/license.js").write_text("export const license = 1", encoding="utf-8")
    return frontend


def test_js_components_from_package_lock(tmp_path: Path) -> None:
    """Production packages with their files, nested vendor licences and SPDX standard texts; no dev tools and no
    packages of other platforms."""
    components = {c.name: c for c in third_party.js_components(_fake_npm(tmp_path))}
    assert set(components) == {"with-file", "no-file", "vendoring"}
    assert components["with-file"].texts == [("LICENSE", "Apache License\nVersion 2.0, January 2004\n…")]
    source, text = components["no-file"].texts[0]
    assert "keine Lizenzdatei" in source and "Copyright (c) Jane Doe" in text and "MIT License" in text
    vendoring = [s for s, _t in components["vendoring"].texts]
    assert vendoring[0].startswith("Standardtext MIT") and "lib-vendor/d3-x/LICENSE" in vendoring
    assert "license.js" not in vendoring


def test_js_components_need_installed_packages(tmp_path: Path) -> None:
    frontend = _fake_npm(tmp_path)
    shutil.rmtree(frontend / "node_modules")
    with pytest.raises(third_party.LicenseError, match="npm ci"):
        third_party.js_components(frontend)


@pytest.mark.skipif(not (ROOT / "frontend" / "node_modules").is_dir(), reason="frontend/node_modules fehlt")
def test_real_frontend_licences() -> None:
    """PKG-05: class-variance-authority is Apache-2.0, the fonts ship their OFL text, Vite's helper licence is cut
    before the list of Vite's own bundled dependencies, development tools are not listed."""
    components = {c.name: c for c in third_party.js_components(ROOT / "frontend")}
    assert components["class-variance-authority"].license == "Apache-2.0"
    for font in ("@fontsource-variable/inter", "@fontsource-variable/jetbrains-mono"):
        assert any("SIL OPEN FONT LICENSE" in t.upper() for _s, t in components[font].texts)
    assert "Licenses of bundled dependencies" not in components["vite"].texts[0][1]
    assert not {"typescript", "oxlint", "openapi-typescript"} & set(components)


def test_render_states_credits_and_copyleft() -> None:
    python = [third_party.Component("odfpy", "1.4.1", "Apache-2.0", texts=[("x", "TEXT-A")])]
    js = [third_party.Component("react", "19.0.0", "MIT", texts=[("LICENSE", "TEXT-B")])]
    text = third_party.render(python, js, version="1.0.0")
    assert text.startswith("PartForge 1.0.0 – Lizenzen")
    assert "The FreeType Project (www.freetype.org)" in text and "odfpy wird unter Apache-2.0 genutzt" in text
    assert "altium-designer-mcp (GPL-3.0" in text
    assert text.index("TEXT-A") < text.index("TEXT-B")


# --------------------------------------------------------------------------- smoke_test.py (PKG-01)


@pytest.mark.parametrize(("name", "leftover"), [
    ("PF_CHIP.pfhdr93642a1a.PcbLib", True), ("PF_CHIP.pfhgt0011aabb.PcbLib", True),
    ("PF_Passives.pf1234abcd.SchLib", True), ("PF_CHIP.PcbLib", False), ("PF_PFX.PcbLib", False),
    ("PF_CHIP.pfhdr.PcbLib", False),
])
def test_patch_copy_pattern(name: str, leftover: bool) -> None:
    assert bool(smoke.TEMP_COPY.search(name)) is leftover


def test_scan_logs_finds_tracebacks_and_missing_modules(tmp_path: Path) -> None:
    log = tmp_path / "partforge.log"
    log.write_text(
        "2026-10-08 20:00:00 INFO partforge: Bibliothek geöffnet\n"
        "2026-10-08 20:00:01 WARNING partforge.altium.stackup: Lagen-Kopf nicht geändert: No module named 'x'\n"
        "Traceback (most recent call last):\n"
        "ModuleNotFoundError: No module named 'win32timezone'\n"
        "2026-10-08 20:00:02 ERROR partforge: kaputt\n"
        "2026-10-08 20:00:03 WARNING uvicorn: langsam\n",
        encoding="utf-8",
    )
    found = smoke.scan_logs([log, tmp_path / "fehlt.log"])
    assert len(found) == 4 and not any("langsam" in line or "geöffnet" in line for line in found)


def test_job_problems_are_warnings_and_errors() -> None:
    job = {"log": [{"level": "info", "text": "a"}, {"level": "warn", "text": "b"}, {"level": "error", "text": "c"},
                   {"level": "success", "text": "d"}]}
    assert smoke._job_problems(job) == ["warn: b", "error: c"]


def test_isolated_env_never_reaches_the_users_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PARTFORGE_ALLOW_REAL_AI", "1")
    env = smoke.isolated_env(tmp_path, token="t", writer=None)
    assert "ANTHROPIC_API_KEY" not in env and "PARTFORGE_ALLOW_REAL_AI" not in env
    assert env["PARTFORGE_NO_ALTIUM"] == "1" and env["PARTFORGE_TOKEN"] == "t"
    for key in ("PARTFORGE_HOME", "APPDATA", "LOCALAPPDATA"):
        assert Path(env[key]).parent == tmp_path and Path(env[key]).is_dir()
    assert env.get("PARTFORGE_AI_REPLAY_DIR") == str(ROOT / "tests" / "data" / "ai_fixtures")


def test_required_modules_cover_every_router() -> None:
    from partforge.app import ROUTER_MODULES

    assert {f"partforge.api.routes_{name}" for name in ROUTER_MODULES} <= set(smoke.REQUIRED_MODULES)
    assert "win32timezone" in smoke.REQUIRED_MODULES


def test_missing_package_is_reported(tmp_path: Path) -> None:
    result = smoke.run_smoke(tmp_path / "leer")
    assert not result.ok and "PartForge.exe" in result.failures[0]


def test_smoke_checks_the_user_manual(tmp_path: Path) -> None:
    """The smoke test fails a package without the HTML manual or with a missing image."""
    missing = smoke.SmokeResult()
    smoke.check_manual(tmp_path, missing)
    assert not missing.ok and "Handbuch/Bedienung.html" in missing.failures[0]
    build.copy_package_files(tmp_path)
    complete = smoke.SmokeResult()
    smoke.check_manual(tmp_path, complete)
    shown = set(re.findall(r"!\[[^\]]*\]\((bilder/[^)\s]+)\)",
                           (ROOT / "docs/handbuch/BEDIENUNG.md").read_text(encoding="utf-8")))
    assert complete.ok and f"({len(shown)} Bilder)" in complete.passed[-1]
    next((tmp_path / "Handbuch" / "bilder").iterdir()).unlink()
    broken = smoke.SmokeResult()
    smoke.check_manual(tmp_path, broken)
    assert not broken.ok and "unvollständig" in broken.failures[0]
