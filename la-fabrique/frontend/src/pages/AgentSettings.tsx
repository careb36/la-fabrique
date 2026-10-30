import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Bot,
  ChevronRight,
  Copy,
  Cpu,
  Loader2,
  Plus,
  Save,
  Search,
  Sparkles,
  Trash2,
  Users,
  Wand2,
  X,
} from 'lucide-react'
import { useAgents, useCreateAgent, useCurrentRole, useDeleteAgent, useGenerateAgentPrompt, useModels, useUpdateAgentConfig } from '../hooks/useQueries'
import type { AgentActivity, ManagedAgent, ModelCatalogEntry } from '../services/api'
import { useAppStore } from '../store/useAppStore'
import { useToast } from '../store/toastStore'

type AgentDraft = {
  name: string
  role: string
  persona: string
  seniority: string
  specialty: string
  model: string
  system_prompt: string
  token_budget: number
}

type Recommendation = {
  primary: ModelCatalogEntry | null
  alternatives: ModelCatalogEntry[]
  reasonKey: string
}

const COMMON_ROLES = [
  // Product & Design
  'PO', 'Designer', 'UXResearcher',
  // Engineering
  'Architect', 'BackendDev', 'FrontendDev', 'FullstackDev', 'MobileDev',
  'DataEngineer', 'MLEngineer',
  // Quality & Delivery
  'QA', 'ScrumMaster', 'DevOps', 'Security',
  // Support
  'TechWriter', 'Support',
]
const SENIORITIES = ['Junior', 'Mid', 'Senior', 'Staff']
const TIER_META: Record<string, string> = {
  strategic: 'bg-blue-900/30 text-blue-300',
  balanced: 'bg-cyan-900/30 text-cyan-300',
  code: 'bg-green-900/30 text-green-300',
  fast: 'bg-yellow-900/30 text-yellow-300',
  preview: 'bg-purple-900/30 text-purple-300',
  reasoning: 'bg-fuchsia-900/30 text-fuchsia-300',
}

const AUTO_RECOMMENDED_MODEL_IDS = new Set([
  'deepseek-coder',
  'deepseek-chat',
  'deepseek-reasoner',
  'gemini-3.8-flash',
  'gemini-3.1-pro-preview',
  'gemini-pro-latest',
  'gemini-flash-latest',
])

// Relative ordering used when grouping agents by role on screen.
const ROLE_DISPLAY_ORDER = [
  'PO',
  'Architect',
  'ScrumMaster',
  'BackendDev', 'FrontendDev', 'FullstackDev', 'MobileDev',
  'DataEngineer', 'MLEngineer',
  'Designer', 'UXResearcher',
  'QA',
  'DevOps', 'Security',
  'TechWriter', 'Support',
]

function defaultDraft(): AgentDraft {
  return {
    name: '',
    role: 'BackendDev',
    persona: '',
    seniority: 'Senior',
    specialty: '',
    // Empty means "Default for role": the backend resolves it from model_factory.
    model: '',
    system_prompt: '',
    token_budget: 500000,
  }
}

function draftFromAgent(agent: ManagedAgent): AgentDraft {
  return {
    name: agent.name || '',
    role: agent.role || 'BackendDev',
    persona: agent.persona || '',
    seniority: agent.seniority || 'Senior',
    specialty: agent.specialty || '',
    model: agent.model || '',
    system_prompt: agent.system_prompt || '',
    token_budget: agent.token_budget || 500000,
  }
}

function isDraftDirty(draft: AgentDraft, agent: ManagedAgent): boolean {
  const original = draftFromAgent(agent)
  return (
    draft.name !== original.name ||
    draft.role !== original.role ||
    draft.persona !== original.persona ||
    draft.seniority !== original.seniority ||
    draft.specialty !== original.specialty ||
    draft.model !== original.model ||
    draft.system_prompt !== original.system_prompt ||
    draft.token_budget !== original.token_budget
  )
}

function normalizeRole(role: string): string {
  return role.trim().toLowerCase()
}

function pickModels(models: ModelCatalogEntry[], preferredIds: string[]): ModelCatalogEntry[] {
  const unique: ModelCatalogEntry[] = []
  const seen = new Set<string>()

  for (const id of preferredIds) {
    const match = models.find(model => model.id === id)
    if (match && !seen.has(match.id)) {
      seen.add(match.id)
      unique.push(match)
    }
  }

  return unique
}

/**
 * Returns ordered model IDs based on role + seniority.
 *
 * Seniority tiers:
 *   Staff / Senior  → strongest reasoning models first (higher cost, highest quality)
 *   Mid             → balanced models
 *   Junior          → fast/cheap models first (guided execution, cost-conscious)
 */
