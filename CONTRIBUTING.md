# Contributing to PartForge

PartForge is an early beta, developed largely with AI assistance and vibe coding. Bug reports,
documentation improvements, translations and focused code changes are welcome. AI-assisted
contributions are welcome too; contributors are responsible for reviewing and verifying their work.

## Issues and security reports

Search [existing issues](https://github.com/trosenbusch/PartForge/issues) before opening a bug report
or feature request. Use the issue forms and provide a small, reproducible example, the PartForge
version or commit, Windows version and any relevant Altium or library-writer version.

For vulnerabilities, follow [SECURITY.md](SECURITY.md) and use private reporting. Review logs and
attachments before posting: remove API keys, session tokens, personal paths and proprietary data.
Only contribute component libraries, datasheets, images and test fixtures you have permission to
redistribute. Synthetic fixtures are preferred when they reproduce the problem.

## Development setup

Use Windows 10/11, Python 3.11 or later and Node.js 22.12 or later. CI tests Python 3.11 and 3.13
with Node.js 24. The desktop window also needs WebView2. Altium, the external Rust library writer
and a Claude API key are optional for development and are not needed by the offline test suite.

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test,build]" -c constraints.txt
cd frontend
npm.cmd ci
cd ..
```

Start the backend with `.venv\Scripts\python.exe -m partforge --dev` and, in another terminal,
run `npm.cmd run dev` from `frontend`. See [README.md](README.md#development) for the API port,
development token and package build. Existing architecture and frontend guides are under
`docs/entwicklung/` and are currently in German.

## Checks before a pull request

Run the following from the repository root. These settings explicitly disable tests requiring
Claude API requests, a running Altium instance or the external library writer:

```powershell
$env:PARTFORGE_TEST_AI = "0"
$env:PARTFORGE_TEST_ALTIUM = "0"
$env:PARTFORGE_TEST_RUST = "0"
$env:PARTFORGE_ALLOW_REAL_AI = "0"
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m pytest -q -m "not ai and not altium and not rustwriter"
cd frontend
npm.cmd run build
npm.cmd run lint
npm.cmd test
```

CI also scans the complete fetched Git history and current files, including nested archives, with
[Gitleaks](https://github.com/gitleaks/gitleaks). Its Windows binary version and SHA-256 are pinned in
the workflow. When updating the scanner, verify the matching checksum from its official release.

Pytest isolates application settings in a temporary `PARTFORGE_HOME`. Live tests are opt-in through
the environment variables documented in `tests/conftest.py`; run them only with your own test
libraries and credentials. The CI workflow never enables live tests or supplies API keys.

When API models change, run `npm.cmd run gen:api` from `frontend` and commit `openapi.json` and
`src/api/schema.d.ts`. The frontend build checks that the committed schema matches the backend.
When dependencies change, update the frontend lockfile or the tested Python constraints, install
the updated dependencies and rerun the relevant checks. `scripts/update_constraints.py` records
the installed Python versions; review its output before committing.

## Pull requests

Keep each change focused and explain the problem, resulting behavior and validation. Add tests
that reproduce bugs or cover meaningful new behavior. For visible UI changes, include screenshots
and update both English and German strings in `frontend/src/i18n/catalogs/`. Update the relevant
documentation and changelog when behavior or setup changes.

Do not commit generated builds, local settings, secrets, personal libraries or externally supplied
files without redistribution rights. The project's own code uses the [MIT license](LICENSE);
third-party code and assets must retain their notices and compatible licensing. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
