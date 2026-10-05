import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './styles.css'
import { Sidebar } from './components/Sidebar'
import { ArenaPage } from './pages/ArenaPage'
import { ConfigWizard } from './pages/ConfigWizard'
import { ConfigurationsPage } from './pages/ConfigurationsPage'
import { DatasetsPage } from './pages/DatasetsPage'
import { ExperimentsPage } from './pages/ExperimentsPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
import { SettingsPage } from './pages/SettingsPage'

const queryClient = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="shell">
          <Sidebar />
          <main className="main">
            <Routes>
              <Route path="/" element={<Navigate to="/experiments" replace />} />
              <Route path="/experiments" element={<ExperimentsPage />} />
              <Route path="/experiments/:id" element={<ArenaPage />} />
              <Route path="/datasets" element={<DatasetsPage />} />
              <Route path="/configurations" element={<ConfigurationsPage />} />
              <Route path="/configurations/new" element={<ConfigWizard />} />
              <Route path="/configurations/:id" element={<ConfigWizard />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route
                path="/observability"
                element={
                  <PlaceholderPage
                    title="Observability"
                    eyebrow="Observability"
                    headline="See exactly what the model saw."
                    lead="Every arena answer is already logged as a fingerprinted decision trace. This page will gather them: prompts, fields used, drift and cost."
                    primary="Coming next"
                    steps={[
                      { title: 'Decision traces', body: 'Immutable records of each model call, hashed so they can be verified later.' },
                      { title: 'Context audit', body: 'Which rows, fields and connections were in the context window, and which were cited.' },
                      { title: 'Drift', body: 'Repeat the same question over time and track consistency and agreement rate.' },
                    ]}
                  />
                }
              />
              <Route
                path="/saved"
                element={
                  <PlaceholderPage
                    title="Saved attempts"
                    eyebrow="Saved attempts"
                    headline="Keep the runs worth keeping."
                    lead="Pin an arena result to compare against later, or promote a reviewed question into your golden dataset."
                    primary="Coming next"
                    steps={[
                      { title: 'Pin', body: 'Save a result with its full context and verdict as a named attempt.' },
                      { title: 'Compare', body: 'Put saved attempts side by side to see what changed and whether it helped.' },
                      { title: 'Promote', body: 'Turn a reviewed question into a new golden test case.' },
                    ]}
                  />
                }
              />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
