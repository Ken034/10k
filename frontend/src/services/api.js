import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || ''

const api = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 120000,
})

export const fetchCompany = (ticker) => api.get(`/company/${ticker}`)
export const fetchRecentFilings = () => api.get('/filings/recent')
export const searchCompanies = (query) => api.get(`/company/search?q=${encodeURIComponent(query)}`)
