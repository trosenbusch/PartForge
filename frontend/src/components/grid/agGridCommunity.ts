/**
 * Einstieg „ag-grid-community“ für PartForge-Quelldateien (umgeleitet von `vite.config.ts`, Plugin
 * „partforge:ag-grid-modules“): alles wie im Paket – nur `AllCommunityModule` ist {@link ForgeCommunityModule}
 * (die Module aus `./modules.ts`). So landet nicht das ganze AG Grid im Bundle, auch wenn eine Tabelle noch
 * `modules={[AllCommunityModule]}` übergibt. Bibliotheken aus node_modules (ag-grid-react) sehen das Original.
 */
export * from 'ag-grid-community'
export { ForgeCommunityModule as AllCommunityModule } from './modules'
