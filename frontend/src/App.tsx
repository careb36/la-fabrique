import { useEffect, useRef, useState } from 'react'
import { BrowserRouter, Routes, Route, Link, Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { useAppStore } from './store/useAppStore'
import { useAuthStore } from './store/useAuthStore'
import { api, setOnUnauthorized } from './services/api'
import ProtectedRoute from './components/ProtectedRoute'
import AgentSettings from './pages/AgentSettings'
import Sprints from './pages/Sprints'
import CompanyNew from './pages/CompanyNew'
import CompanySelect from './pages/CompanySelect'
import Login from './pages/Login'
import Register from './pages/Register'
import { SprintWorkspace, sprintPath, type SprintTab } from './pages/SprintWorkspace'
import { GovernancePanel } from './components/GovernancePanel'
import { QuotaPanel } from './components/QuotaPanel'
import { SupportBot } from './components/SupportBot'
import MemorySearch from './pages/MemorySearch'
import Evidence from './pages/Evidence'
import EvidenceDetail from './pages/EvidenceDetail'
import Generate from './pages/Generate'
import NotFound from './pages/NotFound'
import TaskDetails from './pages/TaskDetails'
import CompanyMembers from './pages/CompanyMembers'
import GitHubIntegration from './pages/GitHubIntegration'
import HelpDesk from './pages/HelpDesk'
import Lineage from './pages/Lineage'
import Procedures from './pages/Procedures'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ToastContainer } from './components/Toast'
import {
  LayoutDashboard, ShieldCheck, ClipboardCheck,
  Globe, Database, Code2, Menu, X, Building2, ChevronDown, Loader2
} from 'lucide-react'
import { STORAGE_KEY_LANG } from './lib/constants'
import { useCapabilities, useCurrentRole, useInbox } from './hooks/useQueries'

// ── Language Switcher ─────────────────────────────────────────────────────────

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  const current = (i18n.resolvedLanguage || i18n.language).split('-')[0] === 'es' ? 'es' : 'en'
  const next = current === 'en' ? 'es' : 'en'

  function toggle() {
    i18n.changeLanguage(next)
    localStorage.setItem(STORAGE_KEY_LANG, next)
  }

  return (
    <button
      onClick={toggle}
      aria-label={t(`language.switchTo.${next}`)}
      className="btn-ghost btn-sm flex items-center gap-1.5 border border-surface-700"
    >
      <Globe size={14} />
      {current.toUpperCase()}
    </button>
  )
}

// ── Nav links config ──────────────────────────────────────────────────────────

type Section = 'evidence' | 'governance' | 'sprints' | 'generate' | 'memory' | 'company'

/**
 * The shell section a path belongs to. Exactly one element per route carries
 * `aria-current="page"`: the primary link of this section, or the Company menu
 * button for company-level pages.
 */
export function sectionForPath(pathname: string): Section | null {
  const path = pathname.toLowerCase()
  const under = (prefix: string) => path === prefix || path.startsWith(`${prefix}/`)
  if (under('/evidence') || under('/lineage')) return 'evidence'
  if (under('/governance')) return 'governance'
  if (under('/sprints') || under('/task')) return 'sprints'
  if (under('/generate')) return 'generate'
  if (under('/memory')) return 'memory'
  if (under('/agents') || under('/company') || under('/companies') || under('/support')) return 'company'
  return null
}

function useNavLinks() {
  const { t } = useTranslation()
  const { data, isPending, isError } = useCapabilities()
  return [
    { to: '/evidence', section: 'evidence' as Section, icon: ClipboardCheck, label: t('nav.evidence', { defaultValue: 'Evidence' }) },
    { to: '/governance', section: 'governance' as Section, icon: ShieldCheck, label: t('nav.review', { defaultValue: 'Review' }) },
    { to: '/sprints', section: 'sprints' as Section, icon: LayoutDashboard, label: t('nav.sprints', { defaultValue: 'Sprints' }) },
    ...(!isPending && !isError && data?.agent_graph === true ? [{ to: '/generate', section: 'generate' as Section, icon: Code2, label: t('nav.generate', { defaultValue: 'Generate' }) }] : []),
    ...(!isPending && !isError && data?.memory === true ? [{ to: '/memory', section: 'memory' as Section, icon: Database, label: t('nav.memory', { defaultValue: 'Memory' }) }] : []),
  ]
}

