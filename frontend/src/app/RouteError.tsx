import { Home, RotateCw } from 'lucide-react'
import { isRouteErrorResponse, useNavigate, useRouteError } from 'react-router'
import { Button, EmptyState } from '@/components/ui'

/** Fehleranzeige für Render-/Ladefehler einer Route. */
export function RouteError() {
  const error = useRouteError()
  const navigate = useNavigate()
  const isChunkError = error instanceof Error && /dynamically imported module|Failed to fetch/i.test(error.message)
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : String(error)

  return (
    <div className="flex h-full min-h-[60vh] items-center justify-center p-8">
      <div className="w-full max-w-xl rounded-panel border border-line bg-surface shadow-raised">
        <EmptyState
          illustration="forge"
          size="lg"
          titleAs="h2"
          title={isChunkError ? 'Neue Version verfügbar' : 'Hier ist etwas schiefgelaufen'}
          description={
            isChunkError
              ? 'Die Oberfläche wurde aktualisiert. Bitte neu laden.'
              : 'Die Seite konnte nicht angezeigt werden. Die Daten Ihrer Bibliothek sind davon nicht betroffen.'
          }
          actions={
            <>
              <Button variant="primary" leftIcon={<RotateCw />} onClick={() => window.location.reload()}>
                Neu laden
              </Button>
              <Button variant="secondary" leftIcon={<Home />} onClick={() => navigate('/')}>
                Zur Übersicht
              </Button>
            </>
          }
        >
          {!isChunkError && (
            <pre className="mono max-h-32 w-full overflow-auto rounded-button border border-line bg-bg/70 px-3 py-2 text-left text-2xs text-fg-muted">
              {message}
            </pre>
          )}
        </EmptyState>
      </div>
    </div>
  )
}
