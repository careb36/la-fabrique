import React, { useState, useRef, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type SupportTicket } from '../services/api'
import { useAuthStore } from '../store/useAuthStore'
import { Bot, Bug, Send, X, Loader2, Ticket, ChevronRight, RefreshCw, CheckCircle2, Clock, AlertCircle, Circle } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

type Message  = { id: number; role: 'bot' | 'user'; text: string }
type View     = 'chat' | 'bug-form' | 'my-tickets' | 'ticket-detail'

type TicketSummary = SupportTicket

// ── Status config (Linear-style) ──────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { label_key: string; color: string; icon: React.ReactNode }> = {
  open:        { label_key: 'support.status.open',        color: 'bg-blue-100 text-blue-700',    icon: <Circle size={12} className="text-blue-500" /> },
  in_progress: { label_key: 'support.status.in_progress', color: 'bg-yellow-100 text-yellow-700',icon: <Clock size={12} className="text-yellow-500" /> },
  waiting:     { label_key: 'support.status.waiting',     color: 'bg-orange-100 text-orange-700',icon: <AlertCircle size={12} className="text-orange-500" /> },
  resolved:    { label_key: 'support.status.resolved',    color: 'bg-green-100 text-green-700',  icon: <CheckCircle2 size={12} className="text-green-500" /> },
  closed:      { label_key: 'support.status.closed',      color: 'bg-gray-100 text-gray-500',    icon: <CheckCircle2 size={12} className="text-gray-400" /> },
}

const SEVERITIES = ['critical', 'high', 'medium', 'low'] as const

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high:     'bg-orange-100 text-orange-700',
  medium:   'bg-yellow-100 text-yellow-700',
  low:      'bg-gray-100 text-gray-500',
}

// ── Component ─────────────────────────────────────────────────────────────────

