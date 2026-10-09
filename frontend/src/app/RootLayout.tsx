import { useQueryClient } from '@tanstack/react-query'
import { RotateCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Outlet } from 'react-router'
import { toast } from 'sonner'
import { errorMessage, onApiError } from '@/api/client'
import { systemKeys, useWorkspace } from '@/api/system'
import { ForgeMark } from '@/components/brand/ForgeLogo'
import { Button, ConfirmHost, EmptyState, ProgressBar } from '@/components/ui'
import { CommandPalette } from './shell/CommandPalette'
import { GlobalDropOverlay } from './shell/GlobalDropOverlay'
import { JobDock } from './shell/JobDock'
import { LibraryDialogs } from './shell/LibraryDialogs'
import { ShellCommands } from './shell/ShellCommands'

/** Startbildschirm, solange die erste Abfrage läuft (erscheint erst nach kurzer Verzögerung). */
export function Splash() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-6 opacity-0 [animation:pf-fade-in_.4s_.25s_ease-out_forwards]">
      <div className="relative">
        <div
          aria-hidden
          className="absolute -inset-10 rounded-full bg-[radial-gradient(closest-side,var(--pf-ember-strong),transparent)] blur-xl"
        />
        <ForgeMark size={64} animated glow />
      </div>
      <div className="flex w-48 flex-col items-center gap-3">
        <span className="text-lg font-semibold tracking-[-0.02em] text-fg">
          Part<span className="text-gradient-forge">Forge</span>
        </span>
        <ProgressBar indeterminate size="xs" label="PartForge wird gestartet" hideLabel />
        <span className="text-xs text-fg-subtle">Werkstatt wird angeheizt …</span>
      </div>
    </div>
  )
}

function FullscreenProblem({
  title,
  description,
  onRetry,
}: {
  title: string
  description: string
  onRetry?: () => void
}) {
  return (
    <div className="flex h-screen items-center justify-center p-8">
      <div className="w-full max-w-lg rounded-panel border border-line bg-surface shadow-raised">
        <EmptyState
          illustration="offline"
          size="lg"
          titleAs="h1"
          title={title}
          description={description}
          actions={
            <>
              {onRetry && (
                <Button variant="primary" leftIcon={<RotateCw />} onClick={onRetry}>
                  Erneut versuchen
                </Button>
              )}
              <Button variant="secondary" onClick={() => window.location.reload()}>
                Neu laden
              </Button>
            </>
          }
        />
      </div>
    </div>
  )
}

/**
 * Wurzel-Layout: wartet auf die erste Workspace-Abfrage, behandelt Sitzungs-/Verbindungsfehler
 * und stellt die globalen Overlays bereit (Befehlspalette, Drop-Zone, Dialoge, Job-Dock).
 */
export function RootLayout() {
  const workspace = useWorkspace()
  const qc = useQueryClient()
  const [sessionInvalid, setSessionInvalid] = useState(false)

  useEffect(
    () =>
      onApiError((err) => {
        if (err.status === 401) {
          setSessionInvalid(true)
        } else if (err.isNoWorkspace) {
          qc.setQueryData(systemKeys.workspace, null)
          // feste ID: mehrere gleichzeitige 409-Antworten ergeben genau einen Hinweis
          toast.info('Keine Bibliothek geöffnet', {
            id: 'no-workspace',
            description: 'Bitte eine Bibliothek öffnen oder neu anlegen.',
          })
        }
      }),
    [qc],
  )

  if (sessionInvalid) {
    return (
      <FullscreenProblem
        title="Sitzung ungültig"
        description="Diese Oberfläche gehört zu einer beendeten PartForge-Sitzung. Bitte PartForge neu starten oder die Seite neu laden."
      />
    )
  }
  if (workspace.isPending) return <Splash />
  if (workspace.isError) {
    return (
      <FullscreenProblem
        title="Backend nicht erreichbar"
        description={`${errorMessage(workspace.error)} Prüfen Sie, ob PartForge noch läuft.`}
        onRetry={() => void workspace.refetch()}
      />
    )
  }

  return (
    <>
      <ShellCommands />
      <Outlet />
      <CommandPalette />
      <GlobalDropOverlay />
      <LibraryDialogs />
      <JobDock />
      <ConfirmHost />
    </>
  )
}
