import { useState, useEffect, useRef } from 'react'
import { Search } from 'lucide-react'
import { searchCompanies } from '../services/api'

export default function SearchBar({ onSearch, loading }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const debounceRef = useRef(null)
  const dropdownRef = useRef(null)
  const justSelectedRef = useRef(false)

  // Debounced search
  useEffect(() => {
    if (!query.trim() || query.trim().length < 2) {
      setResults([])
      setShowDropdown(false)
      return
    }

    // Skip search if user just selected a result (to avoid re-showing dropdown)
    if (justSelectedRef.current) {
      justSelectedRef.current = false
      return
    }

    if (debounceRef.current) clearTimeout(debounceRef.current)

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchCompanies(query.trim())
        setResults(res.data.results || [])
        setShowDropdown(true)
        setSelectedIndex(-1)
      } catch {
        setResults([])
      }
    }, 300)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query])

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (selectedIndex >= 0 && results[selectedIndex]) {
      selectResult(results[selectedIndex])
    } else if (results.length > 0) {
      // If user typed a name and pressed Enter, select the first result
      selectResult(results[0])
    } else if (query.trim()) {
      // If user typed a ticker directly (e.g., AAPL), use it
      onSearch(query.trim().toUpperCase())
      setShowDropdown(false)
    }
  }

  const selectResult = (result) => {
    justSelectedRef.current = true
    setQuery(result.ticker)
    setResults([])
    setShowDropdown(false)
    onSearch(result.ticker)
  }

  const handleKeyDown = (e) => {
    if (!showDropdown) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((prev) => Math.max(prev - 1, -1))
    } else if (e.key === 'Escape') {
      setShowDropdown(false)
    }
  }

  return (
    <div ref={dropdownRef} className="w-full max-w-2xl mx-auto relative">
      <form onSubmit={handleSubmit} className="w-full">
        <div className="relative flex items-center">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => results.length > 0 && setShowDropdown(true)}
            placeholder="Search US, HK, or China stocks (e.g. AAPL, 0700.HK, 600519)..."
            className="w-full bg-slate-900 border border-slate-700 rounded-2xl py-4 pl-6 pr-16 text-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent shadow-xl"
          />
          <button
            type="submit"
            disabled={loading}
            className="absolute right-2 p-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 rounded-xl transition-colors"
          >
            <Search className="w-6 h-6 text-white" />
          </button>
        </div>
      </form>

      {/* Dropdown */}
      {showDropdown && results.length > 0 && (
        <div className="absolute z-50 w-full mt-2 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden">
          {results.map((result, idx) => (
            <button
              key={result.ticker}
              type="button"
              onClick={() => selectResult(result)}
              className={`w-full px-6 py-3 text-left flex items-center gap-4 transition-colors ${
                idx === selectedIndex
                  ? 'bg-blue-600/30'
                  : 'hover:bg-slate-800'
              }`}
            >
              <span className="font-mono text-blue-400 font-semibold w-24">
                {result.ticker}
              </span>
              <span className="text-slate-300 truncate">{result.name}</span>
              {result.exchange && (
                <span className="text-xs px-2 py-0.5 bg-amber-600/30 text-amber-400 rounded">
                  {result.exchange}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
