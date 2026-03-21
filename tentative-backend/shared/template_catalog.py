"""
template_catalog.py
-------------------
Static seed catalog of reusable frontend code templates.
Seeded into Cosmos DB TemplateLibrary container on startup.
The frontend agent queries these before generating code.
"""

from datetime import datetime, timezone

_NOW = datetime.now(timezone.utc).isoformat()

TEMPLATE_CATALOG = [
    {
        "id":           "navbar-responsive-v1",
        "template_id":  "navbar-responsive-v1",
        "type":         "template_catalog_entry",
        "name":         "Responsive Navbar",
        "category":     "navigation",
        "framework":    "react",
        "tags":         ["navbar", "responsive", "tailwind", "mobile"],
        "description":  "Responsive navbar with mobile hamburger menu, logo slot, and nav links. Collapses to hamburger on small screens.",
        "dependencies": ["react", "tailwind"],
        "usage_count":  0,
        "created_by":   "system",
        "custom":       False,
        "created_at":   _NOW,
        "code": """\
import { useState } from 'react'

export default function Navbar({ logo = 'App', links = [] }) {
  const [open, setOpen] = useState(false)
  return (
    <nav className="bg-white border-b border-gray-200 px-4 py-3">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <span className="text-xl font-bold text-gray-900">{logo}</span>
        <button className="md:hidden p-2" onClick={() => setOpen(o => !o)}>
          <span className="block w-6 h-0.5 bg-gray-700 mb-1" />
          <span className="block w-6 h-0.5 bg-gray-700 mb-1" />
          <span className="block w-6 h-0.5 bg-gray-700" />
        </button>
        <ul className={`flex-col md:flex md:flex-row gap-6 absolute md:static top-16 left-0 w-full md:w-auto bg-white md:bg-transparent p-4 md:p-0 border-b md:border-0 ${open ? 'flex' : 'hidden'}`}>
          {links.map(l => (
            <li key={l.href}>
              <a href={l.href} className="text-gray-600 hover:text-gray-900 text-sm font-medium">{l.label}</a>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  )
}
""",
    },
    {
        "id":           "auth-form-v1",
        "template_id":  "auth-form-v1",
        "type":         "template_catalog_entry",
        "name":         "Login / Signup Form",
        "category":     "authentication",
        "framework":    "react",
        "tags":         ["auth", "login", "signup", "form", "validation"],
        "description":  "Login and signup form with email/password fields, validation, and toggle between modes.",
        "dependencies": ["react", "tailwind"],
        "usage_count":  0,
        "created_by":   "system",
        "custom":       False,
        "created_at":   _NOW,
        "code": """\
import { useState } from 'react'

export default function AuthForm({ onSubmit }) {
  const [mode, setMode]     = useState('login')
  const [email, setEmail]   = useState('')
  const [pass, setPass]     = useState('')
  const [error, setError]   = useState('')

  const handle = async e => {
    e.preventDefault()
    if (!email || !pass) { setError('All fields required'); return }
    setError('')
    await onSubmit?.({ mode, email, password: pass })
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={handle} className="bg-white p-8 rounded-2xl shadow w-full max-w-sm space-y-4">
        <h2 className="text-2xl font-bold text-gray-900">{mode === 'login' ? 'Sign in' : 'Create account'}</h2>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <input type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)}
          className="w-full border rounded-xl px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
        <input type="password" placeholder="Password" value={pass} onChange={e => setPass(e.target.value)}
          className="w-full border rounded-xl px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
        <button type="submit" className="w-full bg-blue-600 text-white rounded-xl py-2 text-sm font-semibold hover:bg-blue-700">
          {mode === 'login' ? 'Sign in' : 'Sign up'}
        </button>
        <p className="text-sm text-center text-gray-500">
          {mode === 'login' ? "Don't have an account?" : 'Already have an account?'}
          <button type="button" onClick={() => setMode(m => m === 'login' ? 'signup' : 'login')}
            className="ml-1 text-blue-600 font-medium hover:underline">
            {mode === 'login' ? 'Sign up' : 'Sign in'}
          </button>
        </p>
      </form>
    </div>
  )
}
""",
    },
    {
        "id":           "dashboard-layout-v1",
        "template_id":  "dashboard-layout-v1",
        "type":         "template_catalog_entry",
        "name":         "Dashboard Layout",
        "category":     "layout",
        "framework":    "react",
        "tags":         ["dashboard", "layout", "sidebar", "admin"],
        "description":  "Full dashboard layout with collapsible sidebar, header with user avatar, and main content area.",
        "dependencies": ["react", "tailwind"],
        "usage_count":  0,
        "created_by":   "system",
        "custom":       False,
        "created_at":   _NOW,
        "code": """\
import { useState } from 'react'

export default function DashboardLayout({ children, navItems = [], user = {} }) {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <div className="flex h-screen bg-gray-100">
      {/* Sidebar */}
      <aside className={`${collapsed ? 'w-16' : 'w-64'} bg-white border-r flex flex-col transition-all duration-200`}>
        <div className="flex items-center justify-between p-4 border-b">
          {!collapsed && <span className="font-bold text-gray-900">Menu</span>}
          <button onClick={() => setCollapsed(c => !c)} className="p-1 rounded hover:bg-gray-100">
            <svg className="h-5 w-5 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M4 12h16M4 18h16"/>
            </svg>
          </button>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {navItems.map(item => (
            <a key={item.href} href={item.href}
              className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-gray-100">
              {item.icon && <span>{item.icon}</span>}
              {!collapsed && <span>{item.label}</span>}
            </a>
          ))}
        </nav>
      </aside>
      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="bg-white border-b px-6 py-3 flex items-center justify-between">
          <h1 className="text-lg font-semibold text-gray-900">Dashboard</h1>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">{user.name || 'User'}</span>
            <div className="h-8 w-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-sm font-bold">
              {(user.name || 'U')[0].toUpperCase()}
            </div>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </div>
    </div>
  )
}
""",
    },
    {
        "id":           "data-table-v1",
        "template_id":  "data-table-v1",
        "type":         "template_catalog_entry",
        "name":         "Data Table",
        "category":     "data-display",
        "framework":    "react",
        "tags":         ["table", "data", "sortable", "pagination"],
        "description":  "Sortable data table with pagination, loading state, and empty state.",
        "dependencies": ["react", "tailwind"],
        "usage_count":  0,
        "created_by":   "system",
        "custom":       False,
        "created_at":   _NOW,
        "code": """\
import { useState } from 'react'

export default function DataTable({ columns = [], rows = [], loading = false }) {
  const [page, setPage]   = useState(1)
  const [sort, setSort]   = useState({ key: null, dir: 'asc' })
  const perPage = 10

  const sorted = [...rows].sort((a, b) => {
    if (!sort.key) return 0
    const v = a[sort.key] < b[sort.key] ? -1 : 1
    return sort.dir === 'asc' ? v : -v
  })
  const paged    = sorted.slice((page - 1) * perPage, page * perPage)
  const maxPages = Math.ceil(rows.length / perPage)

  const toggleSort = key => setSort(s => ({ key, dir: s.key === key && s.dir === 'asc' ? 'desc' : 'asc' }))

  if (loading) return <div className="text-center py-12 text-gray-400">Loading…</div>
  if (!rows.length) return <div className="text-center py-12 text-gray-400">No data found.</div>

  return (
    <div className="bg-white rounded-2xl border overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b">
          <tr>
            {columns.map(col => (
              <th key={col.key} onClick={() => toggleSort(col.key)}
                className="px-4 py-3 text-left font-semibold text-gray-600 cursor-pointer hover:text-gray-900 select-none">
                {col.label} {sort.key === col.key ? (sort.dir === 'asc' ? '↑' : '↓') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {paged.map((row, i) => (
            <tr key={i} className="hover:bg-gray-50">
              {columns.map(col => (
                <td key={col.key} className="px-4 py-3 text-gray-700">{row[col.key] ?? '—'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {maxPages > 1 && (
        <div className="px-4 py-3 border-t flex items-center justify-between text-sm text-gray-500">
          <span>Page {page} of {maxPages}</span>
          <div className="flex gap-2">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
              className="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-50">Prev</button>
            <button onClick={() => setPage(p => Math.min(maxPages, p + 1))} disabled={page === maxPages}
              className="px-3 py-1 rounded border disabled:opacity-40 hover:bg-gray-50">Next</button>
          </div>
        </div>
      )}
    </div>
  )
}
""",
    },
    {
        "id":           "modal-dialog-v1",
        "template_id":  "modal-dialog-v1",
        "type":         "template_catalog_entry",
        "name":         "Modal Dialog",
        "category":     "feedback",
        "framework":    "react",
        "tags":         ["modal", "dialog", "overlay", "confirmation"],
        "description":  "Accessible modal dialog with backdrop, title, body slot, and confirm/cancel actions.",
        "dependencies": ["react", "tailwind"],
        "usage_count":  0,
        "created_by":   "system",
        "custom":       False,
        "created_at":   _NOW,
        "code": """\
export default function Modal({ open, onClose, onConfirm, title = 'Confirm', children, confirmLabel = 'Confirm', danger = false }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6">
        <h2 className="text-lg font-bold text-gray-900 mb-3">{title}</h2>
        <div className="text-sm text-gray-600 mb-6">{children}</div>
        <div className="flex gap-3 justify-end">
          <button onClick={onClose}
            className="px-4 py-2 rounded-xl border text-sm font-medium text-gray-700 hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={onConfirm}
            className={`px-4 py-2 rounded-xl text-sm font-semibold text-white ${danger ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
""",
    },
    {
        "id":           "toast-notifications-v1",
        "template_id":  "toast-notifications-v1",
        "type":         "template_catalog_entry",
        "name":         "Toast Notifications",
        "category":     "feedback",
        "framework":    "react",
        "tags":         ["toast", "notification", "alert", "feedback"],
        "description":  "Toast notification system with success, error, warning, and info variants. Auto-dismisses after 3s.",
        "dependencies": ["react", "tailwind"],
        "usage_count":  0,
        "created_by":   "system",
        "custom":       False,
        "created_at":   _NOW,
        "code": """\
import { useState, useCallback } from 'react'

const STYLES = {
  success: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  error:   'bg-red-50 border-red-200 text-red-800',
  warning: 'bg-amber-50 border-amber-200 text-amber-800',
  info:    'bg-blue-50 border-blue-200 text-blue-800',
}

export function useToast() {
  const [toasts, setToasts] = useState([])
  const add = useCallback((message, type = 'info') => {
    const id = Date.now()
    setToasts(t => [...t, { id, message, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3000)
  }, [])
  return { toasts, toast: add }
}

export function ToastContainer({ toasts }) {
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full">
      {toasts.map(t => (
        <div key={t.id} className={`flex items-start gap-2 border rounded-xl px-4 py-3 text-sm shadow-lg animate-fade-in ${STYLES[t.type]}`}>
          <span className="flex-1">{t.message}</span>
        </div>
      ))}
    </div>
  )
}
""",
    },
    {
        "id":           "search-bar-v1",
        "template_id":  "search-bar-v1",
        "type":         "template_catalog_entry",
        "name":         "Search Bar",
        "category":     "input",
        "framework":    "react",
        "tags":         ["search", "input", "filter", "debounce"],
        "description":  "Search bar with debounced input, clear button, and loading indicator.",
        "dependencies": ["react", "tailwind"],
        "usage_count":  0,
        "created_by":   "system",
        "custom":       False,
        "created_at":   _NOW,
        "code": """\
import { useState, useEffect } from 'react'

export default function SearchBar({ onSearch, placeholder = 'Search…', loading = false }) {
  const [value, setValue] = useState('')

  useEffect(() => {
    const t = setTimeout(() => onSearch?.(value), 300)
    return () => clearTimeout(t)
  }, [value])

  return (
    <div className="relative">
      <svg className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
      </svg>
      <input
        value={value}
        onChange={e => setValue(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-xl border border-gray-200 bg-white py-2 pl-9 pr-8 text-sm outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
      />
      {value && (
        <button onClick={() => setValue('')}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">×</button>
      )}
      {loading && (
        <div className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
      )}
    </div>
  )
}
""",
    },
    {
        "id":           "stats-cards-v1",
        "template_id":  "stats-cards-v1",
        "type":         "template_catalog_entry",
        "name":         "Stats Cards",
        "category":     "data-display",
        "framework":    "react",
        "tags":         ["stats", "cards", "metrics", "kpi", "dashboard"],
        "description":  "Row of KPI stat cards with value, label, trend indicator, and icon slot.",
        "dependencies": ["react", "tailwind"],
        "usage_count":  0,
        "created_by":   "system",
        "custom":       False,
        "created_at":   _NOW,
        "code": """\
export default function StatsCards({ stats = [] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {stats.map((s, i) => (
        <div key={i} className="bg-white rounded-2xl border p-5">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">{s.label}</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">{s.value}</p>
            </div>
            {s.icon && <div className="text-2xl">{s.icon}</div>}
          </div>
          {s.trend !== undefined && (
            <p className={`mt-3 text-xs font-medium ${s.trend >= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
              {s.trend >= 0 ? '↑' : '↓'} {Math.abs(s.trend)}% vs last period
            </p>
          )}
        </div>
      ))}
    </div>
  )
}
""",
    },
]
