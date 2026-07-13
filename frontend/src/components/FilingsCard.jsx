import { useEffect, useState } from 'react'
import { FileText, Calendar } from 'lucide-react'
import { fetchRecentFilings } from '../services/api'

export default function FilingsCard() {
  const [filings, setFilings] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchRecentFilings()
      .then(res => setFilings(res.data.filings.slice(0, 10)))
      .catch(() => setFilings([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 bg-blue-600/20 rounded-lg">
          <FileText className="w-6 h-6 text-blue-400" />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-slate-100">10-K / 20-F Released This Week</h2>
          <p className="text-sm text-slate-400">Latest annual filings from SEC EDGAR</p>
        </div>
      </div>

      {loading ? (
        <div className="text-slate-500">Loading filings...</div>
      ) : filings.length === 0 ? (
        <div className="text-slate-500">No recent filings found.</div>
      ) : (
        <div className="space-y-3 max-h-[400px] overflow-y-auto pr-2">
          {filings.map((filing, idx) => (
            <div key={idx} className="flex items-start justify-between p-3 bg-slate-950 rounded-lg border border-slate-800 hover:border-slate-700 transition-colors">
              <div>
                <div className="font-medium text-slate-200">{filing.name}</div>
                <div className="text-sm text-slate-400">{filing.ticker} · {filing.form}</div>
              </div>
              <div className="flex items-center gap-1 text-sm text-slate-500">
                <Calendar className="w-4 h-4" />
                {filing.filing_date}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
