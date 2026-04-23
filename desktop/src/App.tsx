import { NavLink, Outlet } from 'react-router-dom'

export default function App() {
  return (
    <div className="flex min-h-screen flex-col">
      <nav className="sticky top-0 z-50 flex items-center gap-6 border-b border-white/10 bg-[#07111b]/90 px-6 py-3 backdrop-blur-sm">
        <span className="font-mono text-xs font-bold uppercase tracking-widest text-emerald-400">NFL Props</span>
        <div className="flex gap-4">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `text-sm font-medium transition-colors ${isActive ? 'text-slate-50' : 'text-slate-400 hover:text-slate-200'}`
            }
          >
            Dashboard
          </NavLink>
          <NavLink
            to="/parlays"
            className={({ isActive }) =>
              `text-sm font-medium transition-colors ${isActive ? 'text-slate-50' : 'text-slate-400 hover:text-slate-200'}`
            }
          >
            Parlay Builder
          </NavLink>
        </div>
      </nav>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}
