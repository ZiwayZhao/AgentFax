import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './Layout'
import { OverviewPage } from '../features/overview/OverviewPage'

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<OverviewPage />} />
        {/* F2+ routes will be added here */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
