import { NavLink, Outlet } from 'react-router-dom'

const NAV = [
  { to: '/', label: 'This Week', end: true },
  { to: '/props', label: 'Props', end: false },
  { to: '/parlays', label: 'Parlays', end: false },
  { to: '/execution', label: 'Trading (Paper)', end: false },
]

export default function App() {
  return (
    <div className="flex min-h-screen flex-col">
      <nav className="sticky top-0 z-50 flex items-center gap-6 border-b border-white/10 bg-[#07111b]/90 px-6 py-3 backdrop-blur-sm">
        <span className="font-mono text-xs font-bold uppercase tracking-widest text-emerald-400">
          NFL Fantasy
        </span>
        <div className="flex gap-4">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `text-sm font-medium transition-colors ${
                  isActive ? 'text-slate-50' : 'text-slate-400 hover:text-slate-200'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
