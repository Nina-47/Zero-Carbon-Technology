import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'

const profile = [8.9, 8.1, 8.2, 7.5, 7.8, 7.9, 7.9, 8.7, 10.1, 10.1, 11.7, 12.7, 13.9, 14.8, 14.1, 14.5, 14.4, 14.8, 14.8, 14.5, 13.3, 7.9, 8.2, 7.7]
const hours = ['00h', '01h', '02h', '03h', '04h', '05h', '06h', '07h', '08h', '09h', '10h', '11h', '12h', '13h', '14h', '15h', '16h', '17h', '18h', '19h', '20h', '21h', '22h', '23h']
const upper = profile.map(v => v * 1.08)
const lower = profile.map(v => Math.max(v * 0.92, 0))

export default function LoadForecast() {
  const ref = useRef(null)

  useEffect(() => {
    const chart = echarts.init(ref.current, null, { devicePixelRatio: 2 })
    chart.setOption({
      grid: { left: 40, right: 16, top: 8, bottom: 24 },
      xAxis: {
        type: 'category', data: hours,
        axisLabel: { color: '#5a7a8a', fontSize: 9, interval: 3 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
        axisLabel: { color: '#5a7a8a', fontSize: 10, formatter: v => v + ' MW' },
      },
      series: [
        {
          type: 'line', data: upper,
          lineStyle: { opacity: 0 }, itemStyle: { opacity: 0 },
          areaStyle: { color: 'rgba(0,227,150,0.06)' },
          stack: 'confidence', symbol: 'none',
        },
        {
          type: 'line', data: lower,
          lineStyle: { opacity: 0 }, itemStyle: { opacity: 0 },
          areaStyle: { color: 'rgba(0,10,28,0.6)' },
          stack: 'confidence', symbol: 'none',
        },
        {
          type: 'line', data: profile,
          smooth: true, symbol: 'circle', symbolSize: 3,
          lineStyle: { color: '#00e396', width: 2 },
          itemStyle: { color: '#00e396' },
          markPoint: {
            data: [
              { type: 'max', name: '峰值', symbolSize: 8, itemStyle: { color: '#f2a23a' } },
              { type: 'min', name: '谷值', symbolSize: 8, itemStyle: { color: '#00b4d8' } },
            ],
            label: { color: '#e2e8f0', fontSize: 10 },
          },
        },
      ],
    })
    return () => chart.dispose()
  }, [])

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-header">24h 负荷预测曲线 · 典型工作日</div>
      <div ref={ref} style={{ width: '100%', height: 'calc(100% - 28px)' }} />
    </div>
  )
}
