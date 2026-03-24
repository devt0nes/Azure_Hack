/**
 * TemplateLibrary.jsx
 * --------------------
 * Full-page Template Library overlay — same pattern as AgentMarketplace.
 * Shows reusable frontend code snippets agents can use.
 *
 * Features:
 *  - Browse templates by category / tag / search
 *  - Click a card to see full code with syntax highlighting
 *  - Copy code to clipboard
 *  - Create custom templates via a form
 *  - Delete custom templates
 */

import { useState, useEffect, useCallback } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

// ── API helpers ──────────────────────────────────────────────────────────────
async function fetchTemplates({ category, framework, tag } = {}) {
  const params = new URLSearchParams()
  if (category)  params.set('category',  category)
  if (framework) params.set('framework', framework)
  if (tag)       params.set('tag',       tag)
  const qs  = params.toString()
  const res = await fetch(`${API_BASE}/api/templates${qs ? '?' + qs : ''}`)
  if (!res.ok) throw new Error('Failed to fetch templates')
  return res.json()
}

async function fetchTemplate(templateId) {
  const res = await fetch(`${API_BASE}/api/templates/${templateId}`)
  if (!res.ok) throw new Error('Template not found')
  return res.json()
}

async function fetchCategories() {
  const res = await fetch(`${API_BASE}/api/templates/categories`)
  if (!res.ok) return { categories: [], tags: [] }
  return res.json()
}

async function createTemplate(body) {
  const res = await fetch(`${API_BASE}/api/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to create template')
  }
  return res.json()
}

async function deleteTemplate(templateId) {
  const res = await fetch(`${API_BASE}/api/templates/${templateId}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to delete template')
  }
  return res.json()
}

// ── Category colours ─────────────────────────────────────────────────────────
const CATEGORY_STYLES = {
  navigation:   'bg-sky-100    text-sky-700    border-sky-200',
  layout:       'bg-violet-100 text-violet-700 border-violet-200',
  authentication: 'bg-red-100  text-red-700    border-red-200',
  'data-display': 'bg-teal-100 text-teal-700   border-teal-200',
  input:        'bg-amber-100  text-amber-700  border-amber-200',
  feedback:     'bg-emerald-100 text-emerald-700 border-emerald-200',
}
function categoryStyle(cat) {
  return CATEGORY_STYLES[cat] || 'bg-ink/8 text-ink/60 border-ink/10'
}

