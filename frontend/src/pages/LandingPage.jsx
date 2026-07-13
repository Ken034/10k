import { useNavigate } from 'react-router-dom'
import SearchBar from '../components/SearchBar'
import FilingsCard from '../components/FilingsCard'

export default function LandingPage() {
  const navigate = useNavigate()

  const handleSearch = (ticker) => {
    navigate(`/company/${ticker}`)
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="text-center mb-10">
        <h1 className="text-4xl md:text-5xl font-bold text-slate-100 mb-4">
          SEC Financial Analyst
        </h1>
        <p className="text-lg text-slate-400 max-w-xl mx-auto">
          AI-powered analysis of 10-K and 20-F filings. Search any US-listed ticker for qualitative insights and 15-year audited financials.
        </p>
      </div>

      <div className="w-full max-w-2xl mb-12">
        <SearchBar onSearch={handleSearch} />
      </div>

      <div className="w-full max-w-2xl">
        <FilingsCard />
      </div>
    </div>
  )
}
