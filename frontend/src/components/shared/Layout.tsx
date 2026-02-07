import { Outlet, NavLink } from 'react-router-dom'
import { MessageSquare, FolderOpen, Database } from 'lucide-react'
import clsx from 'clsx'

export default function Layout() {
  const navItems = [
    { to: '/', icon: MessageSquare, label: 'Chat' },
    { to: '/collections', icon: FolderOpen, label: 'Collections' },
    { to: '/databases', icon: Database, label: 'Databases' },
  ]

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="w-16 bg-gray-900 flex flex-col items-center py-4">
        <div className="text-white font-bold text-xl mb-8">DA</div>
        <nav className="flex flex-col gap-2">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                clsx(
                  'p-3 rounded-lg transition-colors',
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                )
              }
              title={label}
            >
              <Icon size={24} />
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}
