import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Mail } from 'lucide-react'
import SearchBar from '../components/SearchBar'
import { warmUpBackend } from '../services/api'

export default function LandingPage() {
  const navigate = useNavigate()

  // Wake up backend immediately so it's ready when user searches
  useEffect(() => {
    warmUpBackend()
  }, [])

  const handleSearch = (ticker) => {
    navigate(`/company/${ticker}`)
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12 relative">
      <div className="text-center mb-10">
        <h1 className="text-4xl md:text-5xl font-bold text-slate-100 mb-4">
          COMLB Search
        </h1>
        <p className="text-lg text-slate-400 max-w-xl mx-auto">
          Access audited financial statements for companies listed on US, Hong Kong, and China stock exchanges. Search by ticker or company name.
        </p>
      </div>

      <div className="w-full max-w-2xl">
        <SearchBar onSearch={handleSearch} />
      </div>

      {/* Contact Us */}
      <a
        href="https://docs.google.com/forms/d/e/1FAIpQLSeXqA3Ty2vS4NKAMKVIJ0cq-17-a92GZF9xwoAsl7jkIQlshg/viewform?usp=publish-editor"
        target="_blank"
        rel="noopener noreferrer"
        className="fixed bottom-6 right-6 flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-full text-sm text-slate-300 transition-colors shadow-lg"
      >
        <Mail className="w-4 h-4" />
        Contact Us
      </a>
    </div>
  )
}
