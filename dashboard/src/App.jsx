import TopBar from './components/TopBar.jsx'
import LeftPanel from './components/LeftPanel.jsx'
import CenterPanel from './components/CenterPanel.jsx'
import RightPanel from './components/RightPanel.jsx'
import './App.css'

export default function App() {
  return (
    <>
      <TopBar />
      <div className="main">
        <LeftPanel />
        <CenterPanel />
        <RightPanel />
      </div>
    </>
  )
}
