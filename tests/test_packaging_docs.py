"""README, package manual and notices (packaging findings PKG-05, PKG-08, PKG-09, F3): every link resolves, the
package manual has no repository links, and the claims match the program."""
from __future__ import annotations

import re
import tomllib
import typing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
README_DE = ROOT / "README.de.md"
MANUAL = ROOT / "docs" / "handbuch" / "README.md"
USER_MANUAL = ROOT / "docs" / "handbuch" / "BEDIENUNG.md"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
CHANGELOG = ROOT / "CHANGELOG.md"
CHANGELOG_DE = ROOT / "CHANGELOG.de.md"
RELEASE_NOTES = ROOT / "docs" / "releases" / "v1.0.0-beta.1.md"
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


def _slug(heading: str) -> str:
    """GitHub's anchor of a heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _anchors(text: str) -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)}


@pytest.mark.parametrize("doc", [README, README_DE, MANUAL, USER_MANUAL, NOTICES, CHANGELOG, CHANGELOG_DE, RELEASE_NOTES],
                         ids=lambda p: p.name if p != MANUAL else "handbuch")
def test_relative_links_and_images_resolve(doc: Path) -> None:
    """PKG-08: no broken image (docs/screenshots/readme/…) or dead link."""
    text = doc.read_text(encoding="utf-8")
    broken = []
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        missing_file = bool(path) and not (doc.parent / path).exists()
        missing_anchor = not path and bool(anchor) and anchor not in _anchors(text)
        if missing_file or missing_anchor:
            broken.append(target)
    assert broken == []


def test_package_manual_has_no_repository_links() -> None:
    """PKG-08: the package ships docs/handbuch/README.md as its README – links into the repository would be dead.
    The only relative link is the one to the user manual beside it, which scripts/build.py points at
    ``Handbuch/Bedienung.html`` in the package (tests/test_packaging_build.py)."""
    text = MANUAL.read_text(encoding="utf-8")
    relative = [t for t in LINK.findall(text) if not t.startswith(("http://", "https://"))]
    assert relative and set(relative) == {"BEDIENUNG.md"}
    assert "docs/" not in text and "docs\\" not in text
    assert "`Handbuch\\Bedienung.html`" in text and "| `Handbuch\\` |" in text
    assert "%LOCALAPPDATA%\\Programs\\altium-designer-mcp\\" in text
    assert "https://github.com/embedded-society/altium-designer-mcp/releases" in text


@pytest.mark.parametrize("doc, heading", [(README, "Manuals"), (README_DE, "Handbuch")])
def test_readme_has_a_handbook_section(doc: Path, heading: str) -> None:
    """Both repository READMEs link the manuals and name the packaged HTML file."""
    text = doc.read_text(encoding="utf-8")
    section = text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]
    assert "](docs/handbuch/BEDIENUNG.md)" in section and "](docs/handbuch/README.md)" in section
    assert "Handbuch\\Bedienung.html" in section


def test_user_manual_links_back_to_the_package_manual() -> None:
    """BEDIENUNG.md links README.md (beside it in the repository, ``../README.md`` from ``Handbuch/`` in the package)
    and nothing else outside its folder."""
    text = USER_MANUAL.read_text(encoding="utf-8")
    relative = {t.partition("#")[0] for t in LINK.findall(text) if not t.startswith(("http://", "https://", "#"))}
    assert "README.md" in relative
    assert all(t == "README.md" or t.startswith("bilder/") for t in relative), relative


def test_changelog_names_this_version_and_the_known_limitations() -> None:
    from partforge import __version__

    text = CHANGELOG.read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(__version__)} – \d{{4}}-\d{{2}}-\d{{2}}$", text, re.MULTILINE)
    assert "### Known limitations" in text
    for limitation in ("XLSX export", "PcbLib", "not compressed", "Murata", "Components panel", "early beta", "vibe coding"):
        assert limitation in text, limitation
    # Both language editions are shipped together; their language links work in the package too.
    assert [t for t in LINK.findall(text) if not t.startswith(("http://", "https://"))] == ["CHANGELOG.de.md"]
    german = CHANGELOG_DE.read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(__version__)} – \d{{4}}-\d{{2}}-\d{{2}}$", german, re.MULTILINE)
    assert "### Bekannte Einschränkungen" in german
    assert [t for t in LINK.findall(german) if not t.startswith(("http://", "https://"))] == ["CHANGELOG.md"]


def test_beta_package_and_release_versions_agree() -> None:
    from packaging.version import Version
    from partforge import __version__

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["version"] == __version__
    assert "Development Status :: 4 - Beta" in project["classifiers"]
    version = Version(__version__)
    assert version.is_prerelease and version.pre[0] == "b"
    release_tag = f"v{version.base_version}-beta.{version.pre[1]}"
    notes = RELEASE_NOTES.read_text(encoding="utf-8")
    assert f"`{__version__}`" in notes and f"`{release_tag}`" in notes
    assert "First public beta" in CHANGELOG.read_text(encoding="utf-8")
    for limitation in ("Known limitations", "vibe coding", "Murata", "not compressed", "unsigned", "German"):
        assert limitation in notes, limitation


def test_rust_writer_install_path_is_where_partforge_looks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The folder the documentation suggests is one PartForge finds the writer in by itself."""
    from partforge import config

    exe = tmp_path / "Programs" / "altium-designer-mcp" / "altium-designer-mcp.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.delenv("PARTFORGE_RUST_WRITER", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert config.detect_rust_writer() == str(exe)


