import {
  Activity,
  Bell,
  Cpu,
  Flame,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  Map as MapIcon,
  MonitorPlay,
  Radar,
  Radio,
  ShieldCheck,
  Video,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  hint?: string
}

export const navItems: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, hint: 'System status and demo banner' },
  { to: '/replay', label: 'Detection Replay', icon: MonitorPlay, hint: 'Run frames or play local video' },
  { to: '/live', label: 'Live Sources', icon: Radio, hint: 'RTSP and local test sources' },
  { to: '/alerts', label: 'Alerts', icon: Bell, hint: 'Experimental detection alerts' },
  { to: '/map', label: 'Geolocation Map', icon: MapIcon, hint: 'Cameras, rays and triangulation' },
  { to: '/incidents', label: 'Incidents', icon: Flame, hint: 'Candidates and review workflow' },
  { to: '/cameras', label: 'Cameras', icon: Video, hint: 'Fixed-camera configuration' },
  { to: '/evaluation', label: 'Evaluation', icon: Gauge, hint: 'Honest metrics on synthetic fixtures' },
  { to: '/models', label: 'Models & VLM', icon: Cpu, hint: 'Detector and vision-language setup' },
  { to: '/datasets', label: 'Datasets', icon: FlaskConical, hint: 'Registered sequences and imports' },
  { to: '/status', label: 'System', icon: Activity, hint: 'Runtime configuration' },
]

export const icons = { Radar, ShieldCheck }
