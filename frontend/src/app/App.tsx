import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './Layout'
import { OverviewPage } from '../features/overview/OverviewPage'
import { ActivityPage } from '../features/activity/ActivityPage'
import { PeersPage } from '../features/peers/PeersPage'
import { SkillBrowserPage } from '../features/skills/SkillBrowserPage'
import { SessionsPage } from '../features/sessions/SessionsPage'
import { WorkflowsPage } from '../features/workflows/WorkflowsPage'
import { MeteringPage } from '../features/metering/MeteringPage'
import { SettingsPage } from '../features/settings/SettingsPage'

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/peers" element={<PeersPage />} />
        <Route path="/skills" element={<SkillBrowserPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/metering" element={<MeteringPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