function recommendModelForRole(
  models: ModelCatalogEntry[],
  role: string,
  seniority: string = 'Senior',
): Recommendation {
  const normalizedRole = normalizeRole(role)
  const level = seniority.trim().toLowerCase()
  const isJuniorMid = level === 'junior' || level === 'mid'
  const isStaffSenior = level === 'staff' || level === 'senior'

  const defaults = {
    ids: isJuniorMid
      ? ['gemini-3.8-flash', 'deepseek-chat']
      : ['gemini-3.8-flash', 'deepseek-chat'],
    reasonKey: 'generalist',
  }

  const plan = (() => {
    if (['backenddev', 'backend dev', 'backend', 'fullstackdev', 'fullstack dev', 'fullstack', 'dev', 'developer', 'mobiledev', 'mobile dev', 'mobile'].includes(normalizedRole)) {
      return {
        ids: isJuniorMid
          ? ['deepseek-coder', 'gemini-3.8-flash', 'deepseek-chat']
          : ['deepseek-reasoner', 'deepseek-coder', 'gemini-3.1-pro-preview'],
        reasonKey: 'dev',
      }
    }
    if (['frontenddev', 'frontend dev', 'frontend'].includes(normalizedRole)) {
      return {
        ids: isJuniorMid
          ? ['deepseek-coder', 'gemini-3.8-flash', 'deepseek-chat']
          : ['gemini-3.1-pro-preview', 'deepseek-reasoner', 'deepseek-coder'],
        reasonKey: 'frontend',
      }
    }
    if (['dataengineer', 'data engineer', 'data', 'mlengineer', 'ml engineer', 'ml'].includes(normalizedRole)) {
      return {
        ids: isJuniorMid
          ? ['gemini-3.8-flash', 'deepseek-coder', 'deepseek-reasoner']
          : ['deepseek-reasoner', 'gemini-3.1-pro-preview', 'gemini-3.8-flash'],
        reasonKey: 'data',
      }
    }
    if (['designer', 'uxresearcher', 'ux researcher', 'ux'].includes(normalizedRole)) {
      return {
        ids: isJuniorMid
          ? ['gemini-3.8-flash', 'deepseek-chat', 'gemini-flash-latest']
          : ['gemini-3.1-pro-preview', 'gemini-3.8-flash', 'deepseek-reasoner'],
        reasonKey: 'designer',
      }
    }
    if (normalizedRole === 'qa') {
      return {
        ids: isJuniorMid
          ? ['deepseek-coder', 'gemini-3.8-flash', 'deepseek-chat']
          : ['deepseek-reasoner', 'gemini-3.1-pro-preview', 'deepseek-coder'],
        reasonKey: 'qa',
      }
    }
    if (normalizedRole === 'architect') {
      return {
        ids: isJuniorMid
          ? ['gemini-3.8-flash', 'deepseek-reasoner', 'gemini-3.1-pro-preview']
          : ['gemini-3.1-pro-preview', 'deepseek-reasoner', 'gemini-pro-latest'],
        reasonKey: 'architect',
      }
    }
    if (normalizedRole === 'po' || normalizedRole === 'product owner') {
      return {
        ids: isJuniorMid
          ? ['gemini-3.8-flash', 'deepseek-chat', 'gemini-3.1-pro-preview']
          : ['gemini-3.1-pro-preview', 'deepseek-reasoner', 'gemini-pro-latest'],
        reasonKey: 'po',
      }
    }
    if (normalizedRole === 'scrummaster' || normalizedRole === 'sm') {
      return {
        ids: isJuniorMid
          ? ['gemini-3.8-flash', 'deepseek-chat', 'deepseek-reasoner']
          : ['deepseek-reasoner', 'gemini-3.1-pro-preview', 'gemini-3.8-flash'],
        reasonKey: 'scrummaster',
      }
    }
    if (normalizedRole === 'devops') {
      return {
        ids: isJuniorMid
          ? ['gemini-3.8-flash', 'deepseek-coder', 'deepseek-reasoner']
          : ['deepseek-reasoner', 'gemini-3.1-pro-preview', 'gemini-3.8-flash'],
        reasonKey: 'devops',
      }
    }
    if (normalizedRole === 'security') {
      return {
        ids: isJuniorMid
          ? ['gemini-3.8-flash', 'deepseek-reasoner', 'gemini-3.1-pro-preview']
          : ['deepseek-reasoner', 'gemini-3.1-pro-preview', 'gemini-3.8-flash'],
        reasonKey: 'security',
      }
    }
    if (['techwriter', 'tech writer', 'support'].includes(normalizedRole)) {
      return {
        ids: isStaffSenior
          ? ['gemini-3.8-flash', 'deepseek-chat', 'gemini-flash-latest']
          : ['gemini-3.8-flash', 'deepseek-chat', 'gemini-flash-latest'],
        reasonKey: 'support',
      }
    }
    return defaults
  })()

  const ordered = pickModels(models, plan.ids)
  return {
    primary: ordered[0] ?? null,
    alternatives: ordered.slice(1, 4),
    reasonKey: plan.reasonKey,
  }
}

function tierClass(tier?: string): string {
  return TIER_META[tier || 'balanced'] || 'bg-surface-700 text-gray-300'
}

function groupedTiers(models: ModelCatalogEntry[]): string[] {
  return [...new Set(models.map(model => model.tier))]
}

