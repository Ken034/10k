import ReactMarkdown from 'react-markdown'

export default function QualitativeSection({ qualitative }) {
  const sections = [
    { title: 'Business Description (Item 1)', content: qualitative.history_and_development },
    { title: "Management's Discussion (Item 7)", content: qualitative.mdna_analysis },
  ]

  return (
    <div className="space-y-6">
      {sections.map((section, idx) => (
        <div key={idx}>
          <h3 className="text-lg font-semibold text-slate-100 mb-3">{section.title}</h3>
          <div className="markdown-body">
            <ReactMarkdown>{section.content || 'No analysis available.'}</ReactMarkdown>
          </div>
        </div>
      ))}
    </div>
  )
}