// ── Legacy route redirects ────────────────────────────────────────────────────

function ActiveSprintRedirect({ tab }: { tab?: SprintTab }) {
  const activeSprintId = useAppStore(state => state.activeSprintId)
  return <Navigate to={activeSprintId ? sprintPath(activeSprintId, tab) : '/sprints'} replace />
}

function SprintParamRedirect({ tab }: { tab: SprintTab }) {
  const { id = '' } = useParams()
  return <Navigate to={sprintPath(encodeURIComponent(id), tab)} replace />
}

function LegacyTaskRedirect() {
  const { sprintId = '', taskId = '' } = useParams()
  return <Navigate to={`/sprints/${encodeURIComponent(sprintId)}/tasks/${encodeURIComponent(taskId)}`} replace />
}



// ── Status pill (live backend health) ────────────────────────────────────────
const HEALTH_COMPONENTS = ['postgres', 'nats', 'llm_proxy', 'neo4j'] as const

function StatusPill({ t }: { t: (k: string, o?: any) => string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { isError } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.health(),
    refetchInterval: 15000,
    retry: 1,
  })
  // Per-service probes are slow when a service is down: only while open.
  const deep = useQuery({
    queryKey: ['health', 'deep'],
    queryFn: () => api.deepHealth(),
    enabled: open,
    staleTime: 0,
    retry: false,
  })
  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])
  const online = !isError
  return (
    <div ref={ref} className="relative hidden xl:block">
      <button type="button" onClick={() => setOpen(value => !value)}
        onKeyDown={event => { if (event.key === 'Escape') setOpen(false) }}
        aria-expanded={open} aria-controls="service-status"
        className="flex items-center gap-2 px-3 py-1.5 bg-surface-800 rounded-full border border-surface-700 text-xs text-gray-400 hover:border-surface-600">
        <span className={online ? 'status-dot-pulse' : 'w-2 h-2 rounded-full bg-red-500'} />
        {online ? t('nav.online', { defaultValue: 'Online' }) : t('nav.offline', { defaultValue: 'Offline' })}
      </button>
      {open && (
        <div id="service-status" role="dialog" aria-label={t('health.title', { defaultValue: 'Service status' })}
          className="absolute right-0 top-full z-20 mt-2 w-72 rounded-lg border border-surface-700 bg-surface-900 p-3 text-xs shadow-lg">
          <p className="mb-2 font-semibold text-gray-200">{t('health.title', { defaultValue: 'Service status' })}</p>
          {deep.isLoading ? (
            <p role="status" className="flex items-center gap-2 text-gray-400">
              <Loader2 size={12} className="animate-spin" /> {t('health.checking', { defaultValue: 'Checking services…' })}
            </p>
          ) : deep.isError || !deep.data ? (
            <p role="alert" className="text-red-300">{t('health.error', { defaultValue: 'Could not check the services.' })}</p>
          ) : (
            <>
              <p className="mb-2 text-gray-400">{t(`health.overall.${deep.data.status}`, { defaultValue: deep.data.status })}</p>
              <ul className="space-y-1.5">
                {HEALTH_COMPONENTS.filter(name => deep.data.components[name]).map(name => {
                  const component = deep.data.components[name]
                  const up = component.status === 'up'
                  return (
                    <li key={name}>
                      <span className="flex items-center gap-2">
                        <span className={`h-2 w-2 shrink-0 rounded-full ${up ? 'bg-emerald-400' : 'bg-red-500'}`} aria-hidden="true" />
                        <span className="text-gray-200">{t(`health.components.${name}`)}</span>
                        <span className={`ml-auto ${up ? 'text-emerald-300' : 'text-red-300'}`}>
                          {up ? t('health.up', { defaultValue: 'up' }) : t('health.down', { defaultValue: 'down' })}
                        </span>
                      </span>
                      {!up && component.reason && <span className="block break-words pl-4 text-gray-500">{component.reason}</span>}
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── NavBar ────────────────────────────────────────────────────────────────────

function NavBar() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [companyOpen, setCompanyOpen] = useState(false)
  const companyRef = useRef<HTMLDivElement>(null)
  const companyToggleRef = useRef<HTMLButtonElement>(null)
  const mobileToggleRef = useRef<HTMLButtonElement>(null)
  const mobileMenuRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()
  const user = useAuthStore(state => state.user)
  const token = useAuthStore(state => state.token)
  const expiresAt = useAuthStore(state => state.expiresAt)
  const logout = useAuthStore(state => state.logout)
  const memberships = useAuthStore(state => state.memberships)
  const role = useCurrentRole()
  const canManage = role === 'Owner' || role === 'Manager'
  const supportAdmin = Boolean(user?.support_admin)
  const companyName = useAppStore(state => state.companyName)
  const companyId = useAppStore(state => state.companyId)
  const authenticated = Boolean(token && expiresAt && expiresAt > Date.now())
  const links = useNavLinks()
  // What the company needs a person for, shown on the Review link.
  const inbox = useInbox(authenticated ? companyId : null)
  const waiting = inbox.data?.total ?? 0
  const section = sectionForPath(location.pathname)
  const companyCurrent = section === 'company'
  const companyLabel = companyId !== null
    ? companyName || t('auth.companyPlaceholder', { id: companyId, defaultValue: 'Company {{id}}' })
    : user?.full_name || user?.email || t('auth.selectCompany', { defaultValue: 'Select a company' })

  useEffect(() => {
    setMenuOpen(false)
    setCompanyOpen(false)
  }, [location])

  useEffect(() => {
    function closeOutside(event: PointerEvent) {
      const target = event.target as Node
      if (!companyRef.current?.contains(target)) setCompanyOpen(false)
      if (!mobileMenuRef.current?.contains(target) && !mobileToggleRef.current?.contains(target)) setMenuOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [])

  useEffect(() => {
    if (companyOpen) companyRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
  }, [companyOpen])

  const linkClass = (isActive: boolean) =>
    `flex items-center gap-1.5 whitespace-nowrap text-sm font-medium px-2 py-2 rounded-lg transition-colors
     ${isActive
       ? 'text-white bg-brand-600/20 border border-brand-600/30'
       : 'text-gray-400 hover:text-white hover:bg-surface-800'}`

  return (
    <header className="relative h-14 bg-surface-900 border-b border-surface-700 text-white flex items-center gap-2 px-4 lg:px-6 z-20 flex-shrink-0"
      onKeyDown={event => {
        if (event.key !== 'Escape') return
        if (companyOpen) {
          setCompanyOpen(false)
          companyToggleRef.current?.focus()
        }
        if (menuOpen) {
          setMenuOpen(false)
          mobileToggleRef.current?.focus()
        }
      }}>
      {/* Logo */}
      <Link to="/evidence" className="flex items-center gap-2.5 hover:opacity-80 transition-opacity flex-shrink-0">
        <img src="/fabrique-icon.svg" alt="La Fabrique" width={30} height={30} className="rounded-md" />
        <span className="text-lg font-black tracking-tight hidden xl:block">La Fabrique</span>
      </Link>

      {/* Desktop nav */}
      {authenticated && (
        <nav className="hidden lg:flex flex-1 min-w-0 items-center gap-1 ml-4" aria-label={t('nav.mainNavigation', { defaultValue: 'Main navigation' })}>
          {links.map(({ to, section: linkSection, icon: Icon, label }) => (
            <Link key={to} to={to} aria-current={section === linkSection ? 'page' : undefined} className={linkClass(section === linkSection)}>
              <Icon size={16} />
              <span>{label}</span>
              {to === '/governance' && waiting > 0 && (
                <span className="badge">
                  <span aria-hidden="true">{waiting}</span>
                  <span className="sr-only">{t('inbox.navCount', { count: waiting, defaultValue: '{{count}} waiting for you' })}</span>
                </span>
              )}
            </Link>
          ))}
        </nav>
      )}

      {/* Right side */}
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <LanguageSwitcher />
        {authenticated && (
          <>
            <div ref={companyRef} className="relative" onBlur={event => {
              if (!event.currentTarget.contains(event.relatedTarget)) setCompanyOpen(false)
            }}>
              <button ref={companyToggleRef} type="button"
                className={`btn-ghost btn-sm max-w-36 xl:max-w-48 border ${companyCurrent ? 'text-white bg-brand-600/20 border-brand-600/30' : 'border-transparent'}`}
                aria-haspopup="menu" aria-expanded={companyOpen} title={companyLabel}
                aria-current={companyCurrent ? 'page' : undefined}
                onKeyDown={event => {
                  if (event.key === 'ArrowDown') {
                    event.preventDefault()
                    setCompanyOpen(true)
                  }
                }}
                aria-controls="company-menu" onClick={() => {
                  setCompanyOpen(open => !open)
                  setMenuOpen(false)
                }}>
                <Building2 size={14} className="shrink-0" /><span className="truncate">{companyLabel}</span><ChevronDown size={14} className="shrink-0" />
              </button>
              {companyOpen && (
                <div id="company-menu" role="menu" aria-label={companyLabel}
                  onClick={() => setCompanyOpen(false)}
                  onKeyDown={event => {
                    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
                    event.preventDefault()
                    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'))
                    const current = items.indexOf(document.activeElement as HTMLElement)
                    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
                      : (current + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length
                    items[next]?.focus()
                  }}
                  className="absolute right-0 top-full mt-2 w-60 max-w-[calc(100vw-2rem)] rounded-lg border border-surface-700 bg-surface-900 p-2 shadow-lg">
                  {memberships.length > 1 && <Link role="menuitem" to="/companies/select" className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-800">{t('auth.switchCompany', { defaultValue: 'Switch company' })}</Link>}
                  <Link role="menuitem" to="/companies/new" className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-800">{t('nav.newCompany', { defaultValue: 'New company' })}</Link>
                  <Link role="menuitem" to="/agents" className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-800">{t('nav.agents', { defaultValue: 'Agents' })}</Link>
                  <Link role="menuitem" to="/company/quotas" className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-800">{t('nav.quotas', { defaultValue: 'Quotas' })}</Link>
                  <Link role="menuitem" to="/company/procedures" className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-800">{t('nav.procedures', { defaultValue: 'Procedures' })}</Link>
                  {role === 'Owner' && <Link role="menuitem" to="/company/members" className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-800">{t('nav.members', { defaultValue: 'Members' })}</Link>}
                  {canManage && <Link role="menuitem" to="/company/github" className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-800">{t('nav.github', { defaultValue: 'GitHub' })}</Link>}
                  {supportAdmin && <Link role="menuitem" to="/support" className="block rounded-lg px-3 py-2 text-sm hover:bg-surface-800">{t('nav.helpDesk', { defaultValue: 'Help desk' })}</Link>}
                  <button role="menuitem" type="button" className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-800" onClick={() => {
                    logout()
                    navigate('/login', { replace: true })
                  }}>{t('auth.logout', { defaultValue: 'Log out' })}</button>
                </div>
              )}
            </div>
          </>
        )}

        {/* Status pill — desktop only */}
        <StatusPill t={t} />

        {/* Hamburger — mobile/tablet */}
        {authenticated && <button
          ref={mobileToggleRef}
          aria-label={menuOpen ? t('nav.closeMenu', { defaultValue: 'Close menu' }) : t('nav.openMenu', { defaultValue: 'Open menu' })}
          aria-controls="mobile-menu"
          aria-expanded={menuOpen}
          onClick={() => {
            setMenuOpen(v => !v)
            setCompanyOpen(false)
          }}
          className="btn-ghost btn-icon lg:hidden"
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>}
      </div>

      {/* Mobile dropdown */}
      {authenticated && menuOpen && (
        <div
          ref={mobileMenuRef} id="mobile-menu"
          className="absolute top-full left-0 right-0 bg-surface-900 border-b border-surface-700 lg:hidden z-30 animate-fade-in"
          onClick={() => setMenuOpen(false)}
        >
          <nav className="flex flex-col p-3 gap-1" aria-label={t('nav.mobileNavigation', { defaultValue: 'Mobile navigation' })}>
            {links.map(({ to, section: linkSection, icon: Icon, label }) => (
              <Link key={to} to={to} aria-current={section === linkSection ? 'page' : undefined} className={linkClass(section === linkSection)}>
                <Icon size={16} />
                <span>{label}</span>
                {to === '/governance' && waiting > 0 && (
                  <span className="badge">
                    <span aria-hidden="true">{waiting}</span>
                    <span className="sr-only">{t('inbox.navCount', { count: waiting, defaultValue: '{{count}} waiting for you' })}</span>
                  </span>
                )}
              </Link>
            ))}
          </nav>
        </div>
      )}
    </header>
  )
}

// ── App shell ─────────────────────────────────────────────────────────────────

function AppContent() {
  const navigate = useNavigate()

  useEffect(() => {
    setOnUnauthorized(() => {
      if (window.location.pathname === '/login') return
      const from = `${window.location.pathname}${window.location.search}${window.location.hash}`
      navigate(`/login?from=${encodeURIComponent(from)}`, { replace: true })
    })
    return () => setOnUnauthorized(null)
  }, [navigate])

  // Desktop app: the native "Factory" menu asks the renderer to navigate.
  useEffect(() => {
    const onNavigate = window.electronAPI?.onNavigate
    if (!onNavigate) return
    return onNavigate(path => {
      if (path.startsWith('/')) navigate(path)
    })
  }, [navigate])

  return (
    <div className="min-h-screen bg-surface-950 flex flex-col relative">
      <NavBar />
      <main className="flex-1 overflow-auto">
        <ErrorBoundary>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route element={<ProtectedRoute />}>
              <Route path="/" element={<Navigate to="/evidence" replace />} />
              <Route path="/sprints" element={<Sprints />} />
              <Route path="/sprints/:id" element={<SprintWorkspace />} />
              <Route path="/sprints/:id/:tab" element={<SprintWorkspace />} />
              <Route path="/sprints/:sprintId/tasks/:taskId" element={<TaskDetails />} />
              <Route path="/dashboard" element={<ActiveSprintRedirect />} />
              <Route path="/dashboard/analytics" element={<ActiveSprintRedirect tab="analytics" />} />
              <Route path="/analytics" element={<ActiveSprintRedirect tab="analytics" />} />
              <Route path="/workspace/:id" element={<SprintParamRedirect tab="live" />} />
              <Route path="/workspace/:id/live" element={<SprintParamRedirect tab="live" />} />
              <Route path="/workspace/:sprintId/task/:taskId" element={<LegacyTaskRedirect />} />
              <Route path="/sprint-ops/:id" element={<SprintParamRedirect tab="board" />} />
              <Route path="/companies/new" element={<CompanyNew />} />
              <Route path="/companies/select" element={<CompanySelect />} />
              <Route path="/company/quotas" element={<div className="page-container"><QuotaPanel /></div>} />
              <Route path="/company/members" element={<CompanyMembers />} />
              <Route path="/company/procedures" element={<Procedures />} />
              <Route path="/company/github" element={<GitHubIntegration />} />
              <Route path="/support" element={<HelpDesk />} />
              <Route path="/agents" element={<AgentSettings />} />
              <Route
                path="/governance"
                element={<div className="page-container"><GovernancePanel /></div>}
              />
              <Route path="/evidence" element={<Evidence />} />
              <Route path="/evidence/:runId" element={<EvidenceDetail />} />
              <Route path="/lineage" element={<Lineage />} />
              <Route path="/memory" element={<MemorySearch />} />
              <Route path="/generate" element={<Generate />} />
              <Route path="/task/:taskId" element={<TaskDetails />} />
              <Route path="*" element={<NotFound />} />
            </Route>
          </Routes>
        </ErrorBoundary>
      </main>
      <SupportBot />
      <ToastContainer />
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  )
}

export default App
