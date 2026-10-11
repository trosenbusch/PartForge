# Security policy

## Supported versions

PartForge is an early beta. Security fixes target the latest beta release and the current default
branch. Older beta releases are not maintained separately; update before reproducing a report
when possible.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/trosenbusch/PartForge/security/advisories/new).
Do not report vulnerabilities, exposed credentials or exploit details in public issues or pull
requests. If private reporting is unavailable, open an issue asking for a private security contact
without including the vulnerability details.

Include the affected version or commit, Windows version, reproduction steps, impact and a minimal
proof of concept. Remove real API keys, session tokens, personal information and proprietary
component libraries or datasheets. Test with synthetic data and your own libraries.

Reports are reviewed on a best-effort basis. The maintainer may request more information, work
with you on a fix and coordinate disclosure through a GitHub security advisory. No fixed response
or resolution time is promised.

## Security boundaries

PartForge runs a local HTTP API on the loopback interface with a per-session access token and
request-origin checks. It is intended for a trusted Windows account on a local machine; exposing
its API to a network is not a supported deployment. The development server uses a documented
development token and is for local development only.

Stored Claude API keys use Windows DPAPI and are tied to the Windows account. Keys provided
through environment variables or a configured key file remain the user's responsibility. AI
features send selected PDF pages or search requests to Anthropic; avoid submitting confidential
data without permission. See [Data and security](README.md#data-and-security) for storage locations
and application behavior.

Generated components, symbols and footprints require engineering review before use. Incorrect
electrical or mechanical output without a security impact belongs in a normal bug report.
