import { useI18n } from '@/lib/i18n'
import { Home } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router'
import { PageBody, PageTitle } from '@/app/page'
import { Button, Card, EmptyState } from '@/components/ui'

export default function NotFoundPage() {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  return (
    <PageBody width="narrow">
      <PageTitle title={tr("Seite nicht gefunden")} />
      <Card className="mt-6">
        <EmptyState
          illustration="search-empty"
          size="lg"
          titleAs="h2"
          title={tr("Diese Seite gibt es nicht")}
          description={tr("Unter „{0}“ gibt es nichts zu sehen. Mit Strg+K finden Sie jede Seite und Aktion.", { "0": String(pathname) })}
          actions={
            <Button variant="primary" leftIcon={<Home />} onClick={() => navigate('/')}>
              {tr("Zur Übersicht")}</Button>
          }
        />
      </Card>
    </PageBody>
  )
}
