import { useState, useEffect } from 'react'
import './TopBar.css'

export default function TopBar() {
  const [time, setTime] = useState('')

  useEffect(() => {
    const tick = () => setTime(new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="topbar">
      <div className="title">
        <span className="title-dot" />
        零碳虚拟电厂智能调度大屏
      </div>
      <div className="topbar-right">
        <span>📡 数据源 <span className="status-dot ok" /> Open-Meteo 正常</span>
        <span>🔄 刷新 30s</span>
        <span>{time}</span>
      </div>
    </div>
  )
}