function formatRelativeTime(iso: string | null, t: (k: string, opts?: Record<string, unknown>) => string): string {
  if (!iso) return t('agentsConfig.never')
  const date = new Date(iso)
  const diffMs = Date.now() - date.getTime()
  if (Number.isNaN(diffMs)) return t('agentsConfig.never')
  if (diffMs < 60_000) return t('agentsConfig.timeJustNow')
  if (diffMs < 3_600_000) return t('agentsConfig.timeMinutesAgo', { n: Math.floor(diffMs / 60_000) })
  if (diffMs < 86_400_000) return t('agentsConfig.timeHoursAgo', { n: Math.floor(diffMs / 3_600_000) })
  if (diffMs < 30 * 86_400_000) return t('agentsConfig.timeDaysAgo', { n: Math.floor(diffMs / 86_400_000) })
  return date.toLocaleDateString()
}

function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return '—'
  if (usd === 0) return '$0'
  if (usd < 0.01) return '<$0.01'
  return `$${usd.toFixed(2)}`
}

function ActivityRow({
  activity,
  className = '',
}: {
  activity: AgentActivity | undefined
  className?: string
}) {
  const { t } = useTranslation()
  if (!activity || activity.total_tasks === 0) {
    return (
      <div className={`flex items-center gap-2 text-[11px] text-gray-500 ${className}`}>
        <span>•</span>
        <span>{t('agentsConfig.noActivity')}</span>
      </div>
    )
  }
  return (
    <div className={`flex items-center gap-3 text-[11px] text-gray-400 flex-wrap ${className}`}>
      <span className="font-mono text-gray-300">
        {activity.total_tasks} {activity.total_tasks === 1 ? t('agentsConfig.taskSingular') : t('agentsConfig.taskPlural')}
      </span>
      <span className="text-gray-600">·</span>
      <span className="font-mono text-gray-300">{formatCost(activity.total_cost_usd)}</span>
      <span className="text-gray-600">·</span>
      <span>{formatRelativeTime(activity.last_run_at, t)}</span>
      {activity.last_model && (
        <>
          <span className="text-gray-600">·</span>
          <span className="font-mono text-gray-500">{activity.last_model}</span>
        </>
      )}
    </div>
  )
}