// ── Code viewer modal ────────────────────────────────────────────────────────
function CodeModal({ templateId, onClose }) {
  const [template, setTemplate] = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [copied,   setCopied]   = useState(false)

  useEffect(() => {
    fetchTemplate(templateId)
      .then(setTemplate)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [templateId])

  const copy = () => {
    if (!template?.code) return
    navigator.clipboard.writeText(template.code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-6">
      <div className="absolute inset-0 bg-midnight/30 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-3xl rounded-3xl border border-white/30 bg-gradient-to-br from-white/95 via-white/90 to-white/85 shadow-2xl backdrop-blur-md flex flex-col max-h-[85vh]">

        {/* Header */}
        <div className="flex items-center justify-between border-b border-ink/8 px-6 py-4 flex-shrink-0">
          <div>
            <h2 className="text-lg font-bold bg-gradient-to-r from-midnight to-ink/70 bg-clip-text text-transparent">
              {loading ? 'Loading…' : template?.name}
            </h2>
            {template && (
              <p className="text-xs text-ink/40 mt-0.5">{template.description}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={copy}
              className="flex items-center gap-1.5 rounded-xl border border-white/50 bg-white/70 px-3 py-2 text-xs font-semibold text-ink/70 hover:bg-white transition"
            >
              {copied ? (
                <><svg className="h-3.5 w-3.5 text-emerald-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M20 6L9 17l-5-5"/></svg> Copied!</>
              ) : (
                <><svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy code</>
              )}
            </button>
            <button onClick={onClose} className="rounded-lg bg-ink/5 px-3 py-2 text-xs font-medium text-ink/60 hover:bg-ink/10 transition">Close</button>
          </div>
        </div>

        {/* Code */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-8 w-8 rounded-full border-2 border-ember/30 border-t-ember animate-spin" />
            </div>
          ) : template?.code ? (
            <>
              {/* Meta pills */}
              <div className="flex flex-wrap gap-2 mb-4">
                <span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold ${categoryStyle(template.category)}`}>
                  {template.category}
                </span>
                <span className="rounded-full border border-ink/10 bg-ink/5 px-2.5 py-1 text-[10px] font-medium text-ink/50">
                  {template.framework}
                </span>
                {template.tags?.map(t => (
                  <span key={t} className="rounded-full border border-ink/8 bg-white/60 px-2 py-0.5 text-[10px] text-ink/40">#{t}</span>
                ))}
                {template.usage_count > 0 && (
                  <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-medium text-emerald-600">
                    Used {template.usage_count}×
                  </span>
                )}
              </div>

              {/* Code block */}
              <pre className="rounded-2xl bg-midnight/95 p-5 overflow-x-auto text-[11px] leading-relaxed text-emerald-300 font-mono whitespace-pre-wrap">
                <code>{template.code}</code>
              </pre>

              {/* Dependencies */}
              {template.dependencies?.length > 0 && (
                <div className="mt-4 rounded-xl border border-white/50 bg-white/60 px-4 py-3">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-ink/40 mb-2">Dependencies</p>
                  <div className="flex flex-wrap gap-1.5">
                    {template.dependencies.map(d => (
                      <span key={d} className="rounded-lg border border-ink/10 bg-ink/5 px-2 py-1 text-[11px] font-mono text-ink/60">{d}</span>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-ink/40 text-center py-8">No code available</p>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Create Template Modal ────────────────────────────────────────────────────
function CreateModal({ onClose, onCreated }) {
  const [form, setForm] = useState({
    name: '', category: 'layout', framework: 'react',
    description: '', code: '', tags: '', dependencies: '',
  })
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState(null)

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))

  const handle = async () => {
    if (!form.name || !form.description || !form.code) {
      setError('Name, description and code are required.'); return
    }
    setSaving(true); setError(null)
    try {
      const data = await createTemplate({
        ...form,
        tags:         form.tags.split(',').map(t => t.trim()).filter(Boolean),
        dependencies: form.dependencies.split(',').map(d => d.trim()).filter(Boolean),
      })
      onCreated(data.template)
      onClose()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const inputCls = "w-full rounded-xl border border-white/50 bg-white/80 px-3 py-2 text-xs text-ink placeholder-ink/30 outline-none focus:border-ember/30 focus:ring-1 focus:ring-ember/20 transition"

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-6">
      <div className="absolute inset-0 bg-midnight/30 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-xl rounded-3xl border border-white/30 bg-gradient-to-br from-white/95 via-white/90 to-white/85 shadow-2xl flex flex-col max-h-[90vh]">

        <div className="flex items-center justify-between border-b border-ink/8 px-6 py-4 flex-shrink-0">
          <div>
            <h2 className="text-lg font-bold bg-gradient-to-r from-midnight to-ink/70 bg-clip-text text-transparent">Create Template</h2>
            <p className="text-xs text-ink/40 mt-0.5">Add a reusable component to the library</p>
          </div>
          <button onClick={onClose} className="rounded-lg bg-ink/5 px-3 py-1.5 text-xs font-medium text-ink/60 hover:bg-ink/10">Cancel</button>
        </div>

        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-widest text-ink/40 mb-1">Name *</label>
              <input className={inputCls} placeholder="e.g. Product Card" value={form.name} onChange={e => set('name', e.target.value)} />
            </div>
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-widest text-ink/40 mb-1">Category</label>
              <select className={inputCls} value={form.category} onChange={e => set('category', e.target.value)}>
                {['navigation','layout','authentication','data-display','input','feedback','other'].map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest text-ink/40 mb-1">Description *</label>
            <input className={inputCls} placeholder="What does this component do?" value={form.description} onChange={e => set('description', e.target.value)} />
          </div>

          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest text-ink/40 mb-1">Code *</label>
            <textarea
              className={`${inputCls} resize-none font-mono text-[11px]`} rows={8}
              placeholder={"export default function MyComponent() {\n  return <div>Hello</div>\n}"}
              value={form.code} onChange={e => set('code', e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-widest text-ink/40 mb-1">Tags (comma-separated)</label>
              <input className={inputCls} placeholder="card, product, ecommerce" value={form.tags} onChange={e => set('tags', e.target.value)} />
            </div>
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-widest text-ink/40 mb-1">Dependencies (comma-separated)</label>
              <input className={inputCls} placeholder="react, tailwind" value={form.dependencies} onChange={e => set('dependencies', e.target.value)} />
            </div>
          </div>

          {error && <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}
        </div>

        <div className="border-t border-ink/8 px-6 py-4 flex items-center justify-end gap-3 flex-shrink-0">
          <button onClick={onClose} className="rounded-xl border border-ink/10 px-4 py-2 text-xs font-semibold text-ink/60 hover:bg-ink/5">Cancel</button>
          <button onClick={handle} disabled={saving}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-ember to-orange-400 px-5 py-2 text-xs font-bold text-white shadow-sm hover:opacity-90 disabled:opacity-50">
            {saving ? (
              <><svg className="h-3.5 w-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Saving…</>
            ) : (
              <><svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 5v14M5 12h14"/></svg> Create Template</>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Template Card ────────────────────────────────────────────────────────────
function TemplateCard({ template, onView, onDelete }) {
  const [deleting, setDeleting] = useState(false)

  const handleDelete = async e => {
    e.stopPropagation()
    if (!confirm(`Delete "${template.name}"?`)) return
    setDeleting(true)
    try {
      await onDelete(template.template_id)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div
      onClick={() => onView(template.template_id)}
      className="group flex flex-col rounded-2xl border border-white/50 bg-white/75 hover:border-white/80 hover:bg-white/95 hover:shadow-lg transition-all duration-200 cursor-pointer overflow-hidden"
    >
      {/* Card body */}
      <div className="flex flex-col gap-3 p-5 flex-1">
        {/* Category + custom badge */}
        <div className="flex items-center justify-between gap-2">
          <span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold ${categoryStyle(template.category)}`}>
            {template.category}
          </span>
          <div className="flex items-center gap-1.5">
            {template.custom && (
              <span className="rounded-full border border-ember/25 bg-ember/8 px-2 py-0.5 text-[10px] font-bold text-ember">custom</span>
            )}
            <span className="rounded-full border border-ink/10 bg-ink/5 px-2 py-0.5 text-[10px] text-ink/40">{template.framework}</span>
          </div>
        </div>

        {/* Name */}
        <h3 className="text-sm font-bold text-midnight leading-tight">{template.name}</h3>

        {/* Description */}
        <p className="text-xs leading-relaxed text-ink/60 flex-1">
          {template.description?.length > 100 ? template.description.slice(0, 100) + '…' : template.description}
        </p>

        {/* Tags */}
        {template.tags?.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {template.tags.slice(0, 4).map(t => (
              <span key={t} className="rounded-full border border-ink/8 bg-white/60 px-2 py-0.5 text-[10px] text-ink/40">#{t}</span>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-ink/8 px-5 py-3 flex items-center justify-between gap-2">
        <span className="text-[11px] text-ink/30">
          {template.usage_count > 0 ? `Used ${template.usage_count}×` : 'Not used yet'}
        </span>
        <div className="flex items-center gap-2">
          {template.custom && (
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-[10px] font-medium text-red-500 hover:bg-red-100 transition disabled:opacity-50"
            >
              {deleting ? '…' : 'Delete'}
            </button>
          )}
          <button className="flex items-center gap-1 rounded-xl bg-gradient-to-r from-ember to-orange-400 px-3 py-1.5 text-[11px] font-bold text-white shadow-sm hover:opacity-90 transition">
            <svg className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
            View
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function TemplateLibrary({ onBack }) {
  const [templates,    setTemplates]    = useState([])
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState(null)
  const [search,       setSearch]       = useState('')
  const [category,     setCategory]     = useState('all')
  const [activeTag,    setActiveTag]    = useState(null)
  const [allCategories,setAllCategories]= useState([])
  const [allTags,      setAllTags]      = useState([])
  const [viewingId,    setViewingId]    = useState(null)
  const [showCreate,   setShowCreate]   = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [data, cats] = await Promise.all([fetchTemplates(), fetchCategories()])
      setTemplates(data.templates || [])
      setAllCategories(cats.categories || [])
      setAllTags(cats.tags || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleDelete = useCallback(async (id) => {
    await deleteTemplate(id)
    setTemplates(prev => prev.filter(t => t.template_id !== id))
  }, [])

  const handleCreated = useCallback((template) => {
    setTemplates(prev => [template, ...prev])
  }, [])

  const filtered = templates.filter(t => {
    const matchCat    = category === 'all' || t.category === category
    const matchSearch = !search  || t.name.toLowerCase().includes(search.toLowerCase()) || t.description?.toLowerCase().includes(search.toLowerCase())
    const matchTag    = !activeTag || (t.tags || []).includes(activeTag)
    return matchCat && matchSearch && matchTag
  })

  return (
    <div className="fixed inset-0 z-[100] overflow-hidden bg-gradient-to-br from-sand via-white to-haze flex flex-col">

      {/* Background */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(242,106,46,0.12),_transparent_55%)]" />
        <div className="absolute -right-32 top-0 h-96 w-96 rounded-full bg-gradient-to-br from-ember/10 via-orange-400/8 to-transparent blur-3xl" />
        <div className="absolute -left-32 bottom-0 h-80 w-80 rounded-full bg-gradient-to-tr from-violet-500/8 to-transparent blur-3xl" />
      </div>

      {/* Header */}
      <header className="relative z-10 flex-shrink-0 animate-fade-in px-6 pt-4">
        <div className="rounded-3xl border border-white/30 bg-gradient-to-br from-white/80 via-white/65 to-white/50 p-4 shadow-glass backdrop-blur-md">
          <div className="flex flex-wrap items-start justify-between gap-4">

            <div className="min-w-[280px] flex-1 flex items-start gap-4">
              <button
                onClick={onBack}
                className="mt-1 flex items-center gap-2 rounded-xl border border-white/50 bg-white/70 px-3 py-2 text-xs font-semibold text-ink/70 hover:bg-white transition shadow-sm flex-shrink-0"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
                Back
              </button>
              <div>
                <p className="mono text-xs uppercase tracking-[0.35em] bg-gradient-to-r from-ember to-orange-400 bg-clip-text text-transparent font-bold">PLATFORM A</p>
                <h1 className="mt-1 text-3xl md:text-4xl font-bold bg-gradient-to-r from-midnight via-ink to-midnight bg-clip-text text-transparent leading-tight">Template Library</h1>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink/70">
                  <span className="inline-flex items-center rounded-full border border-white/30 bg-white/70 px-2.5 py-1">
                    Reusable frontend components for agents
                  </span>
                  <span className="inline-flex items-center rounded-full border border-white/30 bg-white/70 px-2.5 py-1">
                    Templates: <span className="mono ml-1 font-semibold text-ink">{templates.length}</span>
                  </span>
                </div>
              </div>
            </div>

            <div className="flex items-start gap-3 pt-1">
              {/* Search */}
              <div className="relative w-56">
                <svg className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink/30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                </svg>
                <input
                  type="text" placeholder="Search templates…" value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="w-full rounded-xl border border-white/50 bg-white/80 py-2 pl-8 pr-3 text-xs text-ink placeholder-ink/30 outline-none focus:border-ember/30 focus:ring-1 focus:ring-ember/20 transition shadow-sm"
                />
              </div>
              {/* Create button */}
              <button
                onClick={() => setShowCreate(true)}
                className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-ember to-orange-400 px-4 py-2 text-xs font-bold text-white shadow-sm hover:opacity-90 transition"
              >
                <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 5v14M5 12h14"/></svg>
                Create Template
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Filter bar */}
      <div className="relative z-10 flex-shrink-0 px-6 py-3">
        <div className="flex items-center gap-3 flex-wrap">

          {/* Category dropdown */}
          <div className="relative">
            <select value={category} onChange={e => setCategory(e.target.value)}
              className="appearance-none rounded-xl border border-white/50 bg-white/80 py-2 pl-3 pr-8 text-xs font-semibold text-ink shadow-sm outline-none focus:border-ember/30 cursor-pointer backdrop-blur-sm">
              <option value="all">All Categories</option>
              {allCategories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <svg className="pointer-events-none absolute right-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M6 9l6 6 6-6"/></svg>
          </div>

          {/* Tag pills */}
          {allTags.slice(0, 12).map(tag => (
            <button key={tag} onClick={() => setActiveTag(activeTag === tag ? null : tag)}
              className={`rounded-full border px-2.5 py-1 text-[10px] font-medium transition-all ${
                activeTag === tag
                  ? 'border-ember/30 bg-ember/10 text-ember'
                  : 'border-ink/10 bg-white/60 text-ink/50 hover:border-ink/20'
              }`}>
              #{tag}
            </button>
          ))}

          {(category !== 'all' || activeTag || search) && (
            <button onClick={() => { setCategory('all'); setActiveTag(null); setSearch('') }}
              className="ml-auto text-[11px] font-medium text-ember hover:underline">
              Clear filters
            </button>
          )}

          <span className="ml-auto text-[11px] font-medium uppercase tracking-widest text-ink/30">
            {filtered.length} template{filtered.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {/* Grid */}
      <div className="relative z-10 flex-1 overflow-y-auto px-6 pb-6">
        {loading && (
          <div className="flex flex-col items-center justify-center gap-4 py-24">
            <div className="h-10 w-10 rounded-full border-2 border-ember/30 border-t-ember animate-spin" />
            <p className="text-sm font-medium text-ink/40">Loading templates…</p>
          </div>
        )}

        {error && (
          <div className="mx-auto max-w-md rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
            <p className="text-sm font-semibold text-red-600">Could not load templates</p>
            <p className="mt-1 text-xs text-red-500">{error}</p>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-3 py-24">
            <p className="text-sm font-semibold text-ink/40">No templates match your filters</p>
            <button onClick={() => { setCategory('all'); setActiveTag(null); setSearch('') }}
              className="text-xs font-medium text-ember hover:underline">Clear filters</button>
          </div>
        )}

        {!loading && !error && filtered.length > 0 && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filtered.map(t => (
              <TemplateCard
                key={t.template_id}
                template={t}
                onView={setViewingId}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>

      {/* Modals */}
      {viewingId && <CodeModal templateId={viewingId} onClose={() => setViewingId(null)} />}
      {showCreate && <CreateModal onClose={() => setShowCreate(false)} onCreated={handleCreated} />}
    </div>
  )
}
