import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './Layout'
import { OverviewPage } from '../features/overview/OverviewPage'
import { ActivityPage } from '../features/activity/ActivityPage'
import { SettingsPage } from '../features/settings/SettingsPage'

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/activity" element={<ActivityPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        {/* F3+ routes will be added here */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
