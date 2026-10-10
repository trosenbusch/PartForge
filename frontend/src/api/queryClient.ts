import { t as tr } from '@/lib/i18n'
import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError, cleanErrorText, errorMessage, isAbortError } from './client'

declare module '@tanstack/react-query' {
  interface Register {
    defaultError: Error
    mutationMeta: {
      /** Überschrift des automatischen Fehler-Toasts (Standard: „Aktion fehlgeschlagen“) */
      errorTitle?: string
      /** Keinen automatischen Fehler-Toast zeigen (Fehler wird selbst behandelt) */
      silentError?: boolean
      /** Erfolgs-Toast nach Abschluss */
      successMessage?: string
    }
    queryMeta: {
      /** Fehler dieser Abfrage als Toast melden (Standard: aus – Seiten zeigen Fehler inline) */
      errorToast?: string
      /**
       * Daten ändern sich nicht durch Hintergrundjobs (Generator-Familien, Symboltypen, Vorlagen …): nach einem
       * erfolgreich beendeten Job **nicht** neu laden. (Beim Bibliothekswechsel werden sie trotzdem zurückgesetzt.)
       */
      static?: boolean
    }
  }
}

function shouldRetry(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError) {
    // Netzwerkfehler / Backend startet gerade: kurz erneut versuchen, sonst nicht
    if (error.status === 0 || error.status === 502 || error.status === 503) return failureCount < 2
    return false
  }
  return failureCount < 1
}

export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      const title = query.meta?.errorToast
      if (!title || isAbortError(error)) return
      if (error instanceof ApiError && (error.status === 401 || error.isNoWorkspace)) return
      toast.error(title, { id: `query-error:${title}`, description: cleanErrorText(errorMessage(error)) })
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _result, mutation) => {
      if (mutation.meta?.silentError || isAbortError(error)) return
      if (error instanceof ApiError && (error.status === 401 || error.isNoWorkspace)) return // Shell zeigt eigenen Hinweis
      toast.error(mutation.meta?.errorTitle ?? tr("Aktion fehlgeschlagen"), { description: cleanErrorText(errorMessage(error)) })
    },
    onSuccess: (_data, _variables, _result, mutation) => {
      const msg = mutation.meta?.successMessage
      if (msg) toast.success(msg)
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      gcTime: 5 * 60_000,
      retry: shouldRetry,
      retryDelay: (attempt) => Math.min(400 * 2 ** attempt, 3000),
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
})
