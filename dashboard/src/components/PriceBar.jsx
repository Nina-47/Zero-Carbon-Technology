import './PriceBar.css'

export default function PriceBar() {
  return (
    <div className="panel">
      <div className="panel-header">24h 分时电价调度</div>
      <div className="price-bar">
        <div className="seg valley" style={{ flex: 8 }}>低谷 22-08h · 0.262</div>
        <div className="seg flat" style={{ flex: 2 }}>平 08-10</div>
        <div className="seg peak" style={{ flex: 2 }}>高 10-11</div>
        <div className="seg critical" style={{ flex: 1 }}>尖 11-12</div>
        <div className="seg flat" style={{ flex: 2 }}>平 12-14</div>
        <div className="seg peak" style={{ flex: 1 }}>高 14-15</div>
        <div className="seg critical" style={{ flex: 3 }}>尖峰 15-17h · 1.310</div>
        <div className="seg peak" style={{ flex: 2 }}>高 17-19</div>
        <div className="seg flat" style={{ flex: 3 }}>平段 19-22h · 0.655</div>
      </div>
      <div className="price-legend">
        <span className="leg critical">尖峰 1.310 元/kWh · 储能放电</span>
        <span className="leg peak">高峰 1.048 元/kWh · 储能放电</span>
        <span className="leg flat">平段 0.655 元/kWh · 正常用电</span>
        <span className="leg valley">低谷 0.262 元/kWh · 储能充电</span>
      </div>
    </div>
  )
}
