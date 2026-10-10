import type { ComponentType } from 'react'
import { createBrowserRouter, type RouteObject } from 'react-router'
import { setAppNavigate } from './navigation'
import { RootLayout, Splash } from './RootLayout'
import { RouteError } from './RouteError'
import { AppShell, WorkspaceGuard } from './shell/AppShell'

/** Seitenmodul per Code-Splitting laden (Standard-Export = Seitenkomponente). */
function page(load: () => Promise<{ default: ComponentType }>): RouteObject['lazy'] {
  return async () => ({ Component: (await load()).default })
}

export const routes: RouteObject[] = [
  {
    element: <RootLayout />,
    errorElement: <RouteError />,
    hydrateFallbackElement: <Splash />,
    children: [
      { path: '/willkommen', lazy: page(() => import('@/pages/willkommen/WillkommenPage')), errorElement: <RouteError /> },
      {
        element: <AppShell />,
        children: [
          {
            // Fehler einer Seite erscheinen *im* Inhaltsbereich – Sidebar und Topbar bleiben bedienbar
            errorElement: <RouteError />,
            children: [
              {
                element: <WorkspaceGuard />,
                children: [
                  { index: true, lazy: page(() => import('@/pages/uebersicht/UebersichtPage')) },
                  { path: 'bauteile', lazy: page(() => import('@/pages/bauteile/BauteilePage')) },
                  { path: 'bauteile/:table', lazy: page(() => import('@/pages/bauteile/BauteilePage')) },
                  { path: 'serien', lazy: page(() => import('@/pages/serien/SerienPage')) },
                  { path: 'import', lazy: page(() => import('@/pages/import/ImportPage')) },
                  { path: 'bibliotheksimport', lazy: page(() => import('@/pages/bibliotheksimport/BibliotheksimportPage')) },
                  { path: 'symbole', lazy: page(() => import('@/pages/symbole/SymbolePage')) },
                  { path: 'footprints', lazy: page(() => import('@/pages/footprints/FootprintsPage')) },
                  { path: 'stapelbearbeitung', lazy: page(() => import('@/pages/stapelbearbeitung/StapelbearbeitungPage')) },
                  { path: 'altium', lazy: page(() => import('@/pages/altium/AltiumPage')) },
                ],
              },
              // App-Einstellungen sind auch ohne geöffnete Bibliothek erreichbar
              { path: 'einstellungen', lazy: page(() => import('@/pages/einstellungen/EinstellungenPage')) },
              { path: 'einstellungen/:section', lazy: page(() => import('@/pages/einstellungen/EinstellungenPage')) },
              // Komponenten-Galerie (in der Befehlspalette nur im Entwicklungsmodus angeboten)
              { path: 'ui-kit', lazy: page(() => import('@/pages/uikit/UiKitPage')) },
              { path: '*', lazy: page(() => import('@/pages/NotFoundPage')) },
            ],
          },
        ],
      },
    ],
  },
]

export const router = createBrowserRouter(routes)

// Toast-Aktionen und andere Stellen außerhalb von Komponenten navigieren über den Router (kein Neuladen; Router-State
// z. B. für die Aktion der Altium-Seite)
setAppNavigate((to, options) => void router.navigate(to, options))
