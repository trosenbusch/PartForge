"""Smoke test of the built program package (``dist/PartForge``) – run by ``build.py`` after every build.

    .venv\\Scripts\\python.exe scripts\\smoke_test.py [dist\\PartForge] [--work-dir DIR] [--port N] [--keep]

Starts ``PartForge.exe --server-only`` fully isolated – ``PARTFORGE_HOME``, ``APPDATA`` and ``LOCALAPPDATA`` in a
temporary folder, ``PARTFORGE_NO_ALTIUM=1`` (a running Altium is never touched), Claude only in the replay mode
(``PARTFORGE_AI_REPLAY_DIR=tests/data/ai_fixtures``: no network, no costs) – and checks what a frozen build gets
wrong when PyInstaller misses a module or file:

* package: ``_internal/partforge/web/index.html``, LICENSE, README.md, CHANGELOG.md, THIRD_PARTY_LICENSES.txt,
  the user manual ``Handbuch/Bedienung.html`` with every image it shows, version resource of PartForge.exe; modules in the embedded PYZ (``win32timezone`` and every router present; pytest,
  Pygments, setuptools, pdfminer absent); no ``.py`` sources under ``_internal/partforge``
* server: ``GET /`` delivers the UI with the session token and one of its scripts, ``/api/health``
* library: ``POST /api/workspace/create`` with examples – the job "Bibliotheken schreiben" ends ``done`` without a
  warning (needs ``altium-designer-mcp.exe``; without it only a notice), every PcbLib has the layer header of the
  stack (named, typed mechanical layers) and footprint heights, no patch copies (``<stem>.pf…<hex8>.PcbLib``)
* datasheet (if the corpus PDF is present): analysis in the replay mode, page render, proposal
* logs (``partforge*.log`` and the console output): no ``Traceback``, ``No module named``, ``ERROR``

Exit code 0 = all checks passed, 1 = at least one failed (German report on stdout).
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPLAY_DIR = ROOT / "tests" / "data" / "ai_fixtures"
CORPUS_PDF = ROOT / "tests" / "data" / "corpus" / "pdfs" / "25AA02E48.pdf"
MANUAL = "Handbuch/Bedienung.html"

#: Python modules the PYZ of the frozen build must contain (dynamic imports PyInstaller cannot see, e.g.
#: win32timezone, which pywintypes imports from C to convert FILETIMEs – without it every PcbLib patch fails).
REQUIRED_MODULES = (
    "win32timezone", "pywintypes", "pythoncom", "partforge.app", "partforge.__main__",
    "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.on", "sqlalchemy.dialects.sqlite",
    *(f"partforge.api.routes_{name}" for name in (
        "system", "categories", "parts", "series", "symbols", "footprints", "libraries", "altium", "altium_edit",
        "datasheets", "libimport", "housestyle")),
)
#: Extension modules and DLLs below ``_internal`` (glob patterns).
REQUIRED_FILES = ("win32/win32crypt.pyd", "pywin32_system32/pywintypes3*.dll", "pywin32_system32/pythoncom3*.dll")
#: Top-level packages that must not be bundled (development tools, unused).
EXCLUDED_PACKAGES = ("pytest", "_pytest", "pygments", "setuptools", "pdfminer", "pdfplumber")
#: Patch copies beside a library (compound.replace_streams: ``<stem>.<tag><hex8><suffix>``, tags pf/pfhdr/pfhgt).
TEMP_COPY = re.compile(r"\.pf[a-z]*[0-9a-f]{8}\.(pcblib|schlib)$", re.IGNORECASE)
LOG_PROBLEM = re.compile(r"Traceback \(most recent call last\)|No module named|ModuleNotFoundError|ImportError"
                         r"| ERROR | CRITICAL ")
JOB_PROBLEM_LEVELS = frozenset({"warn", "warning", "error"})
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


@dataclass
class SmokeResult:
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    work_dir: Path | None = None

    @property
    def ok(self) -> bool:
        return not self.failures

    def check(self, condition: bool, passed: str, failed: str) -> bool:
        (self.passed if condition else self.failures).append(passed if condition else failed)
        return condition

    def report(self) -> str:
        lines = [f"  ok    {text}" for text in self.passed]
        lines += [f"  Hinweis: {text}" for text in self.notes]
        lines += [f"  FEHLER: {text}" for text in self.failures]
        head = "Smoke-Test bestanden" if self.ok else f"Smoke-Test FEHLGESCHLAGEN ({len(self.failures)} Fehler)"
        if self.work_dir is not None and not self.ok:
            lines.append(f"  Arbeitsordner (Logs, Bibliothek): {self.work_dir}")
        return "\n".join([head, *lines])


# --------------------------------------------------------------------------- package structure


def frozen_modules(exe: Path) -> set[str] | None:
    """Module names in the PYZ archive embedded in ``exe`` (``None`` if PyInstaller's reader is unavailable)."""
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError:
        return None
    archive = CArchiveReader(str(exe))
    name = next((key for key in archive.toc if key.lower().endswith(".pyz")), None)
    if name is None:
        return set()
    return set(archive.open_embedded_archive(name).toc)


def version_strings(exe: Path) -> dict[str, str]:
    """String table of the version resource of ``exe`` (empty without one)."""
    try:
        import win32api  # pywin32
    except ImportError:
        return {}
    try:
        translations = win32api.GetFileVersionInfo(str(exe), "\\VarFileInfo\\Translation")
    except Exception:  # noqa: BLE001 - pywintypes.error: no version resource
        return {}
    out: dict[str, str] = {}
    for lang, codepage in translations or []:
        for key in ("ProductName", "FileDescription", "FileVersion", "ProductVersion", "CompanyName",
                    "LegalCopyright", "OriginalFilename"):
            try:
                value = win32api.GetFileVersionInfo(str(exe), f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{key}")
            except Exception:  # noqa: BLE001, S112 - this string is not in the resource: nothing to report
                continue
            if value:
                out.setdefault(key, str(value))
    return out


def check_package(package: Path, result: SmokeResult, *, version: str) -> Path | None:
    exe = package / "PartForge.exe"
    if not result.check(exe.is_file(), "PartForge.exe vorhanden", f"{exe} fehlt"):
        return None
    internal = package / "_internal"
    result.check((internal / "partforge" / "web" / "index.html").is_file(), "Oberfläche im Paket",
                 "Oberfläche fehlt im Paket (_internal/partforge/web/index.html) – PartForge zeigt nur „Frontend ist "
                 "nicht gebaut“")
    for name in ("LICENSE", "README.md", "CHANGELOG.md", "THIRD_PARTY_LICENSES.txt"):
        result.check((package / name).is_file(), f"{name} im Paket", f"{name} fehlt im Paket")
    check_manual(package, result)
    licenses = package / "THIRD_PARTY_LICENSES.txt"
    if licenses.is_file():
        text = licenses.read_text(encoding="utf-8", errors="replace")
        wanted = ("certifi", "cryptography", "Python (CPython-Laufzeit)", "Microsoft Edge WebView2 SDK",
                  "class-variance-authority", "SIL OPEN FONT LICENSE", "FreeType Project")
        absent = [w for w in wanted if w not in text]
        result.check(not absent, "THIRD_PARTY_LICENSES.txt vollständig",
                     f"THIRD_PARTY_LICENSES.txt unvollständig, es fehlt: {', '.join(absent)}")
    sources = sorted(p.relative_to(internal).as_posix() for p in (internal / "partforge").rglob("*.py"))
    result.check(not sources, "keine Python-Quelltexte unter _internal/partforge",
                 f"{len(sources)} Python-Quelltexte im Paket (z. B. {', '.join(sources[:3])}) – --collect-all?")
    stray = [name for name in EXCLUDED_PACKAGES if (internal / name).exists()]
    result.check(not stray, "keine Entwicklungs-/Altpakete unter _internal",
                 f"nicht benötigte Pakete im Paket: {', '.join(stray)}")
    absent = [pattern for pattern in REQUIRED_FILES if not any(internal.glob(pattern))]
    result.check(not absent, "pywin32-Erweiterungen im Paket", f"Dateien fehlen im Paket: {', '.join(absent)}")
    modules = frozen_modules(exe)
    if modules is None:
        result.notes.append("PyInstaller nicht importierbar – Modulliste des Pakets nicht geprüft")
    else:
        missing = [m for m in REQUIRED_MODULES if m not in modules]
        result.check(not missing, f"alle {len(REQUIRED_MODULES)} Pflichtmodule im Paket (u. a. win32timezone)",
                     f"Module fehlen im Paket: {', '.join(missing)}")
        bundled = sorted({m.split(".")[0] for m in modules if m.split(".")[0] in EXCLUDED_PACKAGES})
        result.check(not bundled, "pytest, Pygments, setuptools, pdfminer nicht gebündelt",
                     f"nicht benötigte Module gebündelt: {', '.join(bundled)}")
    strings = version_strings(exe)
    good = strings.get("ProductName") == "PartForge" and strings.get("FileVersion", "").startswith(version)
    result.check(good, f"Versionsressource PartForge {strings.get('FileVersion', '?')}",
                 f"Versionsressource fehlt oder falsch ({strings or 'keine'}) – Explorer zeigt keine Version")
    return exe


def check_manual(package: Path, result: SmokeResult) -> None:
    """``Handbuch/Bedienung.html`` with every image and file it references (README.md one folder up)."""
    page = package / MANUAL
    if not result.check(page.is_file(), f"Bedienungsanleitung {MANUAL}", f"{MANUAL} fehlt im Paket"):
        return
    text = page.read_text(encoding="utf-8", errors="replace")
    refs = [r for r in dict.fromkeys(re.findall(r'\b(?:href|src)="([^"#]+)"', text))
            if not r.startswith(("http://", "https://", "mailto:"))]
    images = [r for r in refs if r.lower().endswith(".png")]
    missing = [r for r in refs if not (page.parent / r).is_file()]
    result.check(bool(images) and not missing, f"Bedienungsanleitung vollständig ({len(images)} Bilder)",
                 f"Bedienungsanleitung unvollständig: {', '.join(missing[:5]) or 'keine Bilder'}")


# --------------------------------------------------------------------------- running the exe


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def isolated_env(work: Path, *, token: str, writer: str | None) -> dict[str, str]:
    """Environment of the exe: own home/AppData/LocalAppData, no Altium, Claude only replayed."""
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("PARTFORGE_", "PYTHON")) and k.upper() not in ("ANTHROPIC_API_KEY",
                                                                                      "VIRTUAL_ENV")}
    for name in ("home", "appdata", "localappdata"):
        (work / name).mkdir(parents=True, exist_ok=True)
    env.update(
        PARTFORGE_HOME=str(work / "home"), APPDATA=str(work / "appdata"), LOCALAPPDATA=str(work / "localappdata"),
        PARTFORGE_NO_ALTIUM="1", PARTFORGE_TOKEN=token,
    )
    if REPLAY_DIR.is_dir():
        env["PARTFORGE_AI_REPLAY_DIR"] = str(REPLAY_DIR)
    if writer:
        env["PARTFORGE_RUST_WRITER"] = writer
    return env