function ModelRecommendationPanel({
  recommendation,
  activeModelId,
  onApply,
}: {
  recommendation: Recommendation
  activeModelId: string
  onApply: (modelId: string) => void
}) {
  const { t } = useTranslation()

  if (!recommendation.primary) {
    return (
      <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-200">
        {t('agentsConfig.noRecommendation')}
      </div>
    )
  }

  const primary = recommendation.primary
  const isActive = activeModelId === primary.id

  return (
    <div className="rounded-lg border border-brand-500/20 bg-brand-500/5 p-3 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-brand-300">
            {t('agentsConfig.recommendedModel')}
          </p>
          <div className="mt-1 flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm text-white">{primary.id}</span>
            <span className={`rounded-full px-2 py-0.5 text-[10px] ${tierClass(primary.tier)}`}>
              {primary.provider} · {primary.tier}
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-400">
            {t(`agentsConfig.recommendationReasons.${recommendation.reasonKey}`)}
          </p>
        </div>
        <button
          type="button"
          onClick={() => onApply(primary.id)}
          disabled={isActive}
          className="rounded-lg border border-brand-500/30 bg-brand-500/10 px-2.5 py-1.5 text-[11px] font-semibold text-brand-200 disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-1">
            <Sparkles size={12} />
            {isActive ? t('agentsConfig.recommendationApplied') : t('agentsConfig.applyRecommendation')}
          </span>
        </button>
      </div>

      {recommendation.alternatives.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span className="text-gray-500">{t('agentsConfig.alternatives')}</span>
          {recommendation.alternatives.map(model => (
            <button
              key={model.id}
              type="button"
              onClick={() => onApply(model.id)}
              className="rounded-full border border-surface-700 bg-surface-800 px-2 py-0.5 text-gray-300 hover:border-surface-600"
            >
              {model.id}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function ModelSelector({
  draft,
  setDraft,
  models,
}: {
  draft: AgentDraft
  setDraft: React.Dispatch<React.SetStateAction<AgentDraft>>
  models: ModelCatalogEntry[]
}) {
  const { t } = useTranslation()
  const modelInfo = models.find(model => model.id === draft.model)
  const recommendation = useMemo(
    () => recommendModelForRole(models, draft.role, draft.seniority),
    [models, draft.role, draft.seniority],
  )

  return (
    <div className="space-y-3">
      <ModelRecommendationPanel
        recommendation={recommendation}
        activeModelId={draft.model}
        onApply={(modelId) => setDraft(prev => ({ ...prev, model: modelId }))}
      />

      <div>
        <label className="input-label">{t('agentsConfig.model')}</label>
        <select
          className="select w-full text-xs"
          aria-label={t('agentsConfig.model')}
          value={draft.model}
          onChange={e => setDraft(prev => ({ ...prev, model: e.target.value }))}
        >
          <option value="">{t('agentsConfig.defaultForRole', { defaultValue: 'Default for role' })}</option>
          {draft.model && !modelInfo && (
            <option value={draft.model}>
              {t('agentsConfig.modelNotInCatalog', { model: draft.model, defaultValue: '{{model}} (not in catalog)' })}
            </option>
          )}
          {groupedTiers(models).map(tier => {
            const group = models.filter(model => model.tier === tier)
            if (!group.length) return null
            return (
              <optgroup key={tier} label={tier}>
                {group.map(model => (
                  <option key={model.id} value={model.id}>{model.id} ({model.provider})</option>
                ))}
              </optgroup>
            )
          })}
        </select>
        {modelInfo ? (
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <span className={`rounded-full px-2 py-0.5 text-[10px] ${tierClass(modelInfo.tier)}`}>
              {modelInfo.provider} · {modelInfo.tier}
            </span>
            <span className="text-[11px] text-gray-500">{modelInfo.description}</span>
          </div>
        ) : draft.model ? (
          <p className="mt-2 text-[11px] text-amber-300">{t('agentsConfig.customModelHint')}</p>
        ) : (
          <p className="mt-2 text-[11px] text-gray-500">
            {t('agentsConfig.defaultForRoleHint', { defaultValue: "Uses the server's default model for this role." })}
          </p>
        )}
      </div>
    </div>
  )
}

function DraftFields({
  draft,
  setDraft,
  models,
}: {
  draft: AgentDraft
  setDraft: React.Dispatch<React.SetStateAction<AgentDraft>>
  models: ModelCatalogEntry[]
}) {
  const { t } = useTranslation()
  const generatePrompt = useGenerateAgentPrompt()
  const roleOptions = COMMON_ROLES.includes(draft.role) ? COMMON_ROLES : [draft.role, ...COMMON_ROLES]

  function handleRoleChange(nextRole: string) {
    setDraft(prev => {
      const recommendation = recommendModelForRole(models, nextRole, prev.seniority)
      // An empty model stays "Default for role"; only an auto-picked one is replaced.
      const shouldAutoRecommend = AUTO_RECOMMENDED_MODEL_IDS.has(prev.model)
      return {
        ...prev,
        role: nextRole,
        model: shouldAutoRecommend ? (recommendation.primary?.id || prev.model) : prev.model,
      }
    })
  }

  function handleSeniorityChange(nextSeniority: string) {
    setDraft(prev => {
      const recommendation = recommendModelForRole(models, prev.role, nextSeniority)
      // An empty model stays "Default for role"; only an auto-picked one is replaced.
      const shouldAutoRecommend = AUTO_RECOMMENDED_MODEL_IDS.has(prev.model)
      return {
        ...prev,
        seniority: nextSeniority,
        model: shouldAutoRecommend ? (recommendation.primary?.id || prev.model) : prev.model,
      }
    })
  }

  function handleGeneratePrompt() {
    generatePrompt.mutate(
      { role: draft.role, seniority: draft.seniority, specialty: draft.specialty, persona: draft.persona },
      { onSuccess: (res) => setDraft(prev => ({ ...prev, system_prompt: res.system_prompt })) },
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div>
          <label className="input-label">{t('agentsConfig.name')}</label>
          <input
            className="input w-full"
            value={draft.name}
            onChange={e => setDraft(prev => ({ ...prev, name: e.target.value }))}
            placeholder={t('agentsConfig.name')}
          />
        </div>
        <div>
          <label className="input-label">{t('agentsConfig.role')}</label>
          <select
            className="select w-full"
            value={draft.role}
            onChange={e => handleRoleChange(e.target.value)}
          >
            {roleOptions.map(role => <option key={role} value={role}>{role}</option>)}
          </select>
        </div>
        <div>
          <label className="input-label">{t('agentsConfig.seniority')}</label>
          <select
            className="select w-full"
            value={draft.seniority}
            onChange={e => handleSeniorityChange(e.target.value)}
          >
            {SENIORITIES.map(level => <option key={level} value={level}>{level}</option>)}
          </select>
        </div>
        <div>
          <label className="input-label">{t('agentsConfig.specialty')}</label>
          <input
            className="input w-full"
            value={draft.specialty}
            onChange={e => setDraft(prev => ({ ...prev, specialty: e.target.value }))}
            placeholder={t('agentsConfig.specialty')}
          />
        </div>
      </div>

      <ModelSelector draft={draft} setDraft={setDraft} models={models} />

      <div>
        <label className="input-label">{t('agentsConfig.persona')}</label>
        <textarea
          className="textarea w-full"
          rows={2}
          value={draft.persona}
          onChange={e => setDraft(prev => ({ ...prev, persona: e.target.value }))}
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="input-label mb-0">{t('agentsConfig.systemPrompt')}</label>
          <button
            type="button"
            onClick={handleGeneratePrompt}
            disabled={generatePrompt.isPending || !draft.role.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-brand-500/30 bg-brand-500/10 px-2.5 py-1 text-[11px] font-semibold text-brand-200 disabled:opacity-50 hover:bg-brand-500/20 transition-colors"
          >
            {generatePrompt.isPending
              ? <><Loader2 size={11} className="animate-spin" />{t('agentsConfig.generatingPrompt')}</>
              : <><Wand2 size={11} />{t('agentsConfig.generatePrompt')}</>
            }
          </button>
        </div>
        <textarea
          className="textarea w-full font-mono text-xs"
          rows={4}
          value={draft.system_prompt}
          onChange={e => setDraft(prev => ({ ...prev, system_prompt: e.target.value }))}
          placeholder={t('agentsConfig.systemPromptPlaceholder')}
        />
        {generatePrompt.isError && (
          <p className="mt-1 text-[11px] text-red-400">{t('agentsConfig.generatePromptError')}</p>
        )}
      </div>

      <div>
        <label className="input-label">{t('agentsConfig.tokenBudget')}</label>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={100000}
            max={5000000}
            step={100000}
            className="flex-1 accent-brand-500"
            value={draft.token_budget}
            onChange={e => setDraft(prev => ({ ...prev, token_budget: Number(e.target.value) }))}
          />
          <span className="w-24 text-right text-xs font-mono text-brand-300">{Math.round(draft.token_budget / 1000)}K</span>
        </div>
      </div>
    </div>
  )
}

function AgentCard({
  agent,
  models,
  saving,
  deleting,
  expanded,
  confirmingDelete,
  readOnly,
  onToggleExpand,
  onSave,
  onDelete,
  onDuplicate,
}: {
  agent: ManagedAgent
  models: ModelCatalogEntry[]
  saving: boolean
  deleting: boolean
  expanded: boolean
  confirmingDelete: boolean
  readOnly: boolean
  onToggleExpand: () => void
  onSave: (agentId: number, draft: AgentDraft) => void
  onDelete: (agentId: number) => void
  onDuplicate: (agent: ManagedAgent) => void
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<AgentDraft>(() => draftFromAgent(agent))

  useEffect(() => {
    setDraft(draftFromAgent(agent))
  }, [agent])

  const dirty = isDraftDirty(draft, agent)
  const modelInfo = models.find(model => model.id === agent.model)

  return (
    <div className={`rounded-xl border ${expanded ? 'border-brand-500/40' : 'border-surface-700'} bg-surface-900 overflow-hidden transition-colors`}>
      <button
        type="button"
        onClick={onToggleExpand}
        className="w-full flex items-start gap-3 p-3.5 text-left hover:bg-surface-800/40 transition-colors"
      >
        <ChevronRight
          size={16}
          className={`mt-0.5 flex-shrink-0 text-gray-500 transition-transform ${expanded ? 'rotate-90 text-brand-400' : ''}`}
        />
        <Bot size={16} className="mt-0.5 flex-shrink-0 text-brand-400" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-gray-100 truncate">
              {agent.name || t('agentsConfig.unnamedAgent')}
            </span>
            <span className="rounded-full border border-surface-700 bg-surface-800 px-2 py-0.5 text-[10px] text-gray-300">
              {agent.role || '—'}
            </span>
            <span className="text-[10px] text-gray-500">{agent.seniority}</span>
            <span className="text-gray-700">·</span>
            <span className="font-mono text-[11px] text-gray-400 truncate">{agent.model || '—'}</span>
            {modelInfo && (
              <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${tierClass(modelInfo.tier)}`}>
                {modelInfo.tier}
              </span>
            )}
            {dirty && (
              <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                {t('agentsConfig.unsaved')}
              </span>
            )}
          </div>
          <ActivityRow activity={agent.activity} className="mt-1.5" />
        </div>
        {!readOnly && <div
          className="flex items-center gap-1 flex-shrink-0"
          onClick={e => e.stopPropagation()}
          role="presentation"
        >
          <button
            type="button"
            onClick={() => onDuplicate(agent)}
            title={t('agentsConfig.duplicateTooltip')}
            className="rounded-lg border border-surface-700 bg-surface-800 px-2 py-1 text-[11px] text-gray-300 hover:bg-surface-700 transition-colors"
          >
            <span className="inline-flex items-center gap-1"><Copy size={12} /> {t('agentsConfig.duplicate')}</span>
          </button>
          <button
            type="button"
            onClick={() => onDelete(agent.id)}
            disabled={deleting}
            className={`rounded-lg border px-2 py-1 text-[11px] disabled:opacity-50 transition-colors ${
              confirmingDelete
                ? 'border-red-500 bg-red-500/20 text-red-200'
                : 'border-red-500/20 bg-red-500/5 text-red-300 hover:bg-red-500/10'
            }`}
          >
            <span className="inline-flex items-center gap-1">
              <Trash2 size={12} />
              {confirmingDelete ? t('agentsConfig.deleteConfirm') : t('agentsConfig.delete')}
            </span>
          </button>
        </div>}
      </button>

      {expanded && (
        <div className="border-t border-surface-800 p-4 space-y-4 bg-surface-900/40">
          <fieldset disabled={readOnly} className="min-w-0">
            <DraftFields draft={draft} setDraft={setDraft} models={models} />
          </fieldset>

          {!readOnly && <div className="flex items-center justify-between gap-3">
            <span className={`text-[11px] ${dirty ? 'text-amber-300' : 'text-gray-500'}`}>
              {dirty ? t('agentsConfig.dirtyHint') : t('agentsConfig.cleanHint')}
            </span>
            <div className="flex items-center gap-2">
              {dirty && (
                <button
                  type="button"
                  onClick={() => setDraft(draftFromAgent(agent))}
                  className="rounded-lg border border-surface-700 bg-surface-800 px-3 py-2 text-xs text-gray-300 hover:bg-surface-700"
                >
                  {t('agentsConfig.discard')}
                </button>
              )}
              <button
                type="button"
                onClick={() => onSave(agent.id, draft)}
                disabled={saving || !dirty}
                className={`rounded-lg px-3 py-2 text-xs font-semibold disabled:opacity-50 transition-colors ${
                  dirty ? 'bg-brand-600 text-white hover:bg-brand-500' : 'bg-surface-700 text-gray-400'
                }`}
              >
                <span className="inline-flex items-center gap-1.5">
                  {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                  {saving ? t('agentsConfig.saving') : t('agentsConfig.save')}
                </span>
              </button>
            </div>
          </div>}
        </div>
      )}
    </div>
  )
}

// Stable role ordering: known roles in canonical order, then alphabetical for the rest.
function sortRoles(roles: string[]): string[] {
  const ordered = ROLE_DISPLAY_ORDER.filter(r => roles.includes(r))
  const remaining = roles.filter(r => !ROLE_DISPLAY_ORDER.includes(r)).sort()
  return [...ordered, ...remaining]
}

export default function AgentSettings() {
  const { t } = useTranslation()
  const toast = useToast()
  const companyId = useAppStore(state => state.companyId)
  const companyName = useAppStore(state => state.companyName)
  const companies = companyId ? [{ id: companyId, company_name: companyName ?? '' }] : []
  const selectCompany = (_id: number) => {}
  const { data, isLoading, isError, refetch } = useAgents(companyId)
  const { data: modelsData } = useModels()
  const createAgent = useCreateAgent(companyId)
  const updateAgent = useUpdateAgentConfig(companyId)
  const deleteAgent = useDeleteAgent(companyId)
  // A Viewer reads the agents; only a Manager or the Owner changes them (the
  // backend refuses the rest). Without a login, as in a local demo, nothing is hidden.
  const readOnly = useCurrentRole() === 'Viewer'

  const [newAgent, setNewAgent] = useState<AgentDraft>(defaultDraft())
  const [creatorOpen, setCreatorOpen] = useState(false)
  // Bumped to bring the creator into view once it has rendered; an effect
  // instead of a timer, so nothing runs after the page unmounts.
  const [creatorScrollRequest, setCreatorScrollRequest] = useState(0)
  useEffect(() => {
    if (creatorScrollRequest === 0) return
    document.getElementById('agent-creator')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }, [creatorScrollRequest])
  const [searchQuery, setSearchQuery] = useState('')
  const [activeRoleFilter, setActiveRoleFilter] = useState<string | null>(null)
  const [expandedAgents, setExpandedAgents] = useState<Set<number>>(() => new Set())
  const [collapsedRoles, setCollapsedRoles] = useState<Set<string>>(() => new Set())
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<number | null>(null)
  const confirmTimeoutRef = useRef<number | null>(null)

  const models = useMemo(() => modelsData?.models || [], [modelsData?.models])
  const orchestrator = modelsData?.orchestrator
  const allAgents = useMemo(() => data?.agents ?? [], [data?.agents])

  // Auto-recommend model on creator role/seniority change.
  useEffect(() => {
    if (!models.length) return
    setNewAgent(prev => {
      const recommendation = recommendModelForRole(models, prev.role, prev.seniority)
      if (!recommendation.primary) return prev
      if (AUTO_RECOMMENDED_MODEL_IDS.has(prev.model)) {
        return { ...prev, model: recommendation.primary.id }
      }
      return prev
    })
  }, [models])

  // Cleanup confirm-delete timer on unmount.
  useEffect(() => {
    return () => {
      if (confirmTimeoutRef.current !== null) window.clearTimeout(confirmTimeoutRef.current)
    }
  }, [])

  // Build per-role counts before applying search/filter so chips show totals.
  const roleCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const agent of allAgents) {
      const role = agent.role || 'Other'
      counts.set(role, (counts.get(role) ?? 0) + 1)
    }
    return counts
  }, [allAgents])

  // Apply role filter then text search.
  const visibleAgents = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return allAgents.filter(agent => {
      if (activeRoleFilter && agent.role !== activeRoleFilter) return false
      if (!q) return true
      const haystack = [
        agent.name,
        agent.role,
        agent.specialty,
        agent.model,
        agent.seniority,
        agent.activity?.last_model,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(q)
    })
  }, [allAgents, activeRoleFilter, searchQuery])

  const groupedByRole = useMemo(() => {
    const groups: Record<string, ManagedAgent[]> = {}
    for (const agent of visibleAgents) {
      const role = agent.role || 'Other'
      if (!groups[role]) groups[role] = []
      groups[role].push(agent)
    }
    return groups
  }, [visibleAgents])

  const orderedRoles = useMemo(() => sortRoles(Object.keys(groupedByRole)), [groupedByRole])

  function toggleAgentExpand(agentId: number) {
    setExpandedAgents(prev => {
      const next = new Set(prev)
      if (next.has(agentId)) next.delete(agentId)
      else next.add(agentId)
      return next
    })
  }

  function toggleRoleCollapse(role: string) {
    setCollapsedRoles(prev => {
      const next = new Set(prev)
      if (next.has(role)) next.delete(role)
      else next.add(role)
      return next
    })
  }

  function handleCreate() {
    if (!companyId) return
    createAgent.mutate({
      company_id: companyId,
      ...newAgent,
    }, {
      onSuccess: () => {
        setNewAgent(defaultDraft())
        setCreatorOpen(false)
        toast.success(t('agentsConfig.createSuccess'))
      },
      onError: (err) => toast.error(err instanceof Error ? err.message : t('agentsConfig.createError')),
    })
  }

  function handleSave(agentId: number, draft: AgentDraft) {
    updateAgent.mutate({ agentId, data: draft }, {
      onSuccess: () => toast.success(t('agentsConfig.saveSuccess')),
      onError: (err) => toast.error(err instanceof Error ? err.message : t('agentsConfig.saveError')),
    })
  }

  // Two-step delete: first click arms the button, second click confirms within 3s.
  function handleDeleteRequest(agentId: number) {
    if (confirmingDeleteId === agentId) {
      // Confirm.
      if (confirmTimeoutRef.current !== null) {
        window.clearTimeout(confirmTimeoutRef.current)
        confirmTimeoutRef.current = null
      }
      setConfirmingDeleteId(null)
      deleteAgent.mutate(agentId, {
        onSuccess: () => toast.success(t('agentsConfig.deleteSuccess')),
        onError: (err) => toast.error(err instanceof Error ? err.message : t('agentsConfig.deleteError')),
      })
      return
    }
    // Arm.
    setConfirmingDeleteId(agentId)
    if (confirmTimeoutRef.current !== null) window.clearTimeout(confirmTimeoutRef.current)
    confirmTimeoutRef.current = window.setTimeout(() => {
      setConfirmingDeleteId(prev => (prev === agentId ? null : prev))
      confirmTimeoutRef.current = null
    }, 3000)
  }

  function handleDuplicate(agent: ManagedAgent) {
    setNewAgent({
      ...draftFromAgent(agent),
      name: agent.name ? `${agent.name} ${t('agentsConfig.duplicateSuffix')}` : '',
    })
    setCreatorOpen(true)
    setCreatorScrollRequest(n => n + 1)
  }

  const filterChips = useMemo(() => sortRoles([...roleCounts.keys()]), [roleCounts])

  return (
    <div className="min-h-full bg-surface-950 p-4 lg:p-6">
      <div className="max-w-6xl mx-auto space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-xl font-bold text-white">{t('agentsConfig.title')}</h1>
            <p className="text-sm text-gray-500 mt-1">
              {companyName ? t('agentsConfig.subtitleWithCompany', { company: companyName }) : t('agentsConfig.subtitle')}
            </p>
          </div>
          <div className="flex items-stretch gap-3 flex-wrap">
            <div className="rounded-xl border border-surface-700 bg-surface-900 px-4 py-3 text-xs text-gray-400 min-w-[14rem]">
              <label className="flex items-center gap-2"><Users size={14} className="text-brand-400" /> {t('agentsConfig.factory')}</label>
              <select
                className="select mt-2 w-full text-sm"
                value={companyId ?? ''}
                onChange={e => selectCompany(Number(e.target.value))}
                disabled={!companies.length}
              >
                {companies.map(company => (
                  <option key={company.id} value={company.id}>{company.company_name}</option>
                ))}
              </select>
            </div>
            <div className="rounded-xl border border-surface-700 bg-surface-900 px-4 py-3 text-xs text-gray-400">
              <div className="flex items-center gap-2"><Cpu size={14} className="text-brand-400" /> {t('agentsConfig.orchestrator')}</div>
              <div className="mt-1 font-mono text-gray-200">{orchestrator || '—'}</div>
            </div>
          </div>
        </div>

        {!companies.length ? (
          <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm text-amber-200">
            {t('agentsConfig.noCompany')}
          </div>
        ) : (
          <>
            <div className="rounded-xl border border-brand-700/20 bg-brand-950/10 p-4 text-sm text-gray-300">
              <p className="font-medium text-brand-200">{t('agentsConfig.runtimeNoteTitle')}</p>
              <p className="mt-1">{t('agentsConfig.runtimeNote')}</p>
              <p className="mt-2 text-xs text-gray-500">{t('agentsConfig.shardingNote')}</p>
            </div>

            {readOnly && (
              <p role="status" className="rounded-xl border border-surface-700 bg-surface-900 p-3 text-xs text-gray-400">
                {t('agentsConfig.readOnly', { defaultValue: 'You can read the agents. Only a Manager or the Owner changes them.' })}
              </p>
            )}

            {/* Toolbar: search + filter chips + new-agent button */}
            <div className="rounded-xl border border-surface-700 bg-surface-900 p-3 space-y-3">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="relative flex-1 min-w-[220px]">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                  <input
                    type="search"
                    className="input w-full pl-9"
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    placeholder={t('agentsConfig.searchPlaceholder')}
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => setSearchQuery('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-500 hover:text-gray-300"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => refetch()}
                  className="rounded-lg border border-surface-700 bg-surface-800 px-3 py-2 text-xs text-gray-300 hover:bg-surface-700"
                >
                  {t('agentsConfig.refresh')}
                </button>
                {!readOnly && (
                  <button
                    type="button"
                    onClick={() => {
                      setNewAgent(defaultDraft())
                      setCreatorOpen(o => !o)
                      if (!creatorOpen) setCreatorScrollRequest(n => n + 1)
                    }}
                    className="rounded-lg bg-brand-600 px-3 py-2 text-xs font-semibold text-white hover:bg-brand-500"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Plus size={12} />
                      {creatorOpen ? t('agentsConfig.closeCreator') : t('agentsConfig.newAgent')}
                    </span>
                  </button>
                )}
              </div>

              {filterChips.length > 0 && (
                <div className="flex items-center gap-1.5 flex-wrap">
                  <button
                    type="button"
                    onClick={() => setActiveRoleFilter(null)}
                    className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                      activeRoleFilter === null
                        ? 'bg-brand-500/20 text-brand-200 border border-brand-500/40'
                        : 'border border-surface-700 bg-surface-800 text-gray-400 hover:text-gray-200'
                    }`}
                  >
                    {t('agentsConfig.filterAll')} <span className="opacity-60">{allAgents.length}</span>
                  </button>
                  {filterChips.map(role => (
                    <button
                      key={role}
                      type="button"
                      onClick={() => setActiveRoleFilter(prev => (prev === role ? null : role))}
                      className={`rounded-full px-2.5 py-1 text-[11px] font-semibold transition-colors ${
                        activeRoleFilter === role
                          ? 'bg-brand-500/20 text-brand-200 border border-brand-500/40'
                          : 'border border-surface-700 bg-surface-800 text-gray-400 hover:text-gray-200'
                      }`}
                    >
                      {role} <span className="opacity-60">{roleCounts.get(role)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* New-agent creator */}
            {creatorOpen && !readOnly && (
              <div id="agent-creator" className="rounded-xl border border-brand-500/30 bg-surface-900 p-4 space-y-4">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Plus size={16} className="text-brand-400" />
                    <h2 className="text-sm font-semibold text-gray-100">{t('agentsConfig.addAgent')}</h2>
                  </div>
                  <button
                    type="button"
                    onClick={() => setCreatorOpen(false)}
                    className="rounded p-1 text-gray-500 hover:text-gray-300"
                    aria-label={t('agentsConfig.closeCreator')}
                  >
                    <X size={14} />
                  </button>
                </div>

                <DraftFields draft={newAgent} setDraft={setNewAgent} models={models} />

                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setNewAgent(defaultDraft())
                      setCreatorOpen(false)
                    }}
                    className="rounded-lg border border-surface-700 bg-surface-800 px-3 py-2 text-xs text-gray-300"
                  >
                    {t('agentsConfig.cancel')}
                  </button>
                  <button
                    type="button"
                    onClick={handleCreate}
                    disabled={createAgent.isPending || !newAgent.role.trim()}
                    className="rounded-lg bg-brand-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50 hover:bg-brand-500"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      {createAgent.isPending ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                      {t('agentsConfig.create')}
                    </span>
                  </button>
                </div>
              </div>
            )}

            {/* List header with count */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-gray-300">
                <Users size={16} className="text-brand-400" />
                <span>{t('agentsConfig.currentAgents')}</span>
                <span className="rounded-full bg-surface-800 px-2 py-0.5 text-xs text-gray-400">
                  {visibleAgents.length}
                  {(activeRoleFilter || searchQuery) && allAgents.length !== visibleAgents.length && (
                    <span className="text-gray-600"> / {allAgents.length}</span>
                  )}
                </span>
              </div>
            </div>

            {isLoading ? (
              <div className="text-sm text-gray-500">{t('agentsConfig.loading')}</div>
            ) : isError ? (
              <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-200">{t('agentsConfig.loadError')}</div>
            ) : visibleAgents.length === 0 ? (
              <div className="rounded-xl border border-surface-700 bg-surface-900 p-8 text-center text-sm text-gray-500">
                {(searchQuery || activeRoleFilter)
                  ? t('agentsConfig.emptyFiltered')
                  : t('agentsConfig.emptyNoAgents')}
              </div>
            ) : (
              <div className="space-y-5">
                {orderedRoles.map(role => {
                  const groupAgents = groupedByRole[role]
                  const isCollapsed = collapsedRoles.has(role)
                  return (
                    <section key={role}>
                      <button
                        type="button"
                        onClick={() => toggleRoleCollapse(role)}
                        className="w-full flex items-center gap-2 text-left mb-2.5 group"
                      >
                        <ChevronRight
                          size={14}
                          className={`text-gray-500 transition-transform group-hover:text-gray-300 ${isCollapsed ? '' : 'rotate-90'}`}
                        />
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                          {role}
                        </h3>
                        <span className="rounded-full bg-surface-800 px-2 py-0.5 text-[10px] text-gray-400">
                          {groupAgents.length}
                        </span>
                      </button>
                      {!isCollapsed && (
                        <div className="space-y-3">
                          {groupAgents.map(agent => (
                            <AgentCard
                              key={agent.id}
                              agent={agent}
                              models={models}
                              expanded={expandedAgents.has(agent.id)}
                              confirmingDelete={confirmingDeleteId === agent.id}
                              readOnly={readOnly}
                              saving={updateAgent.isPending && updateAgent.variables?.agentId === agent.id}
                              deleting={deleteAgent.isPending && deleteAgent.variables === agent.id}
                              onToggleExpand={() => toggleAgentExpand(agent.id)}
                              onSave={handleSave}
                              onDelete={handleDeleteRequest}
                              onDuplicate={handleDuplicate}
                            />
                          ))}
                        </div>
                      )}
                    </section>
                  )
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
