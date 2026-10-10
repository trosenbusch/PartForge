/**
 * Leerer Zustand vor dem ersten Einlesen: was übernommen wird, wohin es kommt, warum Namen eindeutig sein müssen und
 * dass die Quelle unverändert bleibt – mit der nächsten Aktion (Ordner wählen bzw. Pfad eingeben).
 */
import { motion } from 'motion/react'
import { FolderOpen, FolderTree, Layers, ShieldCheck, Tags, TextCursorInput } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button, EmptyState } from '@/components/ui'
import { pickFolder, useNativeBridge } from '@/lib/native'

export interface IntroStateProps {
  /** Ordner der Symbole bzw. Footprints in der Bibliothek (Einstellungen der Bibliothek) */
  folders: { symbols: string; footprints: string }
  /** Gewählten Ordner einlesen */
  onPicked: (path: string) => void
  /** Fokus ins Pfadfeld */
  onFocusInput: () => void
}

export function IntroState({ folders, onPicked, onFocusInput }: IntroStateProps) {
  const bridge = useNativeBridge()
  const facts: { icon: ReactNode; title: string; text: ReactNode }[] = [
    {
      icon: <Layers />,
      title: 'Was übernommen wird',
      text: 'Symbole aus SchLib- und Footprints aus PcbLib-Dateien – auch aus integrierten Bibliotheken (IntLib), Bibliothekspaketen (LibPkg) und ZIP-Archiven. Datenbankbibliotheken (DbLib) nicht.',
    },
    {
      icon: <FolderTree />,
      title: 'Wohin es kommt',
      text: (
        <>
          Unverändert nach <span className="mono text-fg">{folders.symbols}\Import\…</span> bzw.{' '}
          <span className="mono text-fg">{folders.footprints}\Import\…</span> – die Ordnerstruktur der Quelle bleibt erhalten.
        </>
      ),
    },
    {
      icon: <Tags />,
      title: 'Eindeutige Namen',
      text: 'Altium findet Symbole und Footprints nur über ihren Namen. Ist ein Name schon vergeben oder doppelt, wird er nicht übernommen – Sie sehen vorher, welche.',
    },
    {
      icon: <ShieldCheck />,
      title: 'Quelle bleibt unverändert',
      text: 'PartForge liest die Quelle nur und kopiert die gewählten Dateien. An den Hausstil angleichen ist ein eigener, optionaler Schritt mit Sicherung.',
    },
  ]
  return (
    <motion.section
      aria-labelledby="bibliotheksimport-intro"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="flex flex-col items-center"
    >
      <EmptyState
        illustration="no-library"
        titleAs="h2"
        title={<span id="bibliotheksimport-intro">Vorhandene Altium-Bibliotheken übernehmen</span>}
        description="Firmen- oder Herstellerbibliotheken einlesen, prüfen und übernehmen – danach stehen ihre Symbole und Footprints für Bauteile, Prüfungen und die Stapelbearbeitung bereit."
        actions={
          bridge.canPickFolder ? (
            <Button
              leftIcon={<FolderOpen />}
              onClick={() =>
                void pickFolder(null).then((picked) => {
                  if (picked) onPicked(picked)
                })
              }
            >
              Ordner wählen …
            </Button>
          ) : (
            <Button leftIcon={<TextCursorInput />} onClick={onFocusInput}>
              Pfad eingeben
            </Button>
          )
        }
        className="pb-6"
      />
      <ul className="grid w-full max-w-4xl grid-cols-1 gap-x-6 gap-y-4 @[48rem]:grid-cols-2">
        {facts.map((f, i) => (
          <motion.li
            key={f.title}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: 0.05 + i * 0.025 }}
            className="flex items-start gap-3"
          >
            <span
              aria-hidden
              className="flex size-8 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted [&_svg]:size-4"
            >
              {f.icon}
            </span>
            <div className="min-w-0">
              <h3 className="text-ui font-medium text-fg">{f.title}</h3>
              <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{f.text}</p>
            </div>
          </motion.li>
        ))}
      </ul>
    </motion.section>
  )
}
