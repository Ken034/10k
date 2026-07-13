export default function CAGRCard({ rows }) {
  if (!rows || rows.length === 0) return null

  return (
    <div className="rounded-xl border border-slate-800">
      <table className="w-full table-fixed border-collapse financial-table">
        <thead>
          <tr>
            <th className="text-left">Metric</th>
            <th className="text-right">5Y CAGR</th>
            <th className="text-right">10Y CAGR</th>
            <th className="text-right">15Y CAGR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx} className="hover:bg-slate-900/50">
              <td className="font-medium text-slate-200">{row.metric_name}</td>
              <td className="text-right text-slate-300">
                {row.cagr_5y !== null ? `${row.cagr_5y}%` : '-'}
              </td>
              <td className="text-right text-slate-300">
                {row.cagr_10y !== null ? `${row.cagr_10y}%` : '-'}
              </td>
              <td className="text-right text-slate-300">
                {row.cagr_15y !== null ? `${row.cagr_15y}%` : '-'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
