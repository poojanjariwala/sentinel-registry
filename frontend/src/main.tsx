import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import 'maplibre-gl/dist/maplibre-gl.css'
import './index.css'
import App from './App'
import { AuthProvider } from './lib/auth'
import Login from './pages/Login'
import MapView from './pages/MapView'
import Registry from './pages/Registry'
import CameraDetail from './pages/CameraDetail'
import Onboarding from './pages/Onboarding'
import GapAnalysis from './pages/GapAnalysis'
import LiveView from './pages/LiveView'
import VehicleSearch from './pages/VehicleSearch'
import Admin from './pages/Admin'
import Audit from './pages/Audit'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<App />}>
          <Route path="/" element={<Navigate to="/map" replace />} />
          <Route path="/map" element={<MapView />} />
          <Route path="/registry" element={<Registry />} />
          <Route path="/registry/:cameraId" element={<CameraDetail />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/gap" element={<GapAnalysis />} />
          <Route path="/live" element={<LiveView />} />
          <Route path="/vehicles" element={<VehicleSearch />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/audit" element={<Audit />} />
        </Route>
      </Routes>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
