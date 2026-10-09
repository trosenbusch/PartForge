# PartForge – Frontend

React 19 · Vite 8 · TypeScript 6 · Tailwind 4 · Radix · motion · TanStack Query · zustand · cmdk · sonner.

- Design-Briefing (verbindlich): `../docs/entwicklung/FRONTEND.md`
- Fundament, Regeln, UI-Kit und Shell-APIs für neue Seiten: [`FOUNDATION.md`](./FOUNDATION.md)
- Komponenten-Galerie im Programm: `/ui-kit` (Dev-Server: Befehlspalette → „UI-Kit anzeigen“)

```powershell
npm install
npm run dev          # http://localhost:5173, /api → Backend auf :8765 (python -m partforge --dev)
npm run build        # prüft das API-Schema, dann tsc + Build nach ../partforge/web (vom Backend ausgeliefert)
npm run typecheck
npm run lint         # oxlint inkl. jsx-a11y
npm run gen:api      # OpenAPI-Typen neu erzeugen (src/api/schema.d.ts) – nach jeder Backend-API-Änderung
```
