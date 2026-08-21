import './KPICards.css'

const cards = [
  { val: '47.2', unit: ' t', label: '今日碳排放', sub: '▼ 3.2% vs 昨日', subColor: 'var(--green)' },
  { val: '82', unit: '%', label: '绿电消纳率', sub: '↑ 5% vs 上月', subColor: 'var(--green)' },
  { val: '38.5', unit: 'k', label: '虚拟电厂收益', sub: '↑ 12% vs 上月', subColor: 'var(--green)' },
  { val: '2.31', unit: 'k', label: '碳配额剩余 tCO₂', valColor: 'var(--warn)' },
  { val: '●', unit: '', label: '系统状态', valColor: 'var(--green)', sub: '3/3 子系统正常', isStatus: true },
]

export default function KPICards() {
  return (
    <div className="kpi-cards">
      {cards.map((c, i) => (
        <div className="kpi-card" key={i}>
          <div className="kpi-card-val" style={c.valColor ? { color: c.valColor } : {}}>
            {c.val}
            <span className="kpi-card-unit">{c.unit}</span>
          </div>
          <div className="kpi-card-label">{c.label}</div>
          {c.sub && <div className="kpi-card-sub" style={c.subColor ? { color: c.subColor } : {}}>{c.sub}</div>}
        </div>
      ))}
    </div>
  )
}
