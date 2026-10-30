import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { useAppStore } from '../store/useAppStore'
import { useAuthStore } from '../store/useAuthStore'
import {
  api,
  ApiError,
  errorDetail,
  type DetectedStack,
  type DiscoverTeamAgent,
  type DiscoverTeamResponse,
  type InitCompanyResponse,
  type WorkspaceHost,
  type WorkspaceInspection,
} from '../services/api'
import { FolderPicker } from '../components/FolderPicker'
import { WorkspaceDaemonHelp } from '../components/WorkspaceDaemonHelp'
import { clientPlatform } from '../lib/workspace'
import {
  useModels,
  useDiscoverTeam,
  useInitCompany,
  useWorkspaceStatus,
} from '../hooks/useQueries'

// ── Types ────────────────────────────────────────────────────────────────────

interface Agent {
  name: string
  role: string
  persona: string
  seniority: string
  specialty: string
  token_budget?: number
  reasoning?: string
  model?: string
  system_prompt?: string
}

interface AgentDraft extends Agent {
  defaultSpecialtyKey?: 'productSpecialty' | 'qaSpecialty'
}

interface ModelInfo {
  id: string
  provider: 'gemini' | 'deepseek'
  tier: 'strategic' | 'balanced' | 'code' | 'fast' | 'preview'
  description: string
}

// Static display metadata keyed by tier — used when model ID is not in the
// live catalogue (e.g. while loading or for legacy agents).
const TIMEZONES = [
  'UTC', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Sao_Paulo', 'America/Argentina/Buenos_Aires', 'Europe/London', 'Europe/Paris',
  'Europe/Berlin', 'Asia/Tokyo', 'Asia/Singapore', 'Australia/Sydney',
]

const approvalToggles = (t: TFunction) => [
  { key: 'require_approval_deploy', label: t('companyNew.approvalDeploy'), icon: '🚀' },
  { key: 'require_approval_db_write', label: t('companyNew.approvalDbWrite'), icon: '🗄️' },
]

const resourceSummary = (t: TFunction) => [
  { label: t('companyNew.resources.git.short'), key: 'git_access', icon: '🔀' },
  { label: t('companyNew.resources.cloud.short'), key: 'cloud_access', icon: '☁️' },
  { label: t('companyNew.resources.db.short'), key: 'db_access', icon: '🗄️' },
  { label: t('companyNew.resources.ci.short'), key: 'ci_access', icon: '🔧' },
  { label: t('companyNew.resources.secrets.short'), key: 'secrets_access', icon: '🔑' },
]

const DEFAULT_TIER = 'balanced'

const TIER_META: Record<string, { color: string; icon: string; label: string }> = {
  strategic: { color: 'text-blue-300 bg-blue-900/30',   icon: '🔵', label: 'Strategic' },
  balanced:  { color: 'text-cyan-300 bg-cyan-900/30',   icon: '⚡', label: 'Balanced'  },
  code:      { color: 'text-green-300 bg-green-900/30', icon: '🟢', label: 'Code'      },
  fast:      { color: 'text-yellow-300 bg-yellow-900/30', icon: '🟡', label: 'Fast'    },
  preview:   { color: 'text-purple-300 bg-purple-900/30', icon: '🔮', label: 'Preview' },
}

interface Permissions {
  git_access: string
  cloud_access: string
  db_access: string
  ci_access: string
  secrets_access: string
  require_approval_deploy: boolean
  require_approval_db_write: boolean
}

// ── Constants ────────────────────────────────────────────────────────────────

const ROLES = [
  { value: 'PO',       label: 'Product Owner',        icon: '🎯', desc: 'Defines features and priorities' },
  { value: 'SM',       label: 'Scrum Master',          icon: '🔄', desc: 'Facilitates agile delivery' },
  { value: 'Architect',label: 'Solution Architect',    icon: '🏗️', desc: 'Designs system structure' },
  { value: 'Dev',      label: 'Developer',             icon: '💻', desc: 'Writes and reviews code' },
  { value: 'QA',       label: 'QA Engineer',           icon: '🧪', desc: 'Tests and validates quality' },
  { value: 'DevOps',   label: 'DevOps Engineer',       icon: '🚀', desc: 'CI/CD and infrastructure' },
  { value: 'Security', label: 'Security Engineer',     icon: '🔐', desc: 'Vulnerability and compliance' },
  { value: 'Data',     label: 'Data Engineer',         icon: '📊', desc: 'Pipelines and analytics' },
]

const SENIORITIES = [
  { value: 'Junior', label: 'Junior',  color: 'text-gray-400',   desc: '0–2 yrs' },
  { value: 'Mid',    label: 'Mid',     color: 'text-blue-400',   desc: '2–5 yrs' },
  { value: 'Senior', label: 'Senior',  color: 'text-brand-400',  desc: '5–10 yrs' },
  { value: 'Staff',  label: 'Staff',   color: 'text-purple-400', desc: '10+ yrs' },
]

const AUTONOMY_LEVELS = [
  {
    value: 1,
    label: 'Level 1 — Copilot',
    icon: '🧑‍✈️',
    color: 'border-green-700/50 bg-green-950/20',
    badge: 'bg-green-900/40 text-green-300',
    desc: 'Every AI action requires explicit human approval. Safe for regulated environments.',
    features: ['Full human oversight', 'Manual approve/reject each task', 'Audit log for all actions'],
  },
  {
    value: 2,
    label: 'Level 2 — Exception Manager',
    icon: '⚡',
    color: 'border-brand-700/50 bg-brand-950/20',
    badge: 'bg-brand-900/40 text-brand-300',
    desc: 'AI runs routine tasks autonomously. Flags risky actions for human review.',
    features: ['Auto-approve low-risk tasks', 'Human review for deployments & DB writes', 'Configurable risk thresholds'],
  },
  {
    value: 3,
    label: 'Level 3 — Full Autonomous',
    icon: '🤖',
    color: 'border-red-700/40 bg-red-950/10',
    badge: 'bg-red-900/40 text-red-300',
    desc: 'AI operates without intervention. Recommended only after extensive testing.',
    features: ['Zero human intervention', 'Self-healing and auto-rollback', 'SLA-driven decisions'],
  },
]

