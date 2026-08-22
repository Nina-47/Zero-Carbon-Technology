import './CarbonReduction.css'

const items = [
  { name: '光伏减排', value: '12.4 t', pct: 100, color: 'var(--green)' },
  { name: '储能调峰', value: '8.7 t', pct: 70, color: 'var(--cyan)' },
  { name: '负荷优化', value: '6.3 t', pct: 51, color: 'var(--warn)' },
]

export default function CarbonReduction() {
  return (
    <div className="panel">
      <div className="panel-header">碳减排贡献</div>
      {items.map((item, i) => (
        <div className="bar-item" key={i}>
          <span className="bar-name">{item.name}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: item.pct + '%', background: item.color }} />
          </span>
          <span className="bar-val" style={{ color: item.color }}>{item.value}</span>
        </div>
      ))}
    </div>
  )
}
