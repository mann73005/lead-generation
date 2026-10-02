import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { Layout } from './components/Layout'
import { Spinner } from './components/ui'
import { ApiError } from './lib/api'
import { AuthProvider, useAuth } from './lib/auth'
import { CampaignsPage } from './pages/Campaigns'
import { DashboardPage } from './pages/Dashboard'
import { DiscoveryPage } from './pages/Discovery'
import { LeadDetailPage } from './pages/LeadDetail'
import { LeadsPage } from './pages/Leads'
import { LoginPage } from './pages/Login'
import { OutreachProfilePage } from './pages/OutreachProfile'
import { UsersPage } from './pages/Users'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Retrying a 4xx just delays showing the user what is wrong. Server
        // and network faults are worth one more attempt.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
        return failureCount < 1
      },
    },
  },
})

function Protected({ adminOnly = false }: { adminOnly?: boolean }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center text-ink-muted">
        <Spinner className="size-5" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  if (adminOnly && user.role !== 'admin') return <Navigate to="/" replace />
  return <Layout />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />

            <Route element={<Protected />}>
              <Route index element={<DashboardPage />} />
              <Route path="leads" element={<LeadsPage />} />
              <Route path="leads/:leadId" element={<LeadDetailPage />} />
              <Route path="discovery" element={<DiscoveryPage />} />
              <Route path="campaigns" element={<CampaignsPage />} />
              <Route path="outreach" element={<OutreachProfilePage />} />
            </Route>

            <Route element={<Protected adminOnly />}>
              <Route path="users" element={<UsersPage />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