const PERM_LEVELS = {
  none:      { label: 'None',       color: 'text-gray-500' },
  read_only: { label: 'Read Only',  color: 'text-blue-400' },
  write:     { label: 'Write',      color: 'text-yellow-400' },
  admin:     { label: 'Admin',      color: 'text-red-400' },
}

const DEFAULT_PERMISSIONS: Permissions = {
  git_access: 'read_only',
  cloud_access: 'none',
  db_access: 'read_only',
  ci_access: 'none',
  secrets_access: 'none',
  require_approval_deploy: true,
  require_approval_db_write: true,
}

const STEPS = ['Project', 'Company', 'Autonomy', 'Permissions', 'Team', 'Review']

const localizedRoles = (t: TFunction) => ROLES.map(role => ({
  ...role,
  label: t(`companyNew.roles.${role.value}.label`, { defaultValue: role.label }),
  desc: t(`companyNew.roles.${role.value}.description`, { defaultValue: role.desc }),
}))

const localizedSeniorities = (t: TFunction) => SENIORITIES.map(seniority => ({
  ...seniority,
  label: t(`companyNew.seniorities.${seniority.value}.label`, { defaultValue: seniority.label }),
  desc: t(`companyNew.seniorities.${seniority.value}.experience`, { defaultValue: seniority.desc }),
}))

const localizedAutonomy = (t: TFunction) => AUTONOMY_LEVELS.map(level => ({
  ...level,
  label: t(`companyNew.autonomy.${level.value}.label`, { defaultValue: level.label }),
  desc: t(`companyNew.autonomy.${level.value}.description`, { defaultValue: level.desc }),
  features: level.features.map((feature, index) =>
    t(`companyNew.autonomy.${level.value}.feature${index + 1}`, { defaultValue: feature })),
}))

const localizedPermission = (t: TFunction, value: string) =>
  t(`companyNew.permissionLevels.${value}`, {
    defaultValue: PERM_LEVELS[value as keyof typeof PERM_LEVELS]?.label ?? value,
  })

// ── Sub-components ────────────────────────────────────────────────────────────

