import { Routes, Route } from 'react-router-dom'
import LandingPage from './pages/LandingPage'
import CompanyPage from './pages/CompanyPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/company/:ticker" element={<CompanyPage />} />
    </Routes>
  )
}

export default App
