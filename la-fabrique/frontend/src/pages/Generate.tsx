import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAppStore } from '../store/useAppStore'
import { useGenerate } from '../hooks/useQueries'
import { Code2, Loader2, ArrowRight, CheckCircle2, Copy, Check } from 'lucide-react'

interface GenerateResult {
  interaction_id: string
  sprint_id?: number
  package_url?: string
}

export default function Generate() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const companyId = useAppStore(state => state.companyId)
  const companyName = useAppStore(state => state.companyName)
  const [story, setStory] = useState('')
  const [constraints, setConstraints] = useState('')
  const [result, setResult] = useState<GenerateResult | null>(null)
  const [copied, setCopied] = useState(false)

  const generateMutation = useGenerate()

  const loading = generateMutation.isPending
  const error = (generateMutation.error as any)?.message || null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!story.trim()) return
    
    generateMutation.mutate({
      company_id: companyId ?? 1,
      story: story.trim(),
      constraints: constraints.trim() || undefined
    }, {
      onSuccess: (res: GenerateResult) => {
        setResult(res)
        setStory('')
        setConstraints('')
      }
    })
  }

  async function copyId(text: string) {
    await navigator.clipboard.writeText(text).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="page-container max-w-3xl">
      <div className="page-header mb-8">
        <div className="flex items-center gap-2">
          <Code2 className="text-brand-400" size={22} />
          <h1 className="page-title">{t('generate.title', 'Generate')}</h1>
        </div>
        <p className="text-gray-400 mt-1">{t('generate.subtitle', 'Describe a feature and let the AI team build it')}</p>
      </div>

      {/* Success banner */}
      {result && (
        <div className="card border-l-4 border-l-status-success p-4 mb-6 animate-slide-up">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 size={16} className="text-status-success" />
            <span className="font-semibold text-white">{t('generate.started', 'Generation started!')}</span>
          </div>

          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-gray-500 w-32">{t('generate.interactionId', 'Interaction ID')}</span>
              <code className="font-mono text-brand-300 bg-surface-800 px-2 py-0.5 rounded text-xs flex-1 truncate">
                {result.interaction_id}
              </code>
              <button
                onClick={() => copyId(result.interaction_id)}
                className="btn-ghost btn-icon flex-shrink-0"
                title={t('common.copyId', 'Copy ID')}
              >
                {copied ? <Check size={13} className="text-status-success" /> : <Copy size={13} />}
              </button>
            </div>

            {result.sprint_id && (
              <div className="flex items-center gap-2 pt-2 border-t border-surface-700">
                <span className="text-gray-500 w-32">{t('generate.viewWorkspace', 'View workspace')}</span>
                <button
                  onClick={() => navigate(`/sprints/${result.sprint_id}/live`)}
                  className="btn btn-primary btn-sm flex items-center gap-1.5"
                >
                  {t('generate.sprintLink', { id: result.sprint_id, defaultValue: 'Sprint #{{id}}' })} <ArrowRight size={13} />
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="card p-6 space-y-5">
        {/* Company ID info */}
        <div className="flex items-center gap-2 text-xs text-gray-500 bg-surface-800 rounded-lg px-3 py-2">
          <span className="text-gray-400">{t('generate.companyId', 'Company')}:</span>
          <span className="font-mono text-brand-300">{companyName ?? `ID ${companyId ?? 1}`}</span>
        </div>

        {/* Story */}
        <div>
          <label className="input-label">{t('generate.story', 'Story / Feature request')} *</label>
          <textarea
            value={story}
            onChange={e => setStory(e.target.value)}
            required
            rows={6}
            placeholder={t('generate.storyPlaceholder', 'As a user, I want to...')}
            className="textarea w-full"
          />
          <p className="text-xs text-gray-600 mt-1">{t('generate.interactionHint', 'Be specific about the desired behavior and edge cases')}</p>
        </div>

        {/* Constraints */}
        <div>
          <label className="input-label">{t('generate.constraints', 'Constraints')} <span className="text-gray-600">{t('common.optional', { defaultValue: '(optional)' })}</span></label>
          <textarea
            value={constraints}
            onChange={e => setConstraints(e.target.value)}
            rows={3}
            placeholder={t('generate.constraintsPlaceholder', 'e.g. Must use PostgreSQL, no external APIs, TypeScript only')}
            className="textarea w-full"
          />
        </div>

        {error && <div className="alert-error">{error}</div>}

        <button
          type="submit"
          disabled={loading || !story.trim()}
          className="btn btn-primary w-full"
        >
          {loading ? <Loader2 size={15} className="animate-spin" /> : <Code2 size={15} />}
          {loading ? t('generate.generating', 'Generating…') : t('generate.generate', 'Generate')}
        </button>
      </form>
    </div>
  )
}
