import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, Download, GitPullRequest, KeyRound, Loader2, Plug } from 'lucide-react'
import { useBackfillGitHub, useCapabilities, useCreateGitHubBinding, useCurrentRole } from '../hooks/useQueries'
import { API_BASE } from '../lib/apiBase'
import {
  ApiError,
  errorDetail,
  type GitHubBinding,
  type GitHubInclusionRule,
} from '../services/api'
import { useAppStore } from '../store/useAppStore'

const INCLUSION_RULES: GitHubInclusionRule[] = ['all', 'bots_only', 'non_bots']
const WEBHOOK_PATH = '/v1/integrations/github/webhook'

/** A random webhook secret (32 bytes, hex). */
export function generateWebhookSecret(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

/**
 * GitHub integration: bind a repository so its pull requests are recorded as
 * evidence through the webhook, and import past pull requests (Manager).
 * The API has no endpoint that lists existing bindings.
 */
export default function GitHubIntegration() {
  const { t } = useTranslation()
  const companyId = useAppStore(state => state.companyId)
  const role = useCurrentRole()
  const canManage = role === 'Owner' || role === 'Manager'

  return (
    <div className="page-container max-w-3xl space-y-6">
      <div className="page-header">
        <div>
          <div className="flex items-center gap-2">
            <GitPullRequest className="text-brand-400" size={22} />
            <h1 className="page-title">{t('github.title', { defaultValue: 'GitHub integration' })}</h1>
          </div>
          <p className="text-gray-400 mt-1">
            {t('github.subtitle', { defaultValue: "Record each pull request of a repository as an agent run, verified like any other evidence." })}
          </p>
        </div>
      </div>
      {!canManage || companyId === null ? (
        <div role="status" className="card p-4 text-sm text-gray-300">
          {t('github.managerOnly', { role: role ?? '—', defaultValue: 'Connecting repositories requires the Manager or Owner role. Your role here is {{role}}.' })}
        </div>
      ) : (
        <>
          <BindingForm companyId={companyId} />
          <BackfillForm companyId={companyId} />
        </>
      )}
    </div>
  )
}

function BindingForm({ companyId }: { companyId: number }) {
  const { t } = useTranslation()
  const bind = useCreateGitHubBinding()
  const [owner, setOwner] = useState('')
  const [repo, setRepo] = useState('')
  const [secret, setSecret] = useState(() => generateWebhookSecret())
  const [rule, setRule] = useState<GitHubInclusionRule>('all')
  const [bound, setBound] = useState<{ binding: GitHubBinding; secret: string } | null>(null)

  function submit() {
    if (!owner.trim() || !repo.trim() || !secret.trim()) return
    const webhookSecret = secret.trim()
    setBound(null)
    bind.mutate(
      { company_id: companyId, owner: owner.trim(), repo: repo.trim(), webhook_secret: webhookSecret, inclusion_rule: rule },
      {
        onSuccess: binding => {
          setBound({ binding, secret: webhookSecret })
          setOwner('')
          setRepo('')
          setSecret(generateWebhookSecret())
        },
      },
    )
  }

  const errorMessage = bind.error instanceof ApiError && bind.error.status === 409
    ? t('github.alreadyBound', { defaultValue: 'That repository is already connected.' })
    : t('github.bindError', { message: errorDetail(bind.error), defaultValue: 'Could not connect the repository: {{message}}' })

  return (
    <section className="card p-4 space-y-4" aria-labelledby="bind-title">
      <h2 id="bind-title" className="flex items-center gap-2 text-sm font-semibold text-white">
        <Plug size={15} /> {t('github.bindTitle', { defaultValue: 'Connect a repository' })}
      </h2>
      <form onSubmit={e => { e.preventDefault(); submit() }} className="space-y-3">
        <RepoFields owner={owner} repo={repo} onOwner={setOwner} onRepo={setRepo} />
        <label className="block">
          <span className="input-label">{t('github.secret', { defaultValue: 'Webhook secret' })}</span>
          <div className="flex gap-2">
            <input value={secret} onChange={e => setSecret(e.target.value)} required className="input flex-1 font-mono text-xs" />
            <button type="button" onClick={() => setSecret(generateWebhookSecret())} className="btn btn-secondary btn-sm"
              title={t('github.newSecret', { defaultValue: 'Generate another secret' })}>
              <KeyRound size={14} />
            </button>
          </div>
        </label>
        <label className="block">
          <span className="input-label">{t('github.rule', { defaultValue: 'Pull requests to record' })}</span>
          <select value={rule} onChange={e => setRule(e.target.value as GitHubInclusionRule)} className="select w-full">
            {INCLUSION_RULES.map(value => (
              <option key={value} value={value}>{t(`github.rules.${value}`, { defaultValue: value })}</option>
            ))}
          </select>
        </label>
        <button type="submit" disabled={bind.isPending || !owner.trim() || !repo.trim() || !secret.trim()} className="btn btn-primary">
          {bind.isPending ? <Loader2 size={15} className="animate-spin" /> : <Plug size={15} />}
          {bind.isPending ? t('github.binding', { defaultValue: 'Connecting…' }) : t('github.bind', { defaultValue: 'Connect' })}
        </button>
        {bind.isError && (
          <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
            <span>{errorMessage}</span>
            <button type="button" onClick={submit} className="underline">{t('common.retry')}</button>
          </div>
        )}
      </form>
      {bound && <WebhookInstructions binding={bound.binding} secret={bound.secret} />}
    </section>
  )
}

function WebhookInstructions({ binding, secret }: { binding: GitHubBinding; secret: string }) {
  const { t } = useTranslation()
  const { data: capabilities } = useCapabilities()
  // PUBLIC_API_URL is where GitHub reaches the backend; without it, the
  // address this browser uses, which GitHub may not be able to reach.
  const publicUrl = capabilities?.public_api_url
  const payloadUrl = `${publicUrl || API_BASE}${WEBHOOK_PATH}`
  const settingsUrl = `https://github.com/${encodeURIComponent(binding.owner)}/${encodeURIComponent(binding.repo)}/settings/hooks/new`
  return (
    <div role="status" className="rounded-lg border border-emerald-700/50 bg-emerald-950/30 p-4 text-sm space-y-2">
      <p className="font-medium text-emerald-300">
        {t('github.bound', { repo: `${binding.owner}/${binding.repo}`, defaultValue: '{{repo}} is connected. Now add the webhook in GitHub:' })}
      </p>
      <ol className="list-decimal space-y-1 pl-5 text-gray-300">
        <li>
          <a href={settingsUrl} target="_blank" rel="noreferrer" className="text-brand-300 underline">
            {t('github.stepOpen', { defaultValue: 'Open the repository webhook settings' })}
          </a>
        </li>
        <li>{t('github.stepUrl', { defaultValue: 'Payload URL:' })} <CopyValue value={payloadUrl} /></li>
        <li>{t('github.stepType', { defaultValue: 'Content type: application/json' })}</li>
        <li>{t('github.stepSecret', { defaultValue: 'Secret (shown only now):' })} <CopyValue value={secret} /></li>
        <li>{t('github.stepEvents', { defaultValue: 'Events: "Pull requests".' })}</li>
      </ol>
      {!publicUrl && (
        <p className="text-xs text-gray-500">
          {t('github.publicUrlHint', { defaultValue: 'GitHub must be able to reach this URL. Set PUBLIC_API_URL in the backend to the public address (or a tunnel) and it will be used here.' })}
        </p>
      )}
    </div>
  )
}

function CopyValue({ value }: { value: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <span className="inline-flex max-w-full items-center gap-1 align-middle">
      <code className="break-all rounded bg-surface-900 px-1.5 py-0.5 font-mono text-xs text-gray-200">{value}</code>
      <button type="button" className="btn-ghost btn-icon"
        title={copied ? t('glassroom.copied') : t('glassroom.copy')}
        aria-label={copied ? t('glassroom.copied') : t('glassroom.copy')}
        onClick={() => { void navigator.clipboard?.writeText(value).then(() => setCopied(true)) }}>
        <Copy size={12} />
      </button>
    </span>
  )
}

function BackfillForm({ companyId }: { companyId: number }) {
  const { t } = useTranslation()
  const { data: capabilities } = useCapabilities()
  const backfill = useBackfillGitHub()
  const [owner, setOwner] = useState('')
  const [repo, setRepo] = useState('')
  const [since, setSince] = useState('')

  function submit() {
    if (!owner.trim() || !repo.trim()) return
    backfill.mutate({
      company_id: companyId,
      owner: owner.trim(),
      repo: repo.trim(),
      ...(since ? { since: new Date(`${since}T00:00:00Z`).toISOString() } : {}),
    })
  }

  const result = backfill.data
  const errorMessage = backfill.error instanceof ApiError && backfill.error.status === 404
    ? t('github.notBound', { defaultValue: 'Connect that repository first.' })
    : t('github.backfillError', { message: errorDetail(backfill.error), defaultValue: 'The import failed: {{message}}' })

  return (
    <section className="card p-4 space-y-4" aria-labelledby="backfill-title">
      <h2 id="backfill-title" className="flex items-center gap-2 text-sm font-semibold text-white">
        <Download size={15} /> {t('github.backfillTitle', { defaultValue: 'Import past pull requests' })}
      </h2>
      {capabilities && !capabilities.github && (
        <p className="text-xs text-amber-300">
          {t('github.noToken', { defaultValue: 'The backend has no GITHUB_TOKEN: only public repositories can be imported, with a low rate limit.' })}
        </p>
      )}
      <form onSubmit={e => { e.preventDefault(); submit() }} className="space-y-3">
        <RepoFields owner={owner} repo={repo} onOwner={setOwner} onRepo={setRepo} />
        <label className="block">
          <span className="input-label">{t('github.since', { defaultValue: 'Updated since (optional)' })}</span>
          <input type="date" value={since} onChange={e => setSince(e.target.value)} className="input" />
        </label>
        <button type="submit" disabled={backfill.isPending || !owner.trim() || !repo.trim()} className="btn btn-secondary">
          {backfill.isPending ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
          {backfill.isPending ? t('github.importing', { defaultValue: 'Importing…' }) : t('github.import', { defaultValue: 'Import' })}
        </button>
        {backfill.isError && (
          <div role="alert" className="alert-error flex flex-wrap items-center gap-2 text-sm">
            <span>{errorMessage}</span>
            <button type="button" onClick={submit} className="underline">{t('common.retry')}</button>
          </div>
        )}
      </form>
      {result && (
        <div role="status" className="text-sm text-gray-300 space-y-1">
          <p>{t('github.imported', { ingested: result.ingested, skipped: result.skipped, defaultValue: '{{ingested}} recorded, {{skipped}} already recorded or excluded.' })}</p>
          {result.errors.length > 0 && (
            <ul className="list-disc pl-5 text-xs text-red-300">
              {result.errors.map(error => (
                <li key={`${error.number}-${error.error}`}>
                  {t('github.importErrorItem', { number: error.number ?? '?', error: error.error, defaultValue: '#{{number}}: {{error}}' })}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

function RepoFields({ owner, repo, onOwner, onRepo }: {
  owner: string
  repo: string
  onOwner: (value: string) => void
  onRepo: (value: string) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block">
        <span className="input-label">{t('github.owner', { defaultValue: 'Owner (user or organization)' })}</span>
        <input value={owner} onChange={e => onOwner(e.target.value)} required className="input w-full"
          placeholder={t('github.ownerPlaceholder', { defaultValue: 'my-org' })} />
      </label>
      <label className="block">
        <span className="input-label">{t('github.repo', { defaultValue: 'Repository' })}</span>
        <input value={repo} onChange={e => onRepo(e.target.value)} required className="input w-full"
          placeholder={t('github.repoPlaceholder', { defaultValue: 'my-app' })} />
      </label>
    </div>
  )
}
