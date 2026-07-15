import { Printer } from 'lucide-react'

const DISPLAY_YEARS = 10

export default function FinancialTable({ rows, companyName, ticker, marketCap, currency = 'USD' }) {
  if (!rows || rows.length === 0) return null

  const currencySymbol = currency === 'HKD' ? 'HK$' : currency === 'CNY' ? 'RMB ' : '$'
  const currencyLabel = currency === 'HKD' ? 'HKD' : currency === 'CNY' ? 'RMB' : 'USD'

  // Take the last 10 years (API returns ascending order)
  const allYears = rows[0].values.map(v => v.year)
  const startIdx = Math.max(0, allYears.length - DISPLAY_YEARS)
  const years = allYears.slice(startIdx)

  // Slice each row's values to match
  const displayRows = rows.map(row => ({
    ...row,
    values: row.values.slice(startIdx),
  }))

  const isAsianStock = currency === 'HKD' || currency === 'CNY'

  // Metrics that should show whole numbers for HK/China stocks
  const WHOLE_NUMBER_METRICS = [
    'Weighted Avg Diluted Shares (M)',
    'Revenue ($M)',
    'Depreciation ($M)',
    'Long-Term Debt ($M)',
    'Property, Plant & Equipment ($M)',
    'Inventory ($M)',
  ]

  // Percentage metrics that should show exactly one decimal place
  const PERCENTAGE_METRICS = [
    'Operating Margin (%)',
    'Income Tax Rate (%)',
    'Net Profit Margin (%)',
    'Return on Capital (%)',
  ]

  const formatValue = (val, metricName) => {
    if (val === null || val === undefined) return '-'
    // Percentage metrics: exactly one decimal place
    if (PERCENTAGE_METRICS.includes(metricName)) {
      return val.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
    }
    // Remove decimals for specified HK/China metrics
    if (isAsianStock && WHOLE_NUMBER_METRICS.includes(metricName)) {
      return Math.round(val).toLocaleString()
    }
    return val.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }

  const formatMarketCapForPrint = (val) => {
    if (!val) return ''
    if (val >= 1e12) return `${currencySymbol}${(val / 1e12).toFixed(2)}T`
    if (val >= 1e9) return `${currencySymbol}${(val / 1e9).toFixed(2)}B`
    if (val >= 1e6) return `${currencySymbol}${(val / 1e6).toFixed(2)}M`
    return `${currencySymbol}${val.toLocaleString()}`
  }

  const handlePrint = () => {
    const printWindow = window.open('', '_blank', 'width=1200,height=800')
    if (!printWindow) return

    const headerCells = years.map(y =>
      `<th style="padding:4px 6px;border:1px solid #999;background:#e8e8e8;font-weight:600;text-align:right;white-space:nowrap;">${y}</th>`
    ).join('')

    const bodyRows = displayRows.map((row, idx) => {
      const bg = idx % 2 === 0 ? '#fff' : '#f5f5f5'
      const cells = row.values.map(cell =>
        `<td style="padding:3px 6px;border:1px solid #bbb;background:${bg};text-align:right;white-space:nowrap;">${formatValue(cell.value, row.metric_name)}</td>`
      ).join('')
      return `<tr>
        <td style="padding:3px 6px;border:1px solid #bbb;background:${bg};font-weight:500;text-align:left;white-space:nowrap;">${row.metric_name}</td>
        ${cells}
      </tr>`
    }).join('')

    printWindow.document.write(`<!DOCTYPE html>
<html>
<head>
  <title>${companyName} Financial Summary</title>
  <style>
    @page { size: landscape; margin: 10mm; }
    body { margin: 0; padding: 16px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    h1 { font-size: 20px; margin: 0 0 2px; color: #111; }
    p.subtitle { font-size: 11px; color: #555; margin: 0 0 14px; }
    table { width: 100%; border-collapse: collapse; font-size: 9px; line-height: 1.4; }
    th:first-child, td:first-child { text-align: left; }
  </style>
</head>
<body>
  <h1>${companyName} (${ticker})</h1>
  <p class="subtitle">Financial Summary — 10 Years — ${new Date().toLocaleDateString()} — All figures in ${currencyLabel}${marketCap ? ` — Market Cap: ${formatMarketCapForPrint(marketCap)}` : ''}</p>
  <table>
    <thead><tr>
      <th style="padding:4px 6px;border:1px solid #999;background:#e8e8e8;font-weight:600;text-align:left;white-space:nowrap;">Metric</th>
      ${headerCells}
    </tr></thead>
    <tbody>${bodyRows}</tbody>
  </table>
</body>
</html>`)

    printWindow.document.close()
    setTimeout(() => {
      printWindow.print()
      printWindow.close()
    }, 300)
  }

  return (
    <div className="relative">
      {/* Print button */}
      <div className="flex justify-end mb-3">
        <button
          onClick={handlePrint}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-sm text-slate-300 transition-colors"
        >
          <Printer className="w-4 h-4" />
          Print Table
        </button>
      </div>

      {/* Screen table — 10 years, scrollable on smaller screens */}
      <div className="rounded-xl border border-slate-700 overflow-x-auto">
        <table className="w-full min-w-[900px] border-collapse">
          <thead>
            <tr className="bg-slate-800/80">
              <th className="text-left text-sm font-semibold text-slate-300 px-4 py-3 border-b border-slate-700 sticky left-0 bg-slate-800/80 z-10">
                Metric
              </th>
              {years.map(year => (
                <th key={year} className="text-right text-sm font-semibold text-slate-400 px-3 py-3 border-b border-slate-700 whitespace-nowrap min-w-[80px]">
                  {year}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, idx) => (
              <tr key={idx} className={idx % 2 === 0 ? 'bg-slate-900' : 'bg-slate-900/60'}>
                <td className="px-4 py-3 font-medium text-slate-200 border-b border-slate-800 text-sm whitespace-nowrap sticky left-0 bg-inherit z-10">
                  {row.metric_name}
                </td>
                {row.values.map((cell, i) => (
                  <td key={i} className="text-right px-3 py-3 text-slate-300 border-b border-slate-800 whitespace-nowrap text-sm tabular-nums min-w-[80px]">
                    {formatValue(cell.value, row.metric_name)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
