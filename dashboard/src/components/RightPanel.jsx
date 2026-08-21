import LoadMonitor from './LoadMonitor.jsx'
import LoadForecast from './LoadForecast.jsx'
import KPICards from './KPICards.jsx'
import './RightPanel.css'

export default function RightPanel() {
  return (
    <div className="right-panel">
      <LoadMonitor />
      <LoadForecast />
      <KPICards />
    </div>
  )
}
