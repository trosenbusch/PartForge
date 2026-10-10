import { t as translate } from '@/lib/i18n'
/** „Rückgängig“ für Schemaänderungen: läuft unabhängig von Komponenten (Toast-Aktion nach dem Schließen). */
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { applySchemaResult, type CategoryDef } from '@/api/settings'

export async function runUndo(action: () => Promise<CategoryDef>, done = translate("Rückgängig gemacht")): Promise<void> {
  const id = toast.loading(translate("Wird rückgängig gemacht …"))
  try {
    const cat = await action()
    applySchemaResult(cat)
    toast.success(done, { id })
  } catch (error) {
    toast.error(translate("Rückgängig machen fehlgeschlagen"), { id, description: errorMessage(error) })
  }
}
