import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'

const dailyData = [258.3, 268.5, 271.7, 262.3, 219.8, 217.6, 282.8]
const dates = ['6/23', '6/24', '6/25', '6/26', '6/27', '6/28', '6/29']
const colors = ['#00e396', '#00e396', '#00e396', '#00e396', 'rgba(0,180,216,0.6)', 'rgba(0,180,216,0.6)', '#00e396']

export default function LoadMonitor() {
  const ref = useRef(null)

  useEffect(() => {
    const chart = echarts.init(ref.current, null, { devicePixelRatio: 2 })
    chart.setOption({
      grid: { left: 40, right: 16, top: 8, bottom: 24 },
      xAxis: {
        type: 'category', data: dates,
        axisLabel: { color: '#5a7a8a', fontSize: 10 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        axisLabel: { color: '#5a7a8a', fontSize: 10, formatter: v => v + ' MWh' },
      },
      series: [{
        type: 'bar', data: dailyData.map((v, i) => ({ value: v, itemStyle: { color: colors[i], borderRadius: [3, 3, 0, 0] } })),
        barWidth: 22,
      }],
    })
    return () => chart.dispose()
  }, [])

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-header">实时电力负荷 · A公司</div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', marginBottom: 12 }}>
        <span className="kpi-big">10.2</span>
        <span className="kpi-unit">MW</span>
        <span style={{ fontSize: 12, color: 'var(--text3)', marginLeft: 'auto' }}>
          范围 4.3 ~ 17.5 MW · 日均 245.5 MWh
        </span>
      </div>
      <div ref={ref} style={{ width: '100%', height: 'calc(100% - 44px)' }} />
    </div>
  )
}
