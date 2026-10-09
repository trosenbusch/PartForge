"""Licence notices of the program package: ``THIRD_PARTY_LICENSES.txt`` (written by ``build.py``).

The file lists every third-party component of ``dist/PartForge`` with its licence texts:

* **Python** – each distribution with at least one file in the frozen set (the source paths of PyInstaller's
  ``PYZ-00.toc``, ``PKG-00.toc`` and ``COLLECT-00.toc``, mapped to distributions through their ``RECORD``): the
  texts named by ``License-File`` (else the licence files of its ``.dist-info``) plus the notices of vendored
  code in bundled folders. A distribution without any text needs an entry in :data:`FALLBACK`
  (``scripts/licenses/``) – otherwise :class:`LicenseError`, the build fails.
* **Runtime** – CPython (``LICENSE.txt`` of the base installation: PSF licence, the Microsoft Visual C++ runtime
  conditions, bzip2, libffi, OpenSSL, Tcl/Tk; plus "Licenses and Acknowledgements for Incorporated Software" from
  its HTML documentation when installed – expat, zlib, libmpdec, mimalloc … –, else a link to it), the PyInstaller
  bootloader and runtime hooks (part of the frozen set) and the Microsoft WebView2 SDK DLLs of pywebview
  (``licenses/webview2-sdk.txt``).
* **Oberfläche** – the npm packages of ``frontend/package-lock.json`` that are no development dependencies (a
  superset of the bundle: build-only tools such as Tailwind's compiler are listed too) with their licence files,
  nested vendor licences and – for packages without a file – the standard text of their SPDX id, plus the
  runtime helpers Vite and Rolldown put into every bundle (:data:`JS_RUNTIME_HELPERS`).

    .venv\\Scripts\\python.exe scripts\\third_party.py [--workpath build\\PartForge] [--out dist\\PartForge]
"""
from __future__ import annotations

import argparse
import ast
import datetime as _dt
import hashlib
import importlib.metadata as md
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LICENSE_DIR = Path(__file__).resolve().parent / "licenses"
FILE_NAME = "THIRD_PARTY_LICENSES.txt"
TOC_FILES = ("PYZ-00.toc", "PKG-00.toc", "COLLECT-00.toc")
OWN_DISTRIBUTIONS = frozenset({"partforge"})
#: Folders of the repository whose files are PartForge's own (MIT, see LICENSE).
OWN_FOLDERS = ("partforge", "scripts", "frontend")

LICENSE_NAME = re.compile(r"^(licen[cs]es?|copying|notice|copyright|authors)([._-].*)?$", re.IGNORECASE)
CODE_SUFFIXES = frozenset({".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".map", ".py", ".pyc", ".pyi",
                           ".css", ".html", ".htm", ".svg", ".png"})
#: Upper limit of one licence file (protects against data files that merely look like one).
MAX_LICENSE_BYTES = 512 * 1024
#: ``License-File`` entries for parts of a distribution that the package does not contain:
#: ``{distribution: {License-File prefix: installed folder}}`` – skipped unless a bundled file lives in the folder.
UNBUNDLED_LICENSE_PARTS: dict[str, dict[str, str]] = {
    "pywin32": {
        "adodbapi/": "adodbapi/",
        "pythonwin/": "pythonwin/",
        "isapi/": "isapi/",
        "com/win32comext/mapi/": "win32comext/mapi/",
    },
}
#: Distributions without licence files in their wheel: texts from ``scripts/licenses/``.
FALLBACK: dict[str, tuple[str, ...]] = {
    "odfpy": ("odfpy.txt", "apache-2.0.txt"),
    "proxy-tools": ("proxy_tools.txt",),
}
#: Licence labels where the metadata says too little or too much (the texts stay those of the package).
LICENSE_LABELS: dict[str, str] = {
    "odfpy": "Apache-2.0 (gewählt; wahlweise GPL-2.0-or-later)",
    "pyinstaller": "GPL-2.0-or-later mit Bootloader-Ausnahme (Laufzeit-Hooks: Apache-2.0)",
    "pyinstaller-hooks-contrib": "Apache-2.0 (Laufzeit-Hooks) / GPL-2.0-or-later",
    "clr-loader": "MIT",
    "pywebview": "BSD-3-Clause",
    "pywin32": "PSF-2.0",
    "pypdfium2": "Apache-2.0 / BSD-3-Clause (PDFium: BSD-3-Clause, FreeType: FTL, ICU, libjpeg-turbo, …)",
}
WEBVIEW2_DLL = re.compile(r"^(Microsoft\.Web\.WebView2\..+|WebView2Loader)\.dll$", re.IGNORECASE)
#: npm development packages whose runtime code ends up in every bundle; their licence text is cut before the
#: list of the dependencies they bundle into their own (build-time) code.
JS_RUNTIME_HELPERS: dict[str, str] = {
    "vite": "Laufzeithilfen von Vite (Modul-Preload) im Bundle",
    "rolldown": "Laufzeithilfen von Rolldown (Modul-Wrapper) im Bundle",
}
_BUNDLED_DEPS_HEADING = re.compile(r"^#+\s*Licenses of bundled dependencies", re.IGNORECASE | re.MULTILINE)
#: Notices that must appear in the documentation of the package (also in THIRD_PARTY_NOTICES.md).
CREDITS = (
    ("Portions of this software are copyright © 1996-2025 The FreeType Project (www.freetype.org). "
     "All rights reserved. (FreeType ist Teil von PDFium in pypdfium2.)"),
)
SEPARATOR = "=" * 100
RULE = "-" * 100


