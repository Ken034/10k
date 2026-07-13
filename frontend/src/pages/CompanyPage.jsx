import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Building2, TrendingUp } from 'lucide-react'
import SearchBar from '../components/SearchBar'
import FinancialTable from '../components/FinancialTable'
import { fetchCompany } from '../services/api'

function formatMarketCap(val) {
  if (!val) return ''
  if (val >= 1e12) return `$${(val / 1e12).toFixed(2)}T`
  if (val >= 1e9) return `$${(val / 1e9).toFixed(2)}B`
  if (val >= 1e6) return `$${(val / 1e6).toFixed(2)}M`
  return `$${val.toLocaleString()}`
}

export default function CompanyPage() {
  const { ticker } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const loadCompany = (t) => {
    setLoading(true)
    setError(null)
    fetchCompany(t)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Failed to load company'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (ticker) loadCompany(ticker)
  }, [ticker])

  const handleSearch = (newTicker) => {
    navigate(`/company/${newTicker}`)
  }

  return (
    <div className="min-h-screen px-4 py-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex flex-col md:flex-row items-start md:items-center gap-4 mb-8">
          <button
            onClick={() => navigate('/')}
            className="p-2 bg-slate-900 border border-slate-800 rounded-xl hover:bg-slate-800 transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-slate-300" />
          </button>
          <div className="flex-1 w-full md:w-auto">
            <SearchBar onSearch={handleSearch} loading={loading} />
          </div>
        </div>

        {loading && (
          <div className="text-center py-20 text-slate-400">
            <div className="animate-pulse">Analyzing {ticker}...</div>
          </div>
        )}

        {error && (
          <div className="bg-rose-900/20 border border-rose-800 text-rose-200 rounded-xl p-4 mb-6">
            {error}
          </div>
        )}

        {!loading && data && (
          <>
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 mb-6">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-blue-600/20 rounded-xl">
                  <Building2 className="w-8 h-8 text-blue-400" />
                </div>
                <div>
                  <h1 className="text-3xl font-bold text-slate-100">{data.profile.name}</h1>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-slate-400 mt-1">
                    <span className="font-mono text-blue-400">{data.profile.ticker}</span>
                    <span>•</span>
                    <span>CIK: {data.profile.cik}</span>
                    <span>•</span>
                    <span className="capitalize">{data.profile.sector_bucket}</span>
                    {data.latest_filing_date && (
                      <>
                        <span>•</span>
                        <span>Latest filing: {data.latest_filing_date}</span>
                      </>
                    )}
                    {data.market_cap && (
                      <>
                        <span>•</span>
                        <span className="text-emerald-400">Market Cap: {formatMarketCap(data.market_cap)}</span>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 mb-6">
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="w-5 h-5 text-emerald-400" />
                <h2 className="text-xl font-semibold text-slate-100">Financials</h2>
                <span className="text-sm text-slate-500 ml-2">Last 10 years</span>
              </div>
              <FinancialTable rows={data.financial_table} companyName={data.profile.name} ticker={data.profile.ticker} marketCap={data.market_cap} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
