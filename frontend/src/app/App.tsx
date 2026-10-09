import { QueryClientProvider } from '@tanstack/react-query'
import { LucideProvider } from 'lucide-react'
import { MotionConfig } from 'motion/react'
import { RouterProvider } from 'react-router/dom'
import { queryClient } from '@/api/queryClient'
import { Toaster, TooltipProvider } from '@/components/ui'
import { router } from './router'
import { useJobDock } from './stores'
import { useTheme } from './theme'
import { ThemeProvider } from './ThemeProvider'

/** Toasts weichen dem Job-Dock aus (Pille oder aufgeklapptes Panel). */
function ThemedToaster() {
  const { resolvedTheme } = useTheme()
  const dockVisible = useJobDock((s) => s.visible)
  const dockHeight = useJobDock((s) => s.height)
  return <Toaster theme={resolvedTheme} offsetBottom={dockVisible ? Math.max(84, dockHeight + 32) : 20} />
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MotionConfig reducedMotion="user">
          {/* Icons: 1,75 px Strich passt zu 13-px-Inter (Lucide-Standard 2 px wirkt zu schwer) */}
          <LucideProvider strokeWidth={1.75}>
            <TooltipProvider delayDuration={350} skipDelayDuration={200}>
              <RouterProvider router={router} />
              <ThemedToaster />
            </TooltipProvider>
          </LucideProvider>
        </MotionConfig>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