class LicenseError(RuntimeError):
    """The licence file would be incomplete (German message)."""


@dataclass
class Component:
    """One third-party component with its licence texts ``[(source, text)]``."""

    name: str
    version: str = ""
    license: str = ""
    url: str = ""
    note: str = ""
    texts: list[tuple[str, str]] = field(default_factory=list)

    @property
    def title(self) -> str:
        return f"{self.name} {self.version}".strip()


# --------------------------------------------------------------------------- helpers


def read_text(path: Path) -> str:
    """A licence file as text (UTF-8, else Windows-1252/Latin-1), with ``\\n`` line ends and no outer blank lines."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def is_license_file(path: Path) -> bool:
    return (
        LICENSE_NAME.match(path.name) is not None
        and path.suffix.lower() not in CODE_SUFFIXES
        and path.is_file()
        and path.stat().st_size <= MAX_LICENSE_BYTES
    )


def _key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, folder: Path) -> bool:
    return _key(path).startswith(_key(folder).rstrip("\\/") + os.sep)


def _template(spdx: str, holder: str) -> str | None:
    """Standard text of a simple licence (MIT, ISC, BSD-3-Clause, Apache-2.0) for packages without a file."""
    holder = holder or "the authors"
    if spdx == "MIT":
        return MIT_TEXT.format(holder=holder)
    if spdx == "ISC":
        return ISC_TEXT.format(holder=holder)
    if spdx in ("BSD-3-Clause", "BSD"):
        return BSD3_TEXT.format(holder=holder)
    if spdx == "Apache-2.0":
        return read_text(LICENSE_DIR / "apache-2.0.txt")
    return None


def _templates_for(expression: str, holder: str) -> list[tuple[str, str]] | None:
    """Texts for an SPDX expression such as ``MIT AND ISC`` (every part known), else ``None``."""
    parts = [p.strip("() ") for p in re.split(r"\s+(?:AND|OR)\s+", expression.strip()) if p.strip("() ")]
    out: list[tuple[str, str]] = []
    for part in parts or [expression]:
        text = _template(part, holder)
        if text is None:
            return None
        out.append((f"Standardtext {part} (das Paket enthält keine Lizenzdatei)", text))
    return out


def guess_license(texts: Iterable[tuple[str, str]]) -> str | None:
    """Licence name from the text when the metadata names none (e.g. webgl-constants: MIT file, no field)."""
    for _source, text in texts:
        head = " ".join(text[:1500].split())
        if "Permission is hereby granted, free of charge" in head:
            return "MIT"
        if "Permission to use, copy, modify, and/or distribute" in head:
            return "ISC"
        if "Apache License" in head and "Version 2.0" in head:
            return "Apache-2.0"
        if "Redistribution and use in source and binary forms" in head:
            return "BSD"
    return None


def _dedupe(texts: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for source, text in texts:
        digest = hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()
        if digest not in seen:
            seen.add(digest)
            out.append((source, text))
    return out


# --------------------------------------------------------------------------- Python (frozen set)


def _toc_sources(node: Any) -> Iterator[str]:
    """Source paths of the ``(name, source, TYPECODE)`` entries anywhere in a PyInstaller TOC structure."""
    if isinstance(node, tuple) and len(node) == 3 and all(isinstance(x, str) for x in node) and node[2].isupper():
        yield node[1]
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from _toc_sources(item)


def frozen_sources(workpath: Path) -> set[Path]:
    """Absolute source paths of everything PyInstaller put into the package (modules, binaries, data)."""
    found: set[Path] = set()
    for name in TOC_FILES:
        toc = workpath / name
        if not toc.is_file():
            raise LicenseError(f"{toc} fehlt – die Lizenzliste entsteht aus dem PyInstaller-Lauf (scripts\\build.py).")
        tree = ast.literal_eval(toc.read_text(encoding="utf-8", errors="replace"))
        found.update(Path(src) for src in _toc_sources(tree) if src and os.path.isabs(src))
    return found


def distribution_index() -> dict[str, md.Distribution]:
    """``{normalised file path: distribution}`` from the ``RECORD`` of every installed distribution."""
    index: dict[str, md.Distribution] = {}
    for dist in md.distributions():
        for item in dist.files or ():
            index.setdefault(_key(dist.locate_file(item)), dist)
    return index


def _dist_name(dist: md.Distribution) -> str:
    return re.sub(r"[-_.]+", "-", (dist.metadata["Name"] or "").strip()).lower()


def _info_dir(dist: md.Distribution) -> Path | None:
    for item in dist.files or ():
        if item.name in ("METADATA", "PKG-INFO") and item.parent.name.endswith((".dist-info", ".egg-info")):
            return Path(dist.locate_file(item)).parent
    return None


def _license_label(meta: Any) -> str:
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) <= 200:
        return text
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return " / ".join(classifiers) or "siehe Lizenztext"


def _project_url(meta: Any) -> str:
    wanted = ("source", "source code", "repository", "homepage", "home", "github", "code")
    urls = {}
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip().lower()] = url.strip()
    for label in wanted:
        if urls.get(label):
            return urls[label]
    return (meta.get("Home-page") or "").strip() or f"https://pypi.org/project/{meta['Name']}/"


def _holder(meta: Any) -> str:
    author = (meta.get("Author") or "").strip()
    if not author:
        email = (meta.get("Author-email") or "").strip()
        author = email.split("<")[0].strip().strip('"') if email else ""
    return author


def python_license_texts(dist: md.Distribution, bundled: set[Path]) -> list[tuple[str, str]]:
    """Licence texts of a bundled distribution (``License-File`` entries, ``.dist-info`` files, vendored notices)."""
    info = _info_dir(dist)
    base = Path(dist.locate_file(""))
    rel_bundled = {Path(p).resolve().relative_to(base.resolve()).as_posix().lower()
                   for p in bundled if _is_within(p, base)}
    unbundled = {
        prefix: folder
        for prefix, folder in UNBUNDLED_LICENSE_PARTS.get(_dist_name(dist), {}).items()
        if not any(rel.startswith(folder.lower()) for rel in rel_bundled)
    }
    texts: list[tuple[str, str]] = []

    def add(path: Path, source: str, *, declared: bool = False) -> None:
        # a declared License-File (e.g. pypdfium2's LICENSES/Apache-2.0.txt) needs no licence-like name
        if (declared and path.is_file() and path.stat().st_size <= MAX_LICENSE_BYTES) or is_license_file(path):
            texts.append((source, read_text(path)))

    if info is not None:
        for entry in dist.metadata.get_all("License-File") or []:
            entry = entry.replace("\\", "/")
            if any(entry.startswith(prefix) for prefix in unbundled):
                continue
            for candidate in (info / "licenses" / entry, info / entry):
                if candidate.is_file():
                    add(candidate, entry, declared=True)
                    break
        if not texts:
            for item in dist.files or ():
                path = Path(dist.locate_file(item))
                if _is_within(path, info) and is_license_file(path):
                    rel = path.relative_to(info).as_posix()
                    if not any(rel.removeprefix("licenses/").startswith(prefix) for prefix in unbundled):
                        add(path, rel)
    # notices of vendored code inside bundled folders (e.g. anthropic/_vendor/…/NOTICE.md)
    bundled_dirs: set[str] = set()
    base_key = _key(base)
    for path in bundled:
        if not _is_within(path, base):
            continue
        for parent in Path(path).parents:
            key = _key(parent)
            if key == base_key or not key.startswith(base_key):
                break
            bundled_dirs.add(key)
    for item in dist.files or ():
        path = Path(dist.locate_file(item))
        if info is not None and _is_within(path, info):
            continue
        if _key(path.parent) in bundled_dirs and is_license_file(path):
            add(path, item.as_posix())
    return _dedupe(texts)


def python_components(workpath: Path, *, root: Path = ROOT) -> tuple[list[Component], list[str]]:
    """Components of the frozen set (distributions, CPython, WebView2 SDK) and the files no component claims."""
    sources = frozen_sources(workpath)
    index = distribution_index()
    by_dist: dict[str, tuple[md.Distribution, set[Path]]] = {}
    cpython: set[Path] = set()
    unknown: list[str] = []
    webview2 = False
    base_prefix = Path(sys.base_prefix)
    own = [root / folder for folder in OWN_FOLDERS]
    for path in sorted(sources):
        if WEBVIEW2_DLL.match(path.name):
            webview2 = True
        if _is_within(path, workpath) or any(_is_within(path, folder) for folder in own):
            continue  # PyInstaller's own build products (bootloader: see the "pyinstaller" distribution) / PartForge
        dist = index.get(_key(path))
        if dist is not None:
            if _dist_name(dist) not in OWN_DISTRIBUTIONS:
                by_dist.setdefault(_dist_name(dist), (dist, set()))[1].add(path)
            continue
        if _is_within(path, base_prefix):
            cpython.add(path)
            continue
        unknown.append(str(path))

    components: list[Component] = []
    missing: list[str] = []
    for name in sorted(by_dist):
        dist, files = by_dist[name]
        meta = dist.metadata
        component = Component(
            name=meta["Name"], version=dist.version, license=LICENSE_LABELS.get(name) or _license_label(meta),
            url=_project_url(meta),
            texts=python_license_texts(dist, files),
        )
        if name == "pyinstaller":
            component.note = "Bootloader (PartForge.exe) und Laufzeit-Hooks; GPL-2.0-or-later mit Bootloader-Ausnahme"
        if name == "pyinstaller-hooks-contrib":
            component.note = "Laufzeit-Hooks (pyi_rth_*), Apache-2.0"
        if not component.texts and name in FALLBACK:
            component.texts = [(f"scripts/licenses/{file}", read_text(LICENSE_DIR / file)) for file in FALLBACK[name]]
        if not component.texts:
            generated = _templates_for(component.license, _holder(meta))
            if generated:
                component.texts = generated
        if not component.texts:
            missing.append(f"{component.title} ({component.license})")
        elif component.license == "siehe Lizenztext":
            component.license = guess_license(component.texts) or component.license
        components.append(component)
    if missing:
        raise LicenseError(
            "Für diese mitgelieferten Python-Pakete wurde kein Lizenztext gefunden: " + ", ".join(missing)
            + ". Bitte den Text unter scripts/licenses/ ablegen und in scripts/third_party.py (FALLBACK) eintragen."
        )
    components.append(cpython_component(sorted(cpython)))
    if webview2:
        components.append(Component(
            name="Microsoft Edge WebView2 SDK", license="BSD-3-Clause-artige Lizenz der Microsoft Corporation",
            url="https://www.nuget.org/packages/Microsoft.Web.WebView2",
            note="Microsoft.Web.WebView2.Core.dll, Microsoft.Web.WebView2.WinForms.dll, WebView2Loader.dll (über pywebview)",
            texts=[("scripts/licenses/webview2-sdk.txt", read_text(LICENSE_DIR / "webview2-sdk.txt"))],
        ))
    return components, unknown


class _HtmlText(HTMLParser):
    """Plain text of an HTML page (block elements become line breaks, ``<pre>`` keeps its layout)."""

    BLOCKS = frozenset({"p", "div", "h1", "h2", "h3", "h4", "li", "pre", "br", "tr", "section", "dt", "dd", "ul",
                        "ol"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.pre = 0
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.skip += tag in ("script", "style", "nav")
        self.pre += tag == "pre"
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        self.skip = max(0, self.skip - (tag in ("script", "style", "nav")))
        self.pre = max(0, self.pre - (tag == "pre"))
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data if self.pre else re.sub(r"\s+", " ", data))

    def text(self) -> str:
        lines = "".join(self.parts).replace("¶", "").splitlines()  # ¶: permalink markers of the headings
        return re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in lines)).strip()


CPYTHON_ACK_HEADING = re.compile(r"^Licenses and Acknowledgements for Incorporated Software\s*$", re.MULTILINE)
CPYTHON_LICENSE_URL = "https://docs.python.org/{major}.{minor}/license.html"


def cpython_acknowledgements(base: Path | None = None) -> str | None:
    """"Licenses and Acknowledgements for Incorporated Software" (OpenSSL, expat, libffi, zlib, libmpdec, mimalloc …)
    from the HTML documentation of the Python installation, if it was installed."""
    page = Path(base or sys.base_prefix) / "Doc" / "html" / "license.html"
    if not page.is_file():
        return None
    parser = _HtmlText()
    parser.feed(page.read_text(encoding="utf-8", errors="replace"))
    text = parser.text()
    match = CPYTHON_ACK_HEADING.search(text)
    if match is None:
        return None
    section = text[match.start():]
    for end in ("\nTable of Contents\n", "\nThis page\n", "\nNavigation\n"):
        cut = section.find(end)
        if cut > 0:
            section = section[:cut]
    return section.strip()


def cpython_component(files: Iterable[Path] = ()) -> Component:
    """The CPython runtime (python3xx.dll, standard library, DLLs such as libssl/libcrypto, libffi, sqlite3)."""
    license_file = Path(sys.base_prefix) / "LICENSE.txt"
    if not license_file.is_file():
        raise LicenseError(
            f"{license_file} fehlt – das Programmpaket muss mit einer python.org-Installation gebaut werden, "
            "deren LICENSE.txt die Lizenzen der Laufzeit enthält."
        )
    dlls = sorted({p.name for p in files if p.suffix.lower() in (".dll", ".pyd")})
    note = "python3xx.dll, Standardbibliothek und Laufzeit-DLLs"
    if dlls:
        note = f"Standardbibliothek und {', '.join(dlls[:12])}{' …' if len(dlls) > 12 else ''}"
    url = CPYTHON_LICENSE_URL.format(major=sys.version_info[0], minor=sys.version_info[1])
    texts = [("LICENSE.txt der Python-Installation", read_text(license_file))]
    acknowledgements = cpython_acknowledgements()
    if acknowledgements:
        texts.append(("Doc/html/license.html der Python-Installation", acknowledgements))
    else:
        note += f"; Lizenzen aller in Python enthaltenen Bibliotheken: {url}"
    return Component(
        name="Python (CPython-Laufzeit)", version=sys.version.split()[0],
        license="PSF-2.0; enthaltene Bibliotheken unter eigenen Lizenzen (OpenSSL: Apache-2.0, libffi, expat, zlib, "
                "libmpdec, bzip2, xz, SQLite: Public Domain) und die Microsoft Visual C++ Runtime",
        url=url, note=note, texts=texts,
    )


# --------------------------------------------------------------------------- user interface (npm)


def _npm_license(pkg: dict[str, Any], meta: dict[str, Any]) -> str:
    value: Any = pkg.get("license") or meta.get("license") or pkg.get("licenses") or ""
    if isinstance(value, dict):
        value = value.get("type", "")
    if isinstance(value, list):
        value = " OR ".join(str(v.get("type", v)) if isinstance(v, dict) else str(v) for v in value)
    return str(value).strip() or "siehe Lizenztext"


def _npm_url(pkg: dict[str, Any], name: str) -> str:
    repo: Any = pkg.get("repository")
    if isinstance(repo, dict):
        repo = repo.get("url")
    if isinstance(repo, str) and repo:
        url = re.sub(r"^git\+", "", repo).removesuffix(".git")
        if url.startswith("github:"):
            url = "https://github.com/" + url.removeprefix("github:")
        elif re.fullmatch(r"[\w.-]+/[\w.-]+", url):
            url = "https://github.com/" + url
        return url.replace("git://", "https://").replace("ssh://git@", "https://")
    return str(pkg.get("homepage") or f"https://www.npmjs.com/package/{name}")


def _npm_author(pkg: dict[str, Any]) -> str:
    author: Any = pkg.get("author") or ""
    if isinstance(author, dict):
        author = author.get("name", "")
    return re.sub(r"\s*[<(].*$", "", str(author)).strip()


def _npm_license_files(folder: Path, *, depth: int = 3) -> list[Path]:
    """Licence files of a package folder and of vendored code below it (never nested node_modules)."""
    skip = {"node_modules", "test", "tests", "__tests__", "docs", "example", "examples", ".git"}
    found: list[Path] = []

    def walk(current: Path, level: int) -> None:
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                if level < depth and entry.name.lower() not in skip:
                    walk(entry, level + 1)
            elif is_license_file(entry):
                found.append(entry)

    walk(folder, 0)
    return found


def _npm_component(folder: Path, meta: dict[str, Any], *, helper: str = "") -> Component:
    pkg = json.loads(read_text(folder / "package.json"))
    name = str(pkg.get("name") or folder.name)
    license = _npm_license(pkg, meta)
    texts: list[tuple[str, str]] = []
    files = [folder / f for f in ("LICENSE", "LICENSE.md", "LICENSE.txt") if (folder / f).is_file()][:1] if helper \
        else _npm_license_files(folder)
    for path in files:
        text = read_text(path)
        if helper:
            match = _BUNDLED_DEPS_HEADING.search(text)
            text = text[: match.start()].rstrip() if match else text
        texts.append((path.relative_to(folder).as_posix(), text))
    if not any(path.parent == folder for path in files):
        # no licence file of the package itself (only vendored ones, or none): standard text of its own licence –
        # for "MIT AND ISC" (victory-vendor: own code MIT, vendored d3 ISC with its files) the first part
        parts = [p.strip("() ") for p in re.split(r"\s+(?:AND|OR)\s+", license) if p.strip("() ")]
        own = _templates_for(parts[0], _npm_author(pkg) or f"the {name} authors") if parts else None
        texts = (own or []) + texts
    texts = _dedupe(texts)
    if license == "siehe Lizenztext":
        license = guess_license(texts) or license
    return Component(name=name, version=str(pkg.get("version", "")), license=license, url=_npm_url(pkg, name),
                     note=helper, texts=texts)


def js_components(frontend: Path) -> list[Component]:
    """npm packages of the user interface (no development dependencies) plus Vite's/Rolldown's runtime helpers."""
    lock_file = frontend / "package-lock.json"
    if not lock_file.is_file():
        raise LicenseError(f"{lock_file} fehlt – ohne sie lassen sich die Lizenzen der Oberfläche nicht ermitteln.")
    if not (frontend / "node_modules").is_dir():
        raise LicenseError(
            f"{frontend / 'node_modules'} fehlt – bitte im Ordner frontend „npm ci“ ausführen: die Lizenztexte der "
            "Oberfläche stammen aus den installierten Paketen."
        )
    lock = json.loads(read_text(lock_file))
    components: list[Component] = []
    missing: list[str] = []
    for key, meta in sorted(lock.get("packages", {}).items()):
        if not key or meta.get("dev") or meta.get("devOptional") or meta.get("link"):
            continue
        folder = frontend / key
        if not (folder / "package.json").is_file():
            continue  # optional package for another platform – not installed, not bundled
        component = _npm_component(folder, meta)
        if not component.texts:
            missing.append(f"{component.title} ({component.license})")
        components.append(component)
    for name, note in JS_RUNTIME_HELPERS.items():
        folder = frontend / "node_modules" / name
        if (folder / "package.json").is_file():
            components.append(_npm_component(folder, {}, helper=note))
    if missing:
        raise LicenseError("Für diese npm-Pakete der Oberfläche wurde kein Lizenztext gefunden: " + ", ".join(missing))
    return components


# --------------------------------------------------------------------------- output


def render(python: list[Component], frontend: list[Component], *, version: str, today: _dt.date | None = None) -> str:
    """The text of THIRD_PARTY_LICENSES.txt."""
    day = (today or _dt.datetime.now().astimezone().date()).isoformat()
    lines = [
        f"PartForge {version} – Lizenzen der mitgelieferten Komponenten",
        "=" * 60,
        "",
        "PartForge selbst steht unter der MIT-Lizenz (Datei LICENSE). Das Programmpaket enthält die unten",
        "aufgeführten Komponenten von Drittanbietern; zu jeder folgen Lizenz, Quelle und die Lizenztexte.",
        "Copyleft: Keine Komponente steht ausschließlich unter GPL/LGPL/AGPL – odfpy wird unter Apache-2.0 genutzt,",
        "der PyInstaller-Bootloader steht unter GPL-2.0-or-later mit Bootloader-Ausnahme, certifi unter MPL-2.0",
        "(unveränderte Datei, Quelle: https://github.com/certifi/python-certifi).",
        "Nicht enthalten: altium-designer-mcp (GPL-3.0, separat zu installieren; Quelle:",
        "https://github.com/embedded-society/altium-designer-mcp) und der SQLite3 ODBC Driver.",
        f"Erzeugt von scripts/third_party.py am {day}.",
        "",
        "Hinweise",
        "-" * 8,
        *[f"* {credit}" for credit in CREDITS],
        "",
        f"Übersicht – Python-Laufzeit und -Pakete ({len(python)})",
        "-" * 60,
        *[f"  {c.title} – {c.license}" for c in python],
        "",
        f"Übersicht – Oberfläche, npm-Pakete ({len(frontend)}; Produktionsabhängigkeiten laut package-lock.json,",
        "einschließlich Werkzeugen, die nur beim Bauen laufen)",
        "-" * 60,
        *[f"  {c.title} – {c.license}" for c in frontend],
        "",
    ]
    for heading, group in (("PYTHON-LAUFZEIT UND -PAKETE", python), ("OBERFLÄCHE (NPM-PAKETE)", frontend)):
        lines += ["", SEPARATOR, heading, SEPARATOR]
        for component in group:
            lines += ["", SEPARATOR, component.title, f"Lizenz: {component.license}"]
            if component.url:
                lines.append(f"Quelle: {component.url}")
            if component.note:
                lines.append(f"Hinweis: {component.note}")
            for source, text in component.texts:
                lines += [RULE, f"[{source}]", "", text]
    return "\n".join(lines).rstrip() + "\n"


def collect(workpath: Path, frontend: Path) -> tuple[list[Component], list[Component], list[str]]:
    python, unknown = python_components(workpath)
    return python, js_components(frontend), unknown


def write_licenses(target: Path, workpath: Path, frontend: Path, *, version: str) -> tuple[Path, dict[str, int]]:
    """Write ``target/THIRD_PARTY_LICENSES.txt``; returns the path and counts. Raises :class:`LicenseError` when a
    bundled component has no licence text or a bundled file belongs to no known component."""
    python, js, unknown = collect(workpath, frontend)
    if unknown:
        raise LicenseError(
            "Diese mitgelieferten Dateien gehören zu keinem bekannten Paket (Lizenz unklar): "
            + ", ".join(unknown[:10]) + (" …" if len(unknown) > 10 else "")
        )
    path = target / FILE_NAME
    path.write_text(render(python, js, version=version), encoding="utf-8", newline="\r\n")
    return path, {"python": len(python), "frontend": len(js)}


MIT_TEXT = """MIT License

Copyright (c) {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of
the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""

ISC_TEXT = """ISC License

Copyright (c) {holder}

Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby
granted, provided that the above copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER
IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE."""

BSD3_TEXT = """BSD 3-Clause License

Copyright (c) {holder}
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following
   disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the
   following disclaimer in the documentation and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote
   products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="THIRD_PARTY_LICENSES.txt für das Programmpaket schreiben")
    parser.add_argument("--workpath", type=Path, default=ROOT / "build" / "PartForge",
                        help="PyInstaller-Arbeitsordner mit PYZ-00.toc, PKG-00.toc, COLLECT-00.toc")
    parser.add_argument("--frontend", type=Path, default=ROOT / "frontend")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "PartForge", help="Zielordner")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    from partforge import __version__

    try:
        path, counts = write_licenses(args.out, args.workpath, args.frontend, version=__version__)
    except LicenseError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    print(f"{path}: {counts['python']} Python-Komponenten, {counts['frontend']} npm-Pakete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
