import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'
import './CarbonEmission.css'

export default function CarbonEmission() {
  const ringRef = useRef(null)

  useEffect(() => {
    const chart = echarts.init(ringRef.current, null, { devicePixelRatio: 2 })
    chart.setOption({
      series: [{
        type: 'pie',
        radius: ['72%', '82%'],
        center: ['50%', '50%'],
        silent: true,
        label: { show: false },
        data: [
          { value: 78, itemStyle: { color: '#00e396', borderRadius: 3 } },
          { value: 22, itemStyle: { color: 'rgba(255,255,255,0.06)' } },
        ],
      }],
    })
    return () => chart.dispose()
  }, [])

  return (
    <div className="panel carbon-emission">
      <div className="panel-header">实时碳排放</div>
      <div className="emission-value">
        <span className="kpi-big">47.2</span>
        <span className="kpi-unit">tCO₂</span>
      </div>
      <div className="kpi-change down">▼ 3.2% vs 昨日</div>
      <div className="ring-section">
        <div className="ring-wrap" ref={ringRef} />
        <div className="ring-center">
          <span className="ring-pct">78<span className="ring-pct-unit">%</span></span>
          <span className="ring-lbl">已用配额</span>
        </div>
        <div className="ring-info">
          <div>剩余配额 <span className="warn">2,310 tCO₂</span></div>
          <div>月度配额 <span className="text-white">10,500 tCO₂</span></div>
          <div>日均排放 <span className="text-white">197.4 tCO₂</span></div>
        </div>
      </div>
    </div>
  )
}
