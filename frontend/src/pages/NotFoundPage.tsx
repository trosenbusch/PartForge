import { Home } from 'lucide-react'
import { useLocation, useNavigate } from 'react-router'
import { PageBody, PageTitle } from '@/app/page'
import { Button, Card, EmptyState } from '@/components/ui'

export default function NotFoundPage() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  return (
    <PageBody width="narrow">
      <PageTitle title="Seite nicht gefunden" />
      <Card className="mt-6">
        <EmptyState
          illustration="search-empty"
          size="lg"
          titleAs="h2"
          title="Diese Seite gibt es nicht"
          description={`Unter „${pathname}“ gibt es nichts zu sehen. Mit Strg+K finden Sie jede Seite und Aktion.`}
          actions={
            <Button variant="primary" leftIcon={<Home />} onClick={() => navigate('/')}>
              Zur Übersicht
            </Button>
          }
        />
      </Card>
    </PageBody>
  )
}
