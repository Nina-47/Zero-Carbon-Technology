import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import PriceBar from './PriceBar.jsx'
import './CenterPanel.css'

function MapPlane() {
  const shape = useMemo(() => {
    const s = new THREE.Shape()
    s.moveTo(-1.2, 1.2)
    s.lineTo(-0.4, 1.5)
    s.lineTo(0.5, 1.3)
    s.lineTo(1.2, 0.8)
    s.lineTo(0.9, 0.0)
    s.lineTo(1.0, -0.6)
    s.lineTo(0.6, -1.0)
    s.lineTo(-0.2, -1.2)
    s.lineTo(-0.8, -1.0)
    s.lineTo(-1.5, -0.4)
    s.lineTo(-1.6, 0.3)
    s.lineTo(-1.2, 1.2)
    return s
  }, [])

  return (
    <mesh position={[0, 0, 0]}>
      <shapeGeometry args={[shape]} />
      <meshBasicMaterial color="#00e396" transparent opacity={0.08} side={THREE.DoubleSide} />
    </mesh>
  )
}

function GridLines() {
  const lines = useMemo(() => {
    const pts = []
    for (let i = -1.5; i <= 1.5; i += 0.3) {
      pts.push(new THREE.Vector3(i, -1.5, 0), new THREE.Vector3(i, 1.5, 0))
      pts.push(new THREE.Vector3(-1.5, i, 0), new THREE.Vector3(1.5, i, 0))
    }
    return new THREE.BufferGeometry().setFromPoints(pts)
  }, [])

  return (
    <lineSegments geometry={lines}>
      <lineBasicMaterial color="#00e396" transparent opacity={0.04} />
    </lineSegments>
  )
}

function CityDot({ x, y, name, isMain }) {
  const ref = useRef()
  useFrame(({ clock }) => {
    if (isMain && ref.current) {
      const s = 1 + Math.sin(clock.elapsedTime * 2) * 0.3
      ref.current.scale.setScalar(s)
    }
  })

  const color = isMain ? '#00e396' : '#00e396'
  const size = isMain ? 0.06 : 0.03

  return (
    <group>
      <mesh ref={isMain ? ref : null} position={[x, y, 0.01]}>
        <circleGeometry args={[size, 32]} />
        <meshBasicMaterial color={color} />
      </mesh>
      {isMain && (
        <mesh position={[x, y, 0.01]}>
          <ringGeometry args={[size * 1.6, size * 2, 32]} />
          <meshBasicMaterial color="#00e396" transparent opacity={0.25} />
        </mesh>
      )}
    </group>
  )
}

function Scene() {
  const cities = [
    { x: -0.3, y: 0.3, name: '广州' },
    { x: 0.1, y: -0.3, name: '深圳' },
    { x: -0.4, y: 1.0, name: '韶关' },
    { x: -1.2, y: -0.4, name: '湛江' },
    { x: 1.0, y: 0.2, name: '汕头' },
  ]

  return (
    <>
      <GridLines />
      <MapPlane />
      {cities.map((c, i) => (
        <CityDot key={i} x={c.x} y={c.y} name={c.name} isMain={false} />
      ))}
      <CityDot x={-0.6} y={-0.1} name="中山市" isMain />
    </>
  )
}

export default function CenterPanel() {
  return (
    <div className="center-panel">
      <div className="panel map-panel">
        <div className="panel-header">广东省 · 数字孪生地图</div>
        <Canvas camera={{ position: [0, 0, 2.5], fov: 45 }} style={{ width: '100%', height: '100%', position: 'absolute', inset: 0 }}>
          <Scene />
          <OrbitControls enableZoom={false} enablePan={false} enableRotate={false} />
        </Canvas>
      </div>
      <PriceBar />
    </div>
  )
}
