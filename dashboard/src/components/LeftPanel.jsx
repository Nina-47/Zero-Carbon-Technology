import CarbonEmission from './CarbonEmission.jsx'
import EmissionTrend from './EmissionTrend.jsx'
import CarbonReduction from './CarbonReduction.jsx'
import './LeftPanel.css'

export default function LeftPanel() {
  return (
    <div className="left-panel">
      <CarbonEmission />
      <EmissionTrend />
      <CarbonReduction />
    </div>
  )
}