def test_readme_export_formats_match_the_api() -> None:
    """PKG-08: export is CSV/Excel only (ODS is import-only)."""
    from partforge.api import routes_parts

    allowed = set(typing.get_args(typing.get_type_hints(routes_parts.export_download)["format"]))
    assert allowed and "ods" not in allowed
    for doc in (README, README_DE, MANUAL):
        text = doc.read_text(encoding="utf-8")
        assert not re.search(r"Export[^|\n]*ODS", text), doc


@pytest.mark.parametrize("doc", [README, README_DE])
def test_readme_documents_postgres_as_source_only(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    assert "für Teams PostgreSQL verwenden" not in text
    assert "pip install -e .[postgres]" in text and '"kind": "postgres"' in text


@pytest.mark.parametrize("doc", [README, README_DE])
def test_readme_development_commands_install_test_and_build_tools(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    assert "pip install -e .[test,build]" in text
    assert "~4300 Tests" not in text


@pytest.mark.parametrize("doc, heading", [(README, "Uninstall"), (README_DE, "Deinstallieren"),
                                         (MANUAL, "Deinstallieren")])
def test_uninstall_and_data_locations_are_documented(doc: Path, heading: str) -> None:
    """PKG-09: where PartForge stores what, and how to remove it completely."""
    text = doc.read_text(encoding="utf-8")
    assert f"## {heading}" in text
    assert "Aus Altium deinstallieren" in text
    for location in ("%APPDATA%\\PartForge", "%LOCALAPPDATA%\\PartForge"):
        assert location in text


@pytest.mark.parametrize("doc", [README, README_DE, MANUAL], ids=["README", "README.de", "handbuch"])
def test_database_lock_after_uninstall_is_explained(doc: Path) -> None:
    """F3: after "Aus Altium deinstallieren" Altium keeps the database open for a while – the troubleshooting table
    quotes both hints of the uninstall job (``routes_altium._database_release``) and says what to do."""
    text = doc.read_text(encoding="utf-8")
    source = (ROOT / "partforge" / "api" / "routes_altium.py").read_text(encoding="utf-8")
    for hint in ("Ordner erst in etwa einer Minute verschiebbar – Altium hält die Datenbank noch offen",
                 "Ordner erst nach dem Schließen von "):
        assert hint in source  # the quoted text is what the program shows
        if doc != README:
            assert hint.strip() in text
    if doc == README:
        assert "wait about a minute" in text
        assert "Altium may still hold the database open" in text
        assert "another program holding the file, close that program" in text
        assert "restart or close Altium" in text
    else:
        assert "Altium neu starten" in text or "Altium beenden" in text


def test_notices_name_the_bundled_components() -> None:
    """PKG-05: corrected licence of class-variance-authority, the runtime parts, certifi and the FreeType credit."""
    text = NOTICES.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if "class-variance-authority" in line and line.startswith("|"))
    assert "Apache-2.0" in row and "MIT" not in row
    for name in ("certifi", "MPL-2.0", "cryptography", "Python 3.13", "OpenSSL", "WebView2", "PyInstaller",
                 "THIRD_PARTY_LICENSES.txt", "The FreeType Project", "odfpy", "SIL Open Font License"):
        assert name in text, name
    assert "site-packages/<paket>*.dist-info`, Frontend" not in text  # old, wrong claim about the package