function StepIndicator({ current, steps }: { current: number; steps: string[] }) {
  return (
    <div className="flex items-center justify-between mb-8">
      {steps.map((label, i) => (
        <div key={i} className="flex items-center flex-1 last:flex-none">
          <div className="flex flex-col items-center gap-1 flex-shrink-0">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-all
              ${i < current ? 'bg-brand-600 text-white' : i === current ? 'bg-brand-500 text-white ring-2 ring-brand-400/40' : 'bg-surface-700 text-gray-500'}`}>
              {i < current ? '✓' : i + 1}
            </div>
            <span className={`text-xs whitespace-nowrap
              ${i === current ? 'text-brand-300 font-medium' : i < current ? 'text-gray-400' : 'text-gray-600'}`}>
              {label}
            </span>
          </div>
          {i < steps.length - 1 && (
            <div className={`h-px flex-1 mx-2 mb-5 transition-all ${i < current ? 'bg-brand-600' : 'bg-surface-700'}`} />
          )}
        </div>
      ))}
    </div>
  )
}

const PROVIDER_BADGES: Record<string, string> = {
  github: 'bg-gray-800 text-gray-100 ring-1 ring-gray-600',
  gitlab: 'bg-orange-900/50 text-orange-200 ring-1 ring-orange-700/50',
  bitbucket: 'bg-blue-900/50 text-blue-200 ring-1 ring-blue-700/50',
  other: 'bg-surface-700 text-gray-200',
  none: 'bg-yellow-900/40 text-yellow-200',
}

/** Result of asking the workspace daemon about a folder; `stale` when the field changed meanwhile. */
type InspectOutcome =
  | { kind: 'ok'; result: WorkspaceInspection }
  | { kind: 'error' }
  | { kind: 'stale' }

const platformName = (t: TFunction, platform: string) =>
  t(`workspaceDaemon.platforms.${platform}`, { defaultValue: platform })

/** The folder the agents will work in, as the workspace daemon sees it. */
function ProjectCard({ project }: { project: WorkspaceInspection }) {
  const { t } = useTranslation()
  if (!project.exists || !project.is_dir) {
    return (
      <div role="alert" className="alert-error text-sm">
        <span className="break-all">
          {t(project.exists ? 'projectFolder.notFolder' : 'projectFolder.notFound', {
            host: project.host.hostname,
            path: project.path,
          })}
        </span>
      </div>
    )
  }
  const git = project.git
  const provider = git?.is_repo ? (git.provider ?? 'other') : 'none'
  const remote = git?.is_repo ? (git.remote_url ?? git.web_url) : null
  return (
    <section aria-label={t('projectFolder.cardLabel')} data-testid="project-card"
      className="rounded-xl border border-surface-700 bg-surface-800/50 p-4 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span aria-hidden="true">📁</span>
        <span className="text-sm font-semibold text-white break-all">{project.name}</span>
        <span className={`badge ${PROVIDER_BADGES[provider] ?? PROVIDER_BADGES.other}`} data-testid="project-provider">
          {t(`projectFolder.providers.${provider}`, { defaultValue: provider })}
        </span>
      </div>
      <p className="font-mono text-xs text-gray-400 break-all">{project.path}</p>
      {git?.is_repo ? (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-gray-500">{t('projectFolder.remote')}</dt>
          <dd className="min-w-0 break-all font-mono text-gray-200">
            {git.web_url ? (
              <a href={git.web_url} target="_blank" rel="noopener noreferrer" className="text-brand-300 hover:underline">
                {git.web_url}
              </a>
            ) : (remote ?? <span className="font-sans text-gray-500">{t('projectFolder.noRemote')}</span>)}
          </dd>
          <dt className="text-gray-500">{t('projectFolder.branch')}</dt>
          <dd className="min-w-0 break-all font-mono text-gray-200">
            {git.branch ?? <span className="font-sans text-gray-500">{t('projectFolder.noBranch')}</span>}
          </dd>
        </dl>
      ) : (
        <p className="text-xs text-gray-500">{t('projectFolder.notGitHint')}</p>
      )}
    </section>
  )
}

/** Whether the native workspace daemon answers, and on which machine. */
function DaemonStatusLine({ host, connected, state, reason, isPending, error, fallbackPlatform }: {
  host: WorkspaceHost | null | undefined
  connected: boolean | undefined
  state?: 'connected' | 'absent' | 'unknown'
  reason?: string | null
  isPending: boolean
  error: unknown
  fallbackPlatform: string | undefined
}) {
  const { t } = useTranslation()
  if (isPending) return null
  if (connected && host) {
    return (
      <p role="status" className="flex items-center gap-2 text-xs text-green-300">
        <span className="status-dot bg-green-500" aria-hidden="true" />
        {t('workspaceDaemon.connected', { hostname: host.hostname, platform: platformName(t, host.platform) })}
      </p>
    )
  }
  // Unknown is not absent: the backend could not tell, so no "start it" instructions.
  if (state === 'unknown') {
    return (
      <p role="status" className="flex items-center gap-2 text-xs text-amber-300">
        <span className="status-dot bg-amber-500" aria-hidden="true" />
        {t('workspaceDaemon.unknown', { reason: reason ?? '' })}
      </p>
    )
  }
  if (connected === false) return <WorkspaceDaemonHelp role="status" platform={fallbackPlatform} />
  if (error) {
    return (
      <p role="status" className="text-xs text-gray-500">
        {t('workspaceDaemon.statusError', { message: errorDetail(error) })}
      </p>
    )
  }
  return null
}

function AgentCard({ agent, index, onUpdate, onRemove, canRemove, availableModels }: {
  agent: Agent
  index: number
  onUpdate: (i: number, field: keyof Agent, val: string | number) => void
  onRemove: (i: number) => void
  canRemove: boolean
  availableModels: ModelInfo[]
}) {
  const { t } = useTranslation()
  const roles = localizedRoles(t)
  const seniorities = localizedSeniorities(t)
  const roleInfo  = roles.find(r => r.value === agent.role) ?? roles[3]
  const senInfo   = seniorities.find(s => s.value === agent.seniority) ?? seniorities[2]
  const modelInfo = availableModels.find(m => m.id === (agent.model ?? ''))
  const tierMeta  = TIER_META[modelInfo?.tier ?? 'balanced']
  const [showPrompt, setShowPrompt] = useState(false)

  return (
    <div className="bg-surface-800 border border-surface-700 rounded-xl p-5 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{roleInfo.icon}</span>
          <div>
            {agent.name ? (
              <>
                <p className="text-sm font-medium text-white">{agent.name}</p>
                <p className="text-xs text-gray-500">{roleInfo.label} · {roleInfo.desc}</p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-white">{roleInfo.label}</p>
                <p className="text-xs text-gray-500">{roleInfo.desc}</p>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          {modelInfo && (
            <span className={`badge text-[10px] font-mono ${tierMeta.color}`}>
              {tierMeta.icon} {agent.model}
            </span>
          )}
          {canRemove && (
            <button onClick={() => onRemove(index)}
              className="text-gray-600 hover:text-red-400 transition-colors text-lg leading-none p-1 ml-1"
              title={t('companyNew.removeAgent')}>×</button>
          )}
        </div>
      </div>

      {/* Name / Alias */}
      <div>
        <label className="input-label">{t('companyNew.agentName')}</label>
        <input type="text" value={agent.name}
          onChange={e => onUpdate(index, 'name', e.target.value)}
          placeholder={t('companyNew.agentNamePlaceholder')}
          className="input w-full" />
      </div>

      {/* Role + Seniority */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="input-label">{t('companyNew.agentRole')}</label>
          <select value={agent.role} onChange={e => onUpdate(index, 'role', e.target.value)} className="select w-full">
            {roles.map(r => <option key={r.value} value={r.value}>{r.icon} {r.label}</option>)}
          </select>
        </div>
        <div>
          <label className="input-label">{t('companyNew.seniority')}</label>
          <select value={agent.seniority} onChange={e => onUpdate(index, 'seniority', e.target.value)} className="select w-full">
            {seniorities.map(s => (
              <option key={s.value} value={s.value}>{s.label} ({s.desc})</option>
            ))}
          </select>
        </div>
      </div>

      {/* Model selector */}
      <div>
        <label className="input-label">{t('companyNew.llmModel')}</label>
        <select value={agent.model ?? ''}
          onChange={e => onUpdate(index, 'model', e.target.value)} className="select w-full text-xs">
          <option value="">{t('companyNew.selectModel')}</option>
          {availableModels.length === 0 && (
            <option value="" disabled>{t('companyNew.loadingModels')}</option>
          )}
          {Object.keys(TIER_META).map(tier => {
            const group = availableModels.filter(m => m.tier === tier)
            if (!group.length) return null
            const tm = TIER_META[tier]
            return (
              <optgroup key={tier} label={`${tm.icon} ${t(`companyNew.tiers.${tier}`, { defaultValue: tm.label })}`}>
                {group.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.id} ({m.provider})
                  </option>
                ))}
              </optgroup>
            )
          })}
          {agent.model && !availableModels.find(m => m.id === agent.model) && (
            <option value={agent.model}>{t('companyNew.unresolvedModel', { model: agent.model })}</option>
          )}
        </select>
        {modelInfo && (
          <p className="text-[10px] text-gray-600 mt-1">{modelInfo.description}</p>
        )}
      </div>

      {/* Specialty */}
      <div>
        <label className="input-label">{t('companyNew.specialty')}</label>
        <input type="text" value={agent.specialty || agent.persona}
          onChange={e => { onUpdate(index, 'persona', e.target.value); onUpdate(index, 'specialty', e.target.value) }}
          placeholder={t(`companyNew.specialtyPlaceholders.${['Dev', 'DevOps', 'QA'].includes(roleInfo.value) ? roleInfo.value : 'other'}`)}
          className="input w-full" />
      </div>

      {/* System prompt — collapsible */}
      {agent.system_prompt && (
        <div>
          <button type="button"
            onClick={() => setShowPrompt(v => !v)}
            className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1 transition-colors">
            {showPrompt ? '▾' : '▸'} {t('companyNew.systemPrompt')}
          </button>
          {showPrompt && (
            <textarea
              value={agent.system_prompt}
              onChange={e => onUpdate(index, 'system_prompt', e.target.value)}
              rows={4}
              className="textarea w-full text-xs mt-1 text-gray-300 font-mono"
            />
          )}
        </div>
      )}

      {/* Token budget */}
      <div>
        <label className="input-label">{t('companyNew.monthlyBudget')}</label>
        <div className="flex items-center gap-2">
          <input type="range" min={100000} max={5000000} step={100000}
            value={agent.token_budget ?? 500000}
            onChange={e => onUpdate(index, 'token_budget', parseInt(e.target.value))}
            className="flex-1 accent-brand-500" />
          <span className="text-xs text-brand-300 w-20 text-right font-mono">
            {t('companyNew.thousandTokens', { count: (agent.token_budget ?? 500000) / 1000 })}
          </span>
        </div>
      </div>

      {/* Badges + reasoning */}
      <div className="flex gap-2 flex-wrap pt-1">
        <span className={`badge bg-surface-700 ${senInfo.color}`}>{senInfo.label}</span>
        <span className="badge bg-surface-700 text-gray-400">{roleInfo.label}</span>
        {agent.specialty && <span className="badge bg-brand-900/30 text-brand-300">{agent.specialty}</span>}
      </div>
      {agent.reasoning && (
        <p className="text-xs text-gray-500 italic border-t border-surface-700/50 pt-2 mt-1">
          💡 {agent.reasoning}
        </p>
      )}
    </div>
  )
}

function PermRow({ icon, label, desc, permKey, value, options, onChange }: {
  icon: string; label: string; desc: string
  permKey: string; value: string; options: string[]
  onChange: (key: string, val: string) => void
}) {
  const { t } = useTranslation()
  const current = PERM_LEVELS[value as keyof typeof PERM_LEVELS]
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 py-3 border-b border-surface-700 last:border-0">
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <span className="text-xl flex-shrink-0">{icon}</span>
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-200">{label}</p>
          <p className="text-xs text-gray-500 truncate">{desc}</p>
        </div>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <span className={`text-xs font-medium ${current?.color ?? 'text-gray-400'} w-20 text-right`}>
          {localizedPermission(t, value)}
        </span>
        <select value={value} onChange={e => onChange(permKey, e.target.value)}
          className="select w-36 text-xs">
          {options.map(o => (
            <option key={o} value={o}>{localizedPermission(t, o)}</option>
          ))}
        </select>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CompanyNew() {
  const { t } = useTranslation()
  const steps = STEPS.map(step => t(`companyNew.steps.${step}`, { defaultValue: step }))
  const autonomyLevels = localizedAutonomy(t)
  const roles = localizedRoles(t)
  const navigate = useNavigate()
  const setCompany = useAppStore(state => state.setCompany)

  // Wizard state
  const [step, setStep] = useState(0)

  // Step 0 — Project. Paths are host-native strings from the user's own
  // computer (macOS, Ubuntu or Windows), so the field starts empty.
  const [projectPath, setProjectPath] = useState('')
  const [discoveryResult, setDiscoveryResult] = useState<DetectedStack | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [inspected, setInspected] = useState<WorkspaceInspection | null>(null)
  const [inspecting, setInspecting] = useState(false)
  const [inspectError, setInspectError] = useState<{ status: number; message: string } | null>(null)
  const inspectRequest = useRef(0)
  const pendingInspect = useRef<{ path: string; promise: Promise<InspectOutcome> } | null>(null)
  const browseButtonRef = useRef<HTMLButtonElement>(null)
  const workspaceStatus = useWorkspaceStatus()
  const workspaceHost = workspaceStatus.data?.host ?? inspected?.host ?? null
  const hostPlatform = workspaceHost?.platform ?? clientPlatform()
  const selectDirectory = typeof window !== 'undefined' ? window.electronAPI?.selectDirectory : undefined

  // Step 1 — Company
  const [companyName, setCompanyName] = useState('')
  const [companyDesc, setCompanyDesc] = useState('')
  const [scopeSize, setScopeSize] = useState<'S' | 'M' | 'L'>('M')
  const [timezone, setTimezone] = useState('UTC')

  // Step 2 — Autonomy
  const [autonomyLevel, setAutonomyLevel] = useState(2)

  // Step 3 — Permissions
  const [permissions, setPermissions] = useState<Permissions>(DEFAULT_PERMISSIONS)

  // Step 4 — Team
  const [agentDrafts, setAgents] = useState<AgentDraft[]>([
    { name: '', role: 'PO', persona: '', seniority: 'Senior', specialty: '', defaultSpecialtyKey: 'productSpecialty', token_budget: 1000000 },
    { name: '', role: 'Architect', persona: '', seniority: 'Senior', specialty: '', token_budget: 2000000 },
    { name: '', role: 'Dev', persona: '', seniority: 'Mid', specialty: '', token_budget: 1000000 },
    { name: '', role: 'QA', persona: '', seniority: 'Senior', specialty: '', defaultSpecialtyKey: 'qaSpecialty', token_budget: 500000 },
  ])
  const agents: Agent[] = agentDrafts.map(({ defaultSpecialtyKey, ...agent }) => ({
    ...agent,
    specialty: defaultSpecialtyKey ? t(`companyNew.defaults.${defaultSpecialtyKey}`) : agent.specialty,
  }))

  // Available LLM models — fetched dynamically from the proxy via backend
  const { data: modelsData } = useModels()
  const availableModels = (modelsData?.models || []) as ModelInfo[]

  const discoverTeamMutation = useDiscoverTeam()
  const initCompanyMutation = useInitCompany()

  // Global
  const loading = initCompanyMutation.isPending
  useEffect(() => {
    if (!loading) return
    const timer = setTimeout(() => {
      console.warn('Init company timeout - resetting')
      initCompanyMutation.reset()
    }, 30000)
    return () => clearTimeout(timer)
  }, [loading])
  const mutationError = (discoverTeamMutation.error as any)?.message || (initCompanyMutation.error as any)?.message || null

  // ── Discover ──────────────────────────────────────────────────────────────

  // ── Project folder ────────────────────────────────────────────────────────

  /**
   * Asks the workspace daemon about `rawPath`. On success the input shows the
   * canonical path it returns. Errors (503: daemon not connected) are shown but
   * never block typing a path by hand.
   */
  const inspectPath = (rawPath: string): Promise<InspectOutcome> => {
    const path = rawPath.trim()
    if (!path) return Promise.resolve({ kind: 'error' })
    // Blurring the field and then clicking Scan asks about the same path twice.
    if (pendingInspect.current?.path === path) return pendingInspect.current.promise
    const request = ++inspectRequest.current
    setInspecting(true)
    setInspectError(null)
    const promise = (async (): Promise<InspectOutcome> => {
      try {
        const result = await api.inspectWorkspace(path)
        if (request !== inspectRequest.current) return { kind: 'stale' }
        setInspected(result)
        if (result.exists) setProjectPath(result.path)
        return { kind: 'ok', result }
      } catch (err) {
        if (request !== inspectRequest.current) return { kind: 'stale' }
        setInspected(null)
        setInspectError({ status: err instanceof ApiError ? err.status : 0, message: errorDetail(err) })
        return { kind: 'error' }
      } finally {
        if (request === inspectRequest.current) {
          setInspecting(false)
          pendingInspect.current = null
        }
      }
    })()
    pendingInspect.current = { path, promise }
    return promise
  }

  const chooseFolder = (path: string) => {
    setPickerOpen(false)
    setProjectPath(path)
    setDiscoveryResult(null)
    void inspectPath(path)
  }

  const handleBrowse = async () => {
    if (!selectDirectory) {
      setPickerOpen(true)
      return
    }
    const chosen = await selectDirectory()
    if (chosen) chooseFolder(chosen)
  }

  const closePicker = () => {
    setPickerOpen(false)
    browseButtonRef.current?.focus()
  }

  const handlePathChange = (value: string) => {
    inspectRequest.current++
    pendingInspect.current = null
    setProjectPath(value)
    setInspected(null)
    setInspectError(null)
    setInspecting(false)
  }

  const folderMissing = inspected !== null && (!inspected.exists || !inspected.is_dir)

  // ── Discover ──────────────────────────────────────────────────────────────

  const handleDiscover = async () => {
    let path = projectPath.trim()
    if (!path || discoverTeamMutation.isPending) return
    if (inspected?.path !== path) {
      // An inspection error (e.g. 503, daemon down) does not block scanning a typed path.
      const outcome = await inspectPath(path)
      if (outcome.kind === 'stale') return
      if (outcome.kind === 'ok') {
        if (!outcome.result.exists || !outcome.result.is_dir) return
        path = outcome.result.path
      }
    } else if (folderMissing) {
      return
    }
    setDiscoveryResult(null)

    discoverTeamMutation.mutate({ companyId: null, projectPath: path }, {
      onSuccess: (response: DiscoverTeamResponse) => {
        if (response.project_path) setProjectPath(response.project_path)
        if (response.project) setInspected(response.project)
        setDiscoveryResult(response.detected_stack)
        if (response.detected_stack.name && !companyName) {
          setCompanyName(response.detected_stack.name)
        }
        if (response.suggested_team.length) {
          setAgents(response.suggested_team.map((a: DiscoverTeamAgent) => ({
            ...a,
            name: a.name ?? '',
            persona: a.persona ?? a.specialty ?? '',
            token_budget: a.token_budget ?? 1000000,
            model: a.model ?? '',
            system_prompt: a.system_prompt ?? '',
          })))
        }
      }
    })
  }

  // ── Agent helpers ─────────────────────────────────────────────────────────

  const addAgent = () => setAgents(prev => [...prev, {
    name: '', role: 'Dev', persona: '', seniority: 'Mid', specialty: '', token_budget: 1000000,
  }])

  const removeAgent = (i: number) => setAgents(prev => prev.filter((_, idx) => idx !== i))

  const updateAgent = (i: number, field: keyof Agent, val: string | number) =>
    setAgents(prev => prev.map((a, idx) => idx === i ? {
      ...a,
      [field]: val,
      defaultSpecialtyKey: field === 'specialty' || field === 'persona' ? undefined : a.defaultSpecialtyKey,
    } : a))

  // ── Permission helpers ────────────────────────────────────────────────────

  const updatePerm = (key: string, val: string) =>
    setPermissions(prev => ({ ...prev, [key]: val }))

  // ── Submit ────────────────────────────────────────────────────────────────

  const handleSubmit = async () => {
    const { require_approval_deploy, require_approval_db_write, ...credPerms } = permissions
    const payload = {
      company_name: companyName.trim(),
      description: companyDesc,
      default_scope_size: scopeSize,
      autonomy_level: autonomyLevel,
      timezone,
      agents,
      permissions: credPerms,
      governance: { require_approval_deploy, require_approval_db_write },
      project_path: projectPath.trim() || undefined,
      detected_stack: discoveryResult || undefined,
    }

    initCompanyMutation.mutate(payload, {
      onSuccess: (response: InitCompanyResponse) => {
        const companyId = response.company_id
        const sprintId = response?.sprint_id ?? companyId
        setCompany(companyId, companyName.trim())
        // Navigate immediately, load profile in background
        navigate(`/sprints/${sprintId}`)
        // Fallback navigation in case React Router doesn't work
        setTimeout(() => {
          if (!window.location.pathname.startsWith(`/sprints/${sprintId}`)) {
            window.location.href = `/sprints/${sprintId}`
          }
        }, 1000)
        useAuthStore.getState().loadMe().catch(() => {})
      },
      onError: (error: any) => {
        console.error('Init company failed:', error)
        alert(t('companyNew.initializationError', { message: error?.message || t('companyNew.unknownError') }))
      }
    })
  }

  // ── Validation ────────────────────────────────────────────────────────────

  const canProceed = () => {
    if (step === 0) return !discoverTeamMutation.isPending
    if (step === 1) return companyName.trim().length >= 2
    if (step === 4) return agents.length >= 1
    return true
  }

  // ── Step renderers ────────────────────────────────────────────────────────

  const renderStep0 = () => (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">{t('companyNew.scanTitle')}</h2>
        <p className="text-sm text-gray-400">
          {t('companyNew.scanDescription')}
        </p>
      </div>

      <div className="space-y-2">
        <label htmlFor="project-path" className="input-label">{t('projectFolder.label')}</label>
        <div className="flex flex-col sm:flex-row gap-2">
          <input id="project-path" type="text" value={projectPath}
            onChange={e => handlePathChange(e.target.value)}
            onBlur={() => {
              const typed = projectPath.trim()
              if (typed && inspected?.path !== typed && !discoverTeamMutation.isPending) void inspectPath(typed)
            }}
            onKeyDown={e => e.key === 'Enter' && handleDiscover()}
            placeholder={t(hostPlatform === 'win32' ? 'projectFolder.placeholderWindows' : 'projectFolder.placeholderUnix')}
            spellCheck={false} autoComplete="off"
            className="input flex-1 min-w-0 font-mono text-sm" />
          <button ref={browseButtonRef} type="button" onClick={handleBrowse}
            className="btn btn-secondary flex-shrink-0">
            📂 {t('companyNew.browse')}
          </button>
        </div>
        {selectDirectory && (
          <button type="button" onClick={() => setPickerOpen(true)}
            className="text-xs text-brand-400 hover:text-brand-300 hover:underline">
            {t('projectFolder.browseDaemon')}
          </button>
        )}
        <DaemonStatusLine
          host={workspaceStatus.data?.host}
          connected={workspaceStatus.data?.connected}
          state={workspaceStatus.data?.state}
          reason={workspaceStatus.data?.reason}
          isPending={workspaceStatus.isPending}
          error={workspaceStatus.error}
          fallbackPlatform={hostPlatform} />
      </div>

      {pickerOpen && (
        <FolderPicker
          initialPath={inspected?.exists && inspected.is_dir ? inspected.path : undefined}
          platform={workspaceHost?.platform}
          onSelect={chooseFolder}
          onClose={closePicker} />
      )}

      {inspecting && (
        <p role="status" className="flex items-center gap-2 text-xs text-gray-400">
          <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          {t('projectFolder.checking')}
        </p>
      )}
      {!inspecting && inspected && <ProjectCard project={inspected} />}
      {!inspecting && inspectError?.status === 503 && (
        <WorkspaceDaemonHelp platform={hostPlatform} detail={inspectError.message}>
          <p className="text-yellow-300/80">{t('projectFolder.manualHint')}</p>
        </WorkspaceDaemonHelp>
      )}
      {!inspecting && inspectError && inspectError.status !== 503 && (
        <div role="alert" className="alert-error text-sm">
          <span className="break-all">{t('projectFolder.inspectError', { message: inspectError.message })}</span>
        </div>
      )}

      <div className="flex justify-end">
        <button type="button" onClick={handleDiscover}
          disabled={discoverTeamMutation.isPending || !projectPath.trim() || folderMissing}
          className="btn btn-primary flex-shrink-0 min-w-28">
          {discoverTeamMutation.isPending ? (
            <span className="flex items-center gap-2">
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              {t('companyNew.scanning')}
            </span>
          ) : `🔍 ${t('companyNew.scan')}`}
        </button>
      </div>

      {mutationError && <div className="alert-error text-sm">{t('companyNew.discoveryError', { message: mutationError })}</div>}

      {discoveryResult && (
        <div className="rounded-xl border border-brand-700/40 bg-brand-950/20 overflow-hidden">
          <div className="px-4 py-3 border-b border-brand-700/20 flex items-center gap-2">
            <span className="text-green-400 text-lg">✓</span>
            <span className="text-sm font-semibold text-brand-200">{t('companyNew.stackDetected')} — <span className="font-mono">{discoveryResult.name}</span></span>
          </div>
          <div className="p-4 grid grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
            {[
              { label: t('companyNew.primaryLanguage'), value: discoveryResult.language, icon: '🔷' },
              { label: t('companyNew.frameworks'), value: discoveryResult.frameworks?.join(', ') || '—', icon: '🧩' },
              { label: t('companyNew.databases'), value: discoveryResult.databases?.join(', ') || '—', icon: '🗄️' },
              { label: t('companyNew.infrastructure'), value: discoveryResult.infra?.join(', ') || '—', icon: '⚙️' },
            ].map(({ label, value, icon }) => (
              <div key={label} className="bg-surface-800/70 rounded-lg p-3">
                <span className="text-base">{icon}</span>
                <p className="text-gray-500 mt-1">{label}</p>
                <p className="text-gray-200 font-medium mt-0.5 break-words leading-snug" title={value}>{value}</p>
              </div>
            ))}
          </div>
          <div className="px-4 py-2 border-t border-brand-700/20 flex items-center justify-between text-xs">
            <span className="text-gray-500">{t('companyNew.filesScanned', { count: discoveryResult.file_count })}</span>
            <div className="flex items-center gap-2">
              {discoveryResult.team_source === 'ai' && (
                <span className="badge bg-purple-900/40 text-purple-300">✨ {t('companyNew.aiSuggestion')}</span>
              )}
              {discoveryResult.team_source === 'rules' && (
                <span className="badge bg-surface-700 text-gray-400">{t('companyNew.rulesSuggestion')}</span>
              )}
              <span className={`badge ${discoveryResult.complexity === 'High' ? 'bg-red-900/40 text-red-300' : discoveryResult.complexity === 'Medium' ? 'bg-yellow-900/40 text-yellow-300' : 'bg-green-900/40 text-green-300'}`}>
                {t('companyNew.complexity', { level: t(`companyNew.complexityLevels.${discoveryResult.complexity}`, { defaultValue: discoveryResult.complexity }) })}
              </span>
            </div>
          </div>
        </div>
      )}

      {!discoveryResult && (
        <div className="rounded-xl border border-surface-700 bg-surface-800/30 p-5 text-center">
          <p className="text-3xl mb-2">🏗️</p>
          <p className="text-sm text-gray-400">{t('companyNew.noProject')}</p>
          <p className="text-xs text-gray-600 mt-1">{t('companyNew.manualTeamHint')}</p>
        </div>
      )}
    </div>
  )

  const renderStep1 = () => (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">{t('companyNew.companyDetails')}</h2>
        <p className="text-sm text-gray-400">{t('companyNew.companyDescription')}</p>
      </div>

      <div>
        <label className="input-label">{t('companyNew.factoryName')} *</label>
        <input type="text" value={companyName} onChange={e => setCompanyName(e.target.value)}
          placeholder={t('companyNew.companyNamePlaceholder')} required className="input w-full text-base" autoFocus />
        {companyName.length > 0 && companyName.length < 2 && (
          <p className="text-xs text-red-400 mt-1">{t('companyNew.nameTooShort')}</p>
        )}
      </div>

      <div>
        <label className="input-label">{t('companyNew.description')} <span className="text-gray-600 normal-case font-normal">{t('companyNew.optional')}</span></label>
        <textarea value={companyDesc} onChange={e => setCompanyDesc(e.target.value)}
          placeholder={t('companyNew.descriptionPlaceholder')}
          rows={3} className="textarea w-full" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="input-label">{t('companyNew.sprintLength')}</label>
          <select
            value={scopeSize}
            onChange={e => setScopeSize(e.target.value as 'S' | 'M' | 'L')}
            className="select w-full"
          >
            <option value="S">{t('companyNew.scopes.S')}</option>
            <option value="M">{t('companyNew.scopes.M')}</option>
            <option value="L">{t('companyNew.scopes.L')}</option>
          </select>
          <p className="text-xs text-gray-500 mt-1">
            {t(`companyNew.scopeHints.${scopeSize}`)}
          </p>
        </div>
        <div>
          <label className="input-label">{t('companyNew.timezone')}</label>
          <select value={timezone} onChange={e => setTimezone(e.target.value)} className="select w-full">
            {TIMEZONES.map(tz => (
              <option key={tz} value={tz}>{t(`companyNew.timezones.${tz}`, { defaultValue: tz })}</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  )

  const renderStep2 = () => (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">{t('companyNew.autonomyLevel')}</h2>
        <p className="text-sm text-gray-400">{t('companyNew.autonomyDescription')}</p>
      </div>

      <div className="space-y-3">
        {autonomyLevels.map(level => (
          <button key={level.value} type="button"
            onClick={() => setAutonomyLevel(level.value)}
            className={`w-full text-left rounded-xl border-2 p-4 transition-all ${autonomyLevel === level.value ? level.color + ' border-opacity-100' : 'border-surface-700 bg-surface-800/30 hover:border-surface-600'}`}>
            <div className="flex items-start gap-3">
              <span className="text-2xl flex-shrink-0 mt-0.5">{level.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-white text-sm">{level.label}</span>
                  {autonomyLevel === level.value && (
                    <span className={`badge text-xs ${level.badge}`}>{t('companyNew.selected')}</span>
                  )}
                </div>
                <p className="text-xs text-gray-400 mt-1">{level.desc}</p>
                <ul className="mt-2 space-y-0.5">
                  {level.features.map(f => (
                    <li key={f} className="text-xs text-gray-500 flex items-center gap-1.5">
                      <span className="text-brand-400">·</span> {f}
                    </li>
                  ))}
                </ul>
              </div>
              <div className={`w-5 h-5 rounded-full border-2 flex-shrink-0 mt-0.5 flex items-center justify-center ${autonomyLevel === level.value ? 'border-brand-400 bg-brand-600' : 'border-surface-600'}`}>
                {autonomyLevel === level.value && <span className="text-white text-xs">✓</span>}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )

  const renderStep3 = () => {
    const gitOptions    = ['read_only', 'write', ...(autonomyLevel === 3 ? ['admin'] : [])]
    const cloudOptions  = ['none', 'read_only', ...(autonomyLevel >= 2 ? ['write'] : []), ...(autonomyLevel === 3 ? ['admin'] : [])]
    const dbOptions     = ['read_only', 'write', ...(autonomyLevel === 3 ? ['admin'] : [])]
    const ciOptions     = ['none', 'read_only', ...(autonomyLevel >= 2 ? ['write'] : [])]
    const secretOptions = ['none', ...(autonomyLevel >= 2 ? ['read_only'] : []), ...(autonomyLevel === 3 ? ['write'] : [])]

    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-white mb-1">{t('companyNew.infraPerms')}</h2>
          <p className="text-sm text-gray-400">
            {t('companyNew.permissionsDescription')}
          </p>
        </div>

        <div className="card divide-y divide-surface-700 rounded-xl overflow-hidden">
          <PermRow icon="🔀" label={t('companyNew.resources.git.label')} permKey="git_access" value={permissions.git_access}
            options={gitOptions} onChange={updatePerm}
            desc={t('companyNew.resources.git.description')} />
          <PermRow icon="☁️" label={t('companyNew.resources.cloud.label')} permKey="cloud_access" value={permissions.cloud_access}
            options={cloudOptions} onChange={updatePerm}
            desc={t('companyNew.resources.cloud.description')} />
          <PermRow icon="🗄️" label={t('companyNew.resources.db.label')} permKey="db_access" value={permissions.db_access}
            options={dbOptions} onChange={updatePerm}
            desc={t('companyNew.resources.db.description')} />
          <PermRow icon="🔧" label={t('companyNew.resources.ci.label')} permKey="ci_access" value={permissions.ci_access}
            options={ciOptions} onChange={updatePerm}
            desc={t('companyNew.resources.ci.description')} />
          <PermRow icon="🔑" label={t('companyNew.resources.secrets.label')} permKey="secrets_access" value={permissions.secrets_access}
            options={secretOptions} onChange={updatePerm}
            desc={t('companyNew.resources.secrets.description')} />
        </div>

        <div className="card p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{t('companyNew.governance')}</p>
          {approvalToggles(t).map(({ key, label, icon }) => (
            <label key={key} className="flex items-center gap-3 cursor-pointer group">
              <input type="checkbox"
                checked={permissions[key as keyof Permissions] as boolean}
                onChange={e => setPermissions(prev => ({ ...prev, [key]: e.target.checked }))}
                className="w-4 h-4 rounded accent-brand-500 flex-shrink-0" />
              <span className="text-sm">
                <span className="mr-1.5">{icon}</span>
                <span className="text-gray-300 group-hover:text-white transition-colors">{label}</span>
              </span>
            </label>
          ))}
        </div>

        {autonomyLevel === 1 && (
          <div className="alert-info text-xs">
            <span>ℹ️</span>
            <span>{t('companyNew.manualApprovalHint')}</span>
          </div>
        )}
      </div>
    )
  }

  const renderStep4 = () => (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-white mb-1">{t('companyNew.teamTitle')}</h2>
          <p className="text-sm text-gray-400">
            {t(discoveryResult ? 'companyNew.suggestedTeamDescription' : 'companyNew.teamDescription')}
          </p>
        </div>
        <button type="button" onClick={addAgent} className="btn btn-secondary btn-sm flex-shrink-0">
          + {t('companyNew.addTeamAgent')}
        </button>
      </div>

      {agents.length === 0 && (
        <div className="alert-error text-sm">{t('companyNew.minAgentError')}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {agents.map((agent, i) => (
          <AgentCard key={i} agent={agent} index={i}
            onUpdate={updateAgent} onRemove={removeAgent} canRemove={agents.length > 1}
            availableModels={availableModels} />
        ))}
      </div>

      <div className="rounded-lg bg-surface-800/30 border border-surface-700 p-3 text-xs text-gray-500 space-y-1">
        <p className="font-medium text-gray-400">{t('companyNew.teamBudget')}</p>
        <p>{t('companyNew.totalMonthly')} <span className="text-brand-300 font-mono">
          {t('companyNew.millionTokens', { amount: (agents.reduce((s, a) => s + (a.token_budget ?? 500000), 0) / 1000000).toFixed(1) })}
        </span></p>
        <p className="text-gray-600">{t('companyNew.budgetHint')}</p>
      </div>
    </div>
  )

  const renderStep5 = () => {
    const selectedAutonomy = autonomyLevels.find(l => l.value === autonomyLevel)!
    const totalBudget = agents.reduce((s, a) => s + (a.token_budget ?? 500000), 0)
    return (
      <div className="space-y-5">
        <div>
          <h2 className="text-lg font-semibold text-white mb-1">{t('companyNew.reviewTitle')}</h2>
          <p className="text-sm text-gray-400">{t('companyNew.reviewDescription')}</p>
        </div>

        <div className="space-y-3">
          {/* Company */}
          <div className="card p-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">{t('companyNew.steps.Company')}</p>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="font-semibold text-white">{companyName}</p>
                {companyDesc && <p className="text-sm text-gray-400 mt-0.5">{companyDesc}</p>}
              </div>
              <button type="button" onClick={() => setStep(1)} className="text-xs text-brand-400 hover:underline flex-shrink-0">{t('companyNew.edit')}</button>
            </div>
            <div className="mt-2 flex gap-3 text-xs text-gray-500">
              <span>🔄 {t('companyNew.scopeSummary', { scope: scopeSize })}</span>
              <span>🌍 {timezone}</span>
            </div>
          </div>

          {/* Autonomy */}
          <div className="card p-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">{t('companyNew.steps.Autonomy')}</p>
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xl">{selectedAutonomy.icon}</span>
                <span className="text-sm font-medium text-white">{selectedAutonomy.label}</span>
                <span className={`badge text-xs ${selectedAutonomy.badge}`}>{t('companyNew.level', { level: autonomyLevel })}</span>
              </div>
              <button type="button" onClick={() => setStep(2)} className="text-xs text-brand-400 hover:underline">{t('companyNew.edit')}</button>
            </div>
          </div>

          {/* Permissions */}
          <div className="card p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('companyNew.permissions')}</p>
              <button type="button" onClick={() => setStep(3)} className="text-xs text-brand-400 hover:underline">{t('companyNew.edit')}</button>
            </div>
            <div className="grid grid-cols-5 gap-2">
              {resourceSummary(t).map(({ label, key, icon }) => {
                const val = permissions[key as keyof Permissions] as string
                const perm = PERM_LEVELS[val as keyof typeof PERM_LEVELS]
                return (
                  <div key={key} className="bg-surface-800/60 rounded-lg p-2 text-center">
                    <span className="text-base">{icon}</span>
                    <p className="text-xs text-gray-500 mt-0.5">{label}</p>
                    <p className={`text-xs font-medium mt-0.5 ${perm?.color ?? 'text-gray-400'}`}>{localizedPermission(t, val)}</p>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Team */}
          <div className="card p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{t('companyNew.teamSummary', { count: agents.length })}</p>
              <button type="button" onClick={() => setStep(4)} className="text-xs text-brand-400 hover:underline">{t('companyNew.edit')}</button>
            </div>
            <div className="space-y-1.5">
              {agents.map((a, i) => {
                const roleInfo = roles.find(r => r.value === a.role)
                return (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span>{roleInfo?.icon ?? '🤖'}</span>
                    <span className="text-gray-300 font-medium">
                      {a.name ? `${a.name} — ${roleInfo?.label ?? a.role}` : (roleInfo?.label ?? a.role)}
                    </span>
                    <span className={`text-xs ${SENIORITIES.find(s => s.value === a.seniority)?.color ?? 'text-gray-400'}`}>{t(`companyNew.seniorities.${a.seniority}.label`, { defaultValue: a.seniority })}</span>
                    {a.model && (() => {
                      const mi = availableModels.find(m => m.id === a.model)
                      const tm = TIER_META[mi?.tier ?? DEFAULT_TIER]
                      return (
                        <span className={`badge text-[10px] font-mono ${tm.color}`}>
                          {tm.icon} {a.model}
                        </span>
                      )
                    })()}
                    {a.specialty && <span className="text-xs text-gray-600 truncate">· {a.specialty}</span>}
                  </div>
                )
              })}
            </div>
            <p className="text-xs text-gray-600 mt-2">
              {t('companyNew.totalBudget')} <span className="text-brand-300 font-mono">{t('companyNew.millionTokensMonthly', { amount: (totalBudget / 1000000).toFixed(1) })}</span>
            </p>
          </div>
        </div>

        {mutationError && <div className="alert-error text-sm">{t('companyNew.initializationError', { message: mutationError })}</div>}

        <button type="button" onClick={handleSubmit}
          disabled={loading}
          className="btn btn-primary w-full text-base py-3">
          {loading ? (
            <span className="flex items-center gap-2 justify-center">
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              {t('companyNew.submitting')}
            </span>
          ) : `🏭 ${t('companyNew.submit')}`}
        </button>
      </div>
    )
  }

  const STEP_RENDERERS = [renderStep0, renderStep1, renderStep2, renderStep3, renderStep4, renderStep5]

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="page-container max-w-6xl">
      <div className="mb-6">
        <h1 className="page-title">🏭 {t('companyNew.newFactory')}</h1>
        <p className="text-gray-400 text-sm mt-1">{t('companyNew.wizardDescription')}</p>
      </div>

      <StepIndicator current={step} steps={steps} />

      <div className="card p-6">
        {STEP_RENDERERS[step]()}
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between mt-4">
        <button type="button" onClick={() => setStep(s => s - 1)}
          disabled={step === 0}
          className="btn btn-secondary disabled:opacity-30">
          ← {t('companyNew.back')}
        </button>

        <span className="text-xs text-gray-600">{step + 1} / {STEPS.length}</span>

        {step < STEPS.length - 1 ? (
          <button type="button" onClick={() => setStep(s => s + 1)}
            disabled={!canProceed()}
            className="btn btn-primary disabled:opacity-50">
            {t('companyNew.next')} →
          </button>
        ) : null}
      </div>
    </div>
  )
}