export const SupportBot: React.FC = () => {
  const { t } = useTranslation()
  const [isOpen, setIsOpen]     = useState(false)
  const [view, setView]         = useState<View>('chat')

  // Draggable position (bottom-right default)
  const [pos, setPos] = useState({ x: 24, y: 24 })
  const dragging = useRef(false)
  const dragMoved = useRef(false)
  const dragOffset = useRef({ x: 0, y: 0 })
  const fabRef = useRef<HTMLDivElement>(null)

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('[data-chat-panel]')) return
    dragging.current = true
    dragMoved.current = false
    dragOffset.current = { x: e.clientX + pos.x, y: e.clientY + pos.y }
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }, [pos])

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return
    dragMoved.current = true
    const newX = dragOffset.current.x - e.clientX
    const newY = dragOffset.current.y - e.clientY
    const maxX = window.innerWidth - 56
    const maxY = window.innerHeight - 56
    setPos({
      x: Math.max(0, Math.min(newX, maxX)),
      y: Math.max(0, Math.min(newY, maxY)),
    })
  }, [])

  const onPointerUp = useCallback(() => { dragging.current = false }, [])

  // Chat
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput]       = useState('')
  const [isSending, setIsSending] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef    = useRef<HTMLTextAreaElement>(null)

  // Bug form
  const [title, setTitle]             = useState('')
  const [description, setDescription] = useState('')
  // Empty until the reporter picks one: a preset would pass for their choice.
  const [severity, setSeverity]       = useState<'' | 'low'|'medium'|'high'|'critical'>('')
  const [reporterEmail, setReporterEmail] = useState(
    () => localStorage.getItem('fabrique-support-email') || ''
  )
  const [submitting, setSubmitting]   = useState(false)

  // Tickets. A signed-in user sees the tickets reported with their account
  // email (support admins see any); the API answers 403 for another email.
  const accountEmail = useAuthStore(state => state.user?.email)
  const [email, setEmail] = useState(
    () => accountEmail || localStorage.getItem('fabrique-support-email') || ''
  )
  const [ticketsForbidden, setTicketsForbidden] = useState(false)
  // The profile can load after the bot mounts (login, first page load).
  useEffect(() => {
    if (accountEmail) setEmail(current => current || accountEmail)
  }, [accountEmail])
  const [tickets, setTickets]         = useState<TicketSummary[]>([])
  const [loadingTickets, setLoadingTickets] = useState(false)
  const [selectedTicket, setSelectedTicket] = useState<any>(null)

  // Reset greeting on language change
  useEffect(() => {
    setMessages([{ id: 0, role: 'bot', text: t('support.greeting') }])
  }, [t])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isSending])

  // ── Chat ──────────────────────────────────────────────────────────────────

  const addMsg = (role: 'bot' | 'user', text: string) =>
    setMessages(prev => [...prev, { id: Date.now() + Math.random(), role, text }])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isSending) return
    setInput('')
    addMsg('user', text)
    setIsSending(true)
    try {
      // The backend reads the whole conversation, oldest first, as `messages`.
      const res = await api.supportChat([
        ...messages.slice(-10).map(m => ({
          role: m.role === 'bot' ? 'assistant' as const : 'user' as const,
          content: m.text,
        })),
        { role: 'user', content: text },
      ])
      addMsg('bot', res?.reply || t('support.noResponse'))
    } catch {
      addMsg('bot', t('support.chatUnavailable'))
    } finally {
      setIsSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  // Auto-grow textarea
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }

  // Relative date formatter
  const { i18n } = useTranslation()
  function relativeDate(iso: string | null): string {
    if (!iso) return ''
    try {
      const diff = Date.now() - new Date(iso).getTime()
      const mins = Math.floor(diff / 60000)
      if (mins < 1)  return t('glassroom.justNow', 'just now')
      if (mins < 60) return t('glassroom.minutesAgo', '{{n}} min ago').replace('{{n}}', String(mins))
      const hrs = Math.floor(mins / 60)
      if (hrs < 24)  return t('glassroom.hoursAgo', '{{n}} h ago').replace('{{n}}', String(hrs))
      return new Intl.DateTimeFormat(i18n.language, { month: 'short', day: 'numeric' }).format(new Date(iso))
    } catch { return '' }
  }

  // ── Bug form submit ────────────────────────────────────────────────────────

  const handleSubmitBug = async () => {
    if (!title.trim() || !description.trim()) return
    setSubmitting(true)
    try {
      const res = await api.reportBug({
        title: title.trim(),
        description: description.trim(),
        severity: severity || undefined,
        reporter_email: reporterEmail.trim() || undefined,
        browser_info: {
          userAgent: navigator.userAgent,
          url: window.location.href,
          viewport: `${window.innerWidth}x${window.innerHeight}`,
        },
      })
      // Save email for ticket lookup
      if (reporterEmail.trim()) {
        localStorage.setItem('fabrique-support-email', reporterEmail.trim())
        setEmail(reporterEmail.trim())
      }
      // Reset form
      setTitle(''); setDescription(''); setSeverity(''); setReporterEmail('')
      // Return to chat with confirmation
      setView('chat')
      addMsg('bot',
        `✅ ${t('support.ticketCreated', { num: res.ticket_num })}\n\n` +
        `📋 ${t('support.ticketTrackHint')}`
      )
    } catch {
      addMsg('bot', t('common.error'))
      setView('chat')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Ticket list ────────────────────────────────────────────────────────────

  const loadTickets = async (emailOverride?: string) => {
    const q = (emailOverride || email).trim()
    if (!q) return
    setLoadingTickets(true)
    setTicketsForbidden(false)
    try {
      const res = await api.listTickets({ reporter_email: q })
      setTickets(res.tickets || [])
    } catch (error) {
      setTicketsForbidden(error instanceof ApiError && error.status === 403)
      setTickets([])
    } finally {
      setLoadingTickets(false)
    }
  }

  const loadTicketDetail = async (num: string) => {
    try {
      const res = await api.getTicket(num)
      setSelectedTicket(res)
      setView('ticket-detail')
    } catch { /* ignore */ }
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  const StatusBadge = ({ status }: { status: string }) => {
    const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.open
    return (
      <span className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full font-semibold ${cfg.color}`}>
        {cfg.icon} {t(cfg.label_key, status)}
      </span>
    )
  }

  const headerTitle = () => {
    if (view === 'bug-form')      return `🐞 ${t('support.reportBug')}`
    if (view === 'my-tickets')    return `🎫 ${t('support.myTickets')}`
    if (view === 'ticket-detail') return selectedTicket?.ticket_num ?? '...'
    return t('support.title')
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      ref={fabRef}
      className="fixed z-50"
      style={{ right: pos.x, bottom: pos.y }}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      <button
        onPointerDown={onPointerDown}
        onClick={() => { if (!dragMoved.current) setIsOpen(p => !p) }}
        className="w-14 h-14 bg-indigo-600 text-white rounded-full shadow-2xl flex items-center justify-center hover:bg-indigo-700 transition-all hover:scale-110 cursor-grab active:cursor-grabbing select-none touch-none"
        title={t('support.open')}>
        {isOpen ? <X size={24} /> : <Bot size={26} />}
      </button>

      {isOpen && (
        <div data-chat-panel className="absolute bottom-20 right-0 w-[min(320px,calc(100vw-2rem))] bg-white rounded-2xl shadow-2xl border border-gray-100 flex flex-col overflow-hidden max-h-[80vh]">

          {/* Header */}
          <div className="px-4 py-3 bg-indigo-600 text-white flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 min-w-0">
              {view !== 'chat' && (
                <button onClick={() => setView('chat')} className="hover:bg-indigo-500 p-0.5 rounded shrink-0">
                  <ChevronRight size={16} className="rotate-180" />
                </button>
              )}
              <div className="min-w-0">
                <h3 className="font-bold text-sm truncate">{headerTitle()}</h3>
                <p className="text-[11px] opacity-70">{t('support.online')}</p>
              </div>
            </div>
            <div className="flex gap-1 shrink-0">
              <button onClick={() => setView('bug-form')}
                className={`p-1.5 rounded transition-colors ${view==='bug-form' ? 'bg-red-500' : 'hover:bg-indigo-500'}`}
                title={t('support.reportBug')}><Bug size={15} /></button>
              <button onClick={() => { setView('my-tickets'); if (email) loadTickets() }}
                className={`p-1.5 rounded transition-colors ${view==='my-tickets'||view==='ticket-detail' ? 'bg-white/25' : 'hover:bg-indigo-500'}`}
                title={t('support.myTickets')}><Ticket size={15} /></button>
            </div>
          </div>

          {/* ── CHAT ──────────────────────────────────────────────────── */}
          {view === 'chat' && (<>
            <div className="h-56 p-3 overflow-y-auto bg-gray-50 flex flex-col gap-2">
              {messages.map(m => (
                <div key={m.id}
                  className={`max-w-[90%] px-3 py-2 rounded-xl text-sm leading-snug whitespace-pre-wrap break-words ${
                    m.role === 'bot'
                      ? 'bg-indigo-100 text-indigo-900 rounded-tl-none self-start'
                      : 'bg-indigo-600 text-white rounded-tr-none self-end'
                  }`}>{m.text}</div>
              ))}
              {isSending && (
                <div className="self-start bg-indigo-100 text-indigo-600 px-3 py-2 rounded-xl rounded-tl-none flex items-center gap-2">
                  <Loader2 size={13} className="animate-spin" /><span className="text-xs">{t('support.thinking')}</span>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
            <div className="p-3 border-t bg-white">
              <div className="flex gap-2 items-end">
                <textarea ref={textareaRef} value={input}
                  onChange={handleInputChange} onKeyDown={handleKeyDown}
                  placeholder={t('support.inputPlaceholder')} rows={2}
                  className="flex-1 p-2 border border-gray-200 rounded-lg text-sm resize-none focus:ring-2 focus:ring-indigo-400 outline-none" />
                <button onClick={handleSend} disabled={isSending || !input.trim()}
                  className="p-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 self-end">
                  <Send size={17} />
                </button>
              </div>
              <p className="text-[10px] text-gray-400 mt-1">{t('support.enterToSend')}</p>
            </div>
          </>)}

          {/* ── BUG FORM — simple, fast ─────────────────────────────── */}
          {view === 'bug-form' && (
            <div className="flex flex-col">
              <div className="p-4 space-y-3">
                <p className="text-xs text-gray-500">{t('support.form.hint')}</p>

                <label className="block">
                  <span className="text-xs font-semibold text-gray-600">{t('support.form.title')} *</span>
                  <input value={title} onChange={e => setTitle(e.target.value)}
                    placeholder={t('support.form.titlePlaceholder')}
                    className="mt-1 w-full p-2 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 outline-none" />
                </label>

                <label className="block">
                  <span className="text-xs font-semibold text-gray-600">{t('support.description')} *</span>
                  <textarea value={description} onChange={e => setDescription(e.target.value)}
                    placeholder={t('support.form.descPlaceholder')} rows={3}
                    className="mt-1 w-full p-2 border rounded-lg text-sm resize-none focus:ring-2 focus:ring-indigo-400 outline-none" />
                </label>

                <div className="flex gap-2">
                  <label className="flex-1">
                    <span className="text-xs font-semibold text-gray-600">{t('support.severity')}</span>
                    <select value={severity} onChange={e => setSeverity(e.target.value as any)}
                      className="mt-1 w-full p-2 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-indigo-400 bg-white">
                      <option value="">{t('support.severityNotSure', { defaultValue: 'Not sure' })}</option>
                      {SEVERITIES.map(s => (
                        <option key={s} value={s}>{t(`support.${s}`)}</option>
                      ))}
                    </select>
                  </label>
                </div>

                <label className="block">
                  <span className="text-xs font-semibold text-gray-600">{t('support.emailToTrack')}</span>
                  <input type="email" value={reporterEmail} onChange={e => setReporterEmail(e.target.value)}
                    placeholder={t('support.emailPlaceholder', { defaultValue: 'you@company.com' })}
                    className="mt-1 w-full p-2 border rounded-lg text-sm focus:ring-2 focus:ring-indigo-400 outline-none" />
                  <p className="text-[10px] text-gray-400 mt-0.5">{t('support.emailHint')}</p>
                </label>
              </div>

              <div className="px-4 pb-4 flex gap-2">
                <button onClick={() => setView('chat')}
                  className="flex-1 py-2 border rounded-lg text-sm hover:bg-gray-50">{t('common.cancel')}</button>
                <button onClick={handleSubmitBug}
                  disabled={submitting || !title.trim() || !description.trim()}
                  className="flex-1 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700 disabled:opacity-40 flex items-center justify-center gap-1.5">
                  {submitting && <Loader2 size={14} className="animate-spin" />}
                  {submitting ? t('support.submitting') : t('support.submit')}
                </button>
              </div>
            </div>
          )}

          {/* ── MY TICKETS — status tracking ───────────────────────── */}
          {view === 'my-tickets' && (
            <div className="flex flex-col h-[340px]">
              <div className="p-3 border-b flex gap-2">
                <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                  onKeyDown={e => e.key==='Enter' && loadTickets()}
                  placeholder={t('support.emailToSearch')}
                  className="flex-1 p-2 border rounded-lg text-sm outline-none focus:ring-2 focus:ring-indigo-400" />
                <button onClick={() => loadTickets()} disabled={!email.trim() || loadingTickets}
                  className="p-2 bg-indigo-600 text-white rounded-lg disabled:opacity-40">
                  {loadingTickets ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
                </button>
              </div>

              <div className="flex-1 overflow-y-auto divide-y">
                {!loadingTickets && tickets.length === 0 && (
                  <p className="text-xs text-gray-400 text-center mt-10 px-4">
                    {ticketsForbidden
                      ? t('support.ownTicketsOnly', { email: accountEmail ?? '', defaultValue: 'You can only see the tickets reported with your account email ({{email}}).' })
                      : t('support.noTickets')}
                  </p>
                )}
                {tickets.map(tk => (
                  <button key={tk.ticket_num} onClick={() => loadTicketDetail(tk.ticket_num)}
                    className="w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-mono font-bold text-indigo-600">{tk.ticket_num}</span>
                      <StatusBadge status={tk.status} />
                    </div>
                    <p className="text-sm text-gray-800 truncate">{tk.title}</p>
                    <p className="text-[10px] text-gray-400 mt-0.5">
                      {relativeDate(tk.updated_at)}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* ── TICKET DETAIL — what the user cares about ──────────── */}
          {view === 'ticket-detail' && selectedTicket && (
            <div className="overflow-y-auto max-h-[380px]">
              <div className="p-4 space-y-4">

                {/* Status — front and centre */}
                <div className="bg-gray-50 rounded-xl p-3 text-center">
                  <p className="text-[10px] text-gray-400 uppercase font-semibold mb-1">{t('support.currentStatus')}</p>
                  <StatusBadge status={selectedTicket.status} />
                  {selectedTicket.status === 'resolved' && selectedTicket.resolution && (
                    <div className="mt-2 bg-green-50 border border-green-200 rounded-lg p-2 text-left">
                      <p className="text-[10px] font-semibold text-green-700 uppercase">{t('support.resolution')}</p>
                      <p className="text-xs text-green-800 mt-0.5">{selectedTicket.resolution}</p>
                    </div>
                  )}
                </div>

                {/* Ticket info */}
                <div>
                  <p className="font-semibold text-gray-900 text-sm">{selectedTicket.title}</p>
                  <div className="flex gap-2 mt-1.5 flex-wrap">
                    {selectedTicket.severity && (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${SEVERITY_COLOR[selectedTicket.severity]}`}>
                        {selectedTicket.severity}
                      </span>
                    )}
                    {selectedTicket.category && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{selectedTicket.category}</span>
                    )}
                    {selectedTicket.assigned_to && (
                      <span className="text-[10px] text-gray-400">👤 {selectedTicket.assigned_to}</span>
                    )}
                  </div>
                </div>

                <p className="text-xs text-gray-600 leading-relaxed">{selectedTicket.description}</p>

                {selectedTicket.agent_reply && (
                  <div className="p-3 bg-indigo-50 rounded-lg">
                    <p className="text-[10px] font-semibold text-indigo-700 uppercase">{t('support.agentReply', { defaultValue: 'Reply from the Support agent' })}</p>
                    <p className="text-xs text-indigo-900 mt-0.5 whitespace-pre-wrap">{selectedTicket.agent_reply}</p>
                  </div>
                )}

                {/* Timeline */}
                <div className="border-t pt-3 space-y-2">
                  <p className="text-[10px] font-semibold text-gray-400 uppercase">{t('support.timeline')}</p>
                  <div className="space-y-1.5 text-[11px] text-gray-500">
                    <div className="flex gap-2 items-start">
                      <Circle size={10} className="text-indigo-400 mt-0.5 shrink-0" />
                      <span>{t('support.created')}: <span className="text-gray-700">{relativeDate(selectedTicket.created_at)}</span></span>
                    </div>
                    {selectedTicket.updated_at !== selectedTicket.created_at && (
                      <div className="flex gap-2 items-start">
                        <Clock size={10} className="text-yellow-400 mt-0.5 shrink-0" />
                        <span>{t('support.updated')}: <span className="text-gray-700">{relativeDate(selectedTicket.updated_at)}</span></span>
                      </div>
                    )}
                    {selectedTicket.resolved_at && (
                      <div className="flex gap-2 items-start">
                        <CheckCircle2 size={10} className="text-green-500 mt-0.5 shrink-0" />
                        <span>{t('support.resolved')}: <span className="text-gray-700">{new Date(selectedTicket.resolved_at).toLocaleString()}</span></span>
                      </div>
                    )}
                  </div>
                </div>

              </div>
            </div>
          )}

        </div>
      )}
    </div>
  )
}