def default_writer() -> str | None:
    """altium-designer-mcp.exe as the source tree would find it (PARTFORGE_RUST_WRITER, default paths)."""
    sys.path.insert(0, str(ROOT))
    try:
        from partforge.config import detect_rust_writer
    except Exception:  # noqa: BLE001 - only a convenience
        return os.environ.get("PARTFORGE_RUST_WRITER")
    return detect_rust_writer()


class Api:
    def __init__(self, base: str, token: str) -> None:
        import httpx

        self.http = httpx.Client(base_url=base, headers={"X-PartForge-Token": token}, timeout=60.0, trust_env=False)

    def get(self, path: str, **kw: Any) -> Any:
        return self.http.get(path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.http.post(path, **kw)

    def wait_job(self, job: dict[str, Any], timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        snapshot = job
        while snapshot.get("status") in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(0.5)
            snapshot = self.get(f"/api/jobs/{job['id']}").json()
        return snapshot

    def close(self) -> None:
        self.http.close()


def _job_problems(job: dict[str, Any]) -> list[str]:
    return [f"{entry.get('level')}: {entry.get('text')}" for entry in job.get("log") or []
            if str(entry.get("level", "")).lower() in JOB_PROBLEM_LEVELS]


def check_libraries(ws: Path, result: SmokeResult) -> None:
    pcblibs = sorted((ws / "Footprints").glob("*.PcbLib"))
    schlibs = sorted((ws / "Symbols").glob("*.SchLib"))
    if not result.check(bool(pcblibs and schlibs), f"{len(schlibs)} SchLib und {len(pcblibs)} PcbLib geschrieben",
                        "keine SchLib/PcbLib geschrieben"):
        return
    copies = sorted(str(p.relative_to(ws)) for p in ws.rglob("*") if TEMP_COPY.search(p.name))
    result.check(not copies, "keine Patch-Kopien (*.pf…*.PcbLib) zurückgeblieben",
                 f"{len(copies)} Patch-Kopien zurückgeblieben: {', '.join(copies[:5])}")
    sys.path.insert(0, str(ROOT))
    from partforge.altium import heights, stackup
    from partforge.workspace import WORKSPACE_FILE, WorkspaceSettings

    settings = WorkspaceSettings.model_validate_json((ws / WORKSPACE_FILE).read_text(encoding="utf-8"))
    base = stackup.parse_stackup(ws / settings.layer_stackup) if settings.layer_stackup else stackup.default_stack()
    stack = stackup.effective_stack(base, settings.layers)
    off_stack, unreadable, heights_mm = [], [], []
    for lib in pcblibs:
        try:
            problems = stackup.pcblib_layer_problems(lib, stack)
            if problems:
                off_stack.append(f"{lib.name}: {problems[0]}")
            heights_mm += [h for h in heights.read_footprint_heights(lib).values() if h > 0]
        except Exception as exc:  # noqa: BLE001 - reported as a failure
            unreadable.append(f"{lib.name} ({exc})")
    result.check(not unreadable, "PcbLib-Köpfe lesbar", f"PcbLib nicht lesbar: {', '.join(unreadable)}")
    result.check(not off_stack, "Lagen-Kopf jeder PcbLib entspricht dem Lagenaufbau (Namen, Typen)",
                 f"Lagen-Kopf nicht an den Lagenaufbau angepasst ({len(off_stack)} PcbLib), z. B. {off_stack[:1]}")
    result.check(bool(heights_mm), f"Bauhöhen geschrieben ({len(heights_mm)} Footprints > 0 mm)",
                 "keine Bauhöhe gesetzt – alle Footprints haben 0 mm")


def check_datasheet(api: Api, result: SmokeResult) -> None:
    if not (REPLAY_DIR.is_dir() and CORPUS_PDF.is_file()):
        result.notes.append(f"Datenblatt-Test übersprungen ({CORPUS_PDF.name} oder {REPLAY_DIR.name} fehlt)")
        return
    with CORPUS_PDF.open("rb") as fh:
        response = api.post("/api/datasheets", files={"file": (CORPUS_PDF.name, fh, "application/pdf")},
                            data={"extract": "true"})
    if not result.check(response.status_code in (200, 201), "Datenblatt hochgeladen",
                        f"Datenblatt-Upload: HTTP {response.status_code} {response.text[:200]}"):
        return
    body = response.json()
    ds_id = body["datasheet"]["id"]
    job = body.get("job")
    if job:
        job = api.wait_job(job, 300)
        result.check(job.get("status") == "done", "Datenblatt-Analyse (Wiedergabe) fertig",
                     f"Datenblatt-Analyse: {job.get('status')} – {job.get('error') or job.get('message')}")
    page = api.get(f"/api/datasheets/{ds_id}/pages/1.png")
    result.check(page.status_code == 200 and page.content[:8] == b"\x89PNG\r\n\x1a\n", "Seitenbild (PDFium)",
                 f"Seitenbild: HTTP {page.status_code}")
    proposal = api.post(f"/api/datasheets/{ds_id}/proposal")
    result.check(proposal.status_code == 200, "Bauteilvorschlag aus der Analyse",
                 f"Bauteilvorschlag: HTTP {proposal.status_code} {proposal.text[:200]}")


def scan_logs(paths: list[Path]) -> list[str]:
    """Distinct problem lines (Traceback, missing module, ERROR) of the given log files."""
    found: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if LOG_PROBLEM.search(line):
                entry = f"{path.name}: {line.strip()[:240]}"
                if entry not in found:
                    found.append(entry)
    return found


def run_smoke(package: Path, *, work_dir: Path | None = None, port: int | None = None, keep: bool = False,
              writer: str | None = None, startup_timeout: float = 90.0, job_timeout: float = 900.0) -> SmokeResult:
    sys.path.insert(0, str(ROOT))
    from partforge import __version__

    result = SmokeResult()
    exe = check_package(package, result, version=__version__)
    if exe is None:
        return result
    work = Path(work_dir).resolve() if work_dir else Path(tempfile.mkdtemp(prefix="partforge-smoke-"))
    if work.exists() and work_dir:
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    result.work_dir = work
    token = secrets.token_urlsafe(16)
    port = port or free_port()
    writer = writer if writer is not None else default_writer()
    env = isolated_env(work, token=token, writer=writer)
    console = work / "console.log"
    with console.open("wb") as out:
        proc = subprocess.Popen([str(exe), "--server-only", "--port", str(port)], cwd=str(work), env=env,
                                stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=NO_WINDOW)
    api = Api(f"http://127.0.0.1:{port}", token)
    try:
        if not _wait_started(api, proc, result, startup_timeout):
            return result
        _check_ui(api, token, result)
        settings = api.get("/api/settings").json()
        writer_found = settings.get("rust_writer")
        if not writer_found:
            result.notes.append("altium-designer-mcp.exe nicht gefunden – Bibliotheken nicht geschrieben "
                                "(Schreibtest übersprungen; --rust-writer PFAD)")
        ws = work / "Smoke-Bibliothek"
        response = api.post("/api/workspace/create", json={
            "path": str(ws), "name": "Smoke-Test", "with_examples": True, "write_libraries": bool(writer_found)})
        if result.check(response.status_code == 200, "Bibliothek mit Beispielen angelegt",
                        f"Bibliothek anlegen: HTTP {response.status_code} {response.text[:300]}"):
            info = response.json()
            job = info.get("job")
            if writer_found and job:
                job = api.wait_job(job, job_timeout)
                problems = _job_problems(job)
                result.check(job.get("status") == "done" and not problems,
                             f"Job „Bibliotheken schreiben“: {job.get('message')}",
                             f"Job „Bibliotheken schreiben“ {job.get('status')}: {job.get('message')}"
                             + (f" – {len(problems)} Warnungen, z. B. {problems[0]}" if problems else ""))
                check_libraries(ws, result)
            elif writer_found:
                result.failures.append("Bibliothek angelegt, aber kein Job „Bibliotheken schreiben“ gestartet")
        check_datasheet(api, result)
    finally:
        api.close()
        _stop(proc)
    logs = [console, *sorted(work.rglob("partforge*.log"))]
    problems = scan_logs(logs)
    result.check(not problems, "Protokolle ohne Traceback/fehlende Module/ERROR",
                 f"{len(problems)} Problemzeilen in den Protokollen, z. B.: " + " | ".join(problems[:3]))
    if result.ok and not keep and not work_dir:
        shutil.rmtree(work, ignore_errors=True)
        result.work_dir = None
    return result


def _wait_started(api: Api, proc: subprocess.Popen[bytes], result: SmokeResult, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            result.failures.append(f"PartForge.exe hat sich beim Start beendet (Code {proc.returncode})")
            return False
        try:
            health = api.get("/api/health")
            if health.status_code == 200 and health.json().get("ok"):
                result.passed.append(f"Server gestartet (Version {health.json().get('version')})")
                return True
        except Exception:  # noqa: BLE001, S110 - not listening yet: try again
            pass
        time.sleep(0.25)
    result.failures.append(f"Server antwortet nicht innerhalb von {timeout:.0f} s")
    return False


def _check_ui(api: Api, token: str, result: SmokeResult) -> None:
    page = api.get("/")
    html = page.text if page.status_code == 200 else ""
    result.check(f'name="partforge-token" content="{token}"' in html, "Oberfläche mit Sitzungstoken ausgeliefert",
                 f"GET / liefert keine Oberfläche (HTTP {page.status_code}: {html[:120]!r})")
    script = re.search(r'src="(/assets/[^"]+\.js)"', html)
    if script:
        asset = api.get(script.group(1))
        result.check(asset.status_code == 200 and len(asset.content) > 1000, f"Skript {script.group(1)} geladen",
                     f"Skript {script.group(1)}: HTTP {asset.status_code}")
    elif html:
        result.failures.append("index.html verweist auf kein Skript unter /assets/")


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-Test des Programmpakets (PartForge.exe)")
    parser.add_argument("package", nargs="?", type=Path, default=ROOT / "dist" / "PartForge",
                        help="Paketordner mit PartForge.exe (Standard: dist\\PartForge)")
    parser.add_argument("--work-dir", type=Path, help="Arbeitsordner (Standard: temporär, nach Erfolg gelöscht)")
    parser.add_argument("--port", type=int, help="Port des Servers (Standard: frei)")
    parser.add_argument("--rust-writer", help="Pfad zu altium-designer-mcp.exe (Standard: wie PartForge sucht)")
    parser.add_argument("--keep", action="store_true", help="Arbeitsordner auch nach Erfolg behalten")
    args = parser.parse_args(argv)
    result = run_smoke(args.package, work_dir=args.work_dir, port=args.port, keep=args.keep, writer=args.rust_writer)
    print(result.report(), flush=True)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
