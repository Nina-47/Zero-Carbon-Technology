import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'

export default function EmissionTrend() {
  const ref = useRef(null)

  useEffect(() => {
    const chart = echarts.init(ref.current, null, { devicePixelRatio: 2 })
    chart.setOption({
      grid: { left: 36, right: 16, top: 8, bottom: 24 },
      xAxis: {
        type: 'category',
        data: ['6/23', '6/24', '6/25', '6/26', '6/27', '6/28', '6/29'],
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
        axisLabel: { color: '#5a7a8a', fontSize: 10 },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        axisLabel: { color: '#5a7a8a', fontSize: 10, formatter: v => v + ' t' },
      },
      series: [{
        type: 'line',
        data: [207.7, 215.9, 218.4, 210.9, 176.7, 174.9, 227.4],
        smooth: true,
        lineStyle: { color: '#00e396', width: 2 },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(0,227,150,0.15)' },
          { offset: 1, color: 'rgba(0,227,150,0.01)' },
        ])},
        itemStyle: { color: '#00e396' },
        symbol: 'circle',
        symbolSize: 4,
      }],
    })
    return () => chart.dispose()
  }, [])

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-header">碳排放趋势 — 近7天</div>
      <div ref={ref} style={{ width: '100%', height: 'calc(100% - 28px)' }} />
    </div>
  )
}
