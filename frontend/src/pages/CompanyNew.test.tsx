import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createInstance } from 'i18next'
import { I18nextProvider } from 'react-i18next'
import es from '../i18n/es.json'
import en from '../i18n/en.json'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useMutation } from '@tanstack/react-query'
import CompanyNew from './CompanyNew'
import ProtectedRoute from '../components/ProtectedRoute'
import { api, ApiError, type WorkspaceInspection, type WorkspaceStatus } from '../services/api'
import { useAuthStore } from '../store/useAuthStore'
import { useAppStore } from '../store/useAppStore'

const modelCatalogue = vi.hoisted(() => ({
  models: [] as { id: string; provider: string; tier: string; description: string }[],
}))

const daemon = vi.hoisted(() => ({
  status: {
    data: undefined as WorkspaceStatus | undefined,
    isPending: false,
    error: null as unknown,
  },
}))

const MAC_HOST = { hostname: 'ana-mbp', platform: 'darwin', home: '/Users/ana', sep: '/' }

function inspection(path: string, overrides: Partial<WorkspaceInspection> = {}): WorkspaceInspection {
  return {
    host: MAC_HOST,
    path,
    name: path.split('/').pop() || path,
    exists: true,
    is_dir: true,
    git: { is_repo: false, branch: null, remote_url: null, provider: null, web_url: null },
    ...overrides,
  }
}

vi.mock('../hooks/useQueries', () => ({
  useModels: () => ({ data: modelCatalogue }),
  useDiscoverTeam: () => useMutation({
    mutationFn: ({ companyId, projectPath }: { companyId: number | null; projectPath: string }) =>
      api.discoverTeam(companyId, projectPath),
  }),
  useInitCompany: () => useMutation({ mutationFn: api.initCompany }),
  useWorkspaceStatus: () => daemon.status,
}))

function CurrentPath() {
  const location = useLocation()
  return <output data-testid="current-path">{location.pathname}</output>
}

describe('company creation profile refresh', () => {
  beforeEach(() => {
    modelCatalogue.models = []
    daemon.status = { data: { connected: true, host: MAC_HOST, jetstream: true }, isPending: false, error: null }
    vi.spyOn(api, 'inspectWorkspace').mockImplementation(async path => inspection(path))
    useAuthStore.getState().logout()
    useAuthStore.setState({
      token: 'valid-token',
      expiresAt: Date.now() + 60_000,
      meLoaded: true,
    })
  })

    async function renderSpanishWizard(language = 'es') {
      const i18n = createInstance()
      await i18n.init({
        lng: language,
        fallbackLng: false,
        resources: { en: { translation: en }, es: { translation: es } },
        interpolation: { escapeValue: false },
      })
      const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
      render(
        <I18nextProvider i18n={i18n}>
          <QueryClientProvider client={client}>
            <MemoryRouter>
              <CompanyNew />
            </MemoryRouter>
          </QueryClientProvider>
        </I18nextProvider>,
      )
      return i18n
    }

    function nextSpanishStep() {
      fireEvent.click(screen.getByRole('button', { name: 'Siguiente →' }))
    }

    describe('Spanish factory wizard', () => {
      afterEach(() => {
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
      })

      it('updates untouched defaults on language changes while retaining edits and clean API payloads', async () => {
        const init = vi.spyOn(api, 'initCompany').mockImplementation(() => new Promise(() => {}))
        const i18n = await renderSpanishWizard('en')
        fireEvent.click(screen.getByRole('button', { name: 'Next →' }))
        fireEvent.change(screen.getByPlaceholderText('Acme Corp'), { target: { value: 'Factory' } })
        for (let step = 1; step < 4; step++) fireEvent.click(screen.getByRole('button', { name: 'Next →' }))
        expect(screen.getByDisplayValue('Product Management & Backlog')).toBeInTheDocument()
        expect(screen.getByDisplayValue('Automated Testing')).toBeInTheDocument()

        await act(async () => { await i18n.changeLanguage('es') })
        expect(screen.getByDisplayValue('Gestión de producto y trabajo pendiente')).toBeInTheDocument()
        expect(screen.getByDisplayValue('Pruebas automatizadas')).toBeInTheDocument()
        expect(screen.queryByText('Product Management & Backlog')).not.toBeInTheDocument()
        expect(screen.queryByText('Automated Testing')).not.toBeInTheDocument()

        await act(async () => { await i18n.changeLanguage('en') })
        fireEvent.change(screen.getByDisplayValue('Product Management & Backlog'), { target: { value: 'Custom specialty' } })
        fireEvent.change(screen.getByDisplayValue('Custom specialty'), { target: { value: 'Product Management & Backlog' } })
        await act(async () => { await i18n.changeLanguage('es') })
        expect(screen.getByDisplayValue('Product Management & Backlog')).toBeInTheDocument()
        expect(screen.getByDisplayValue('Pruebas automatizadas')).toBeInTheDocument()
        nextSpanishStep()
        expect(screen.getByText('· Product Management & Backlog')).toBeInTheDocument()
        expect(screen.getByText('· Pruebas automatizadas')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: '🏭 Inicializar Fábrica' }))
        await waitFor(() => expect(init).toHaveBeenCalledOnce())
        const payload = init.mock.calls[0][0]
        const agents = payload.agents ?? []
        expect(agents).toHaveLength(4)
        expect(agents[0]).toMatchObject({
          role: 'PO', seniority: 'Senior', specialty: 'Product Management & Backlog',
          persona: 'Product Management & Backlog',
        })
        expect(agents[3].specialty).toBe('Pruebas automatizadas')
        for (const agent of agents) expect(agent).not.toHaveProperty('defaultSpecialtyKey')
      })

      it('does not translate discovery-provided specialties when the mounted wizard changes language', async () => {
        vi.spyOn(api, 'discoverTeam').mockResolvedValue({
          discovery_id: 1,
          detected_stack: {
            name: 'Factory', language: 'TypeScript', frameworks: [], databases: [], infra: [],
            complexity: 'Low', file_count: 1,
          },
          suggested_team: [
            { role: 'PO', seniority: 'Senior', specialty: 'Product Management & Backlog', persona: 'External persona' },
            { role: 'QA', seniority: 'Senior', specialty: 'Automated Testing' },
          ],
        })
        const init = vi.spyOn(api, 'initCompany').mockImplementation(() => new Promise(() => {}))
        const i18n = await renderSpanishWizard('en')
        fireEvent.change(screen.getByLabelText('Project folder'), { target: { value: '/projects/demo' } })
        fireEvent.click(screen.getByRole('button', { name: '🔍 Scan' }))
        await screen.findByText(/Stack detected/)
        for (let step = 0; step < 4; step++) fireEvent.click(screen.getByRole('button', { name: 'Next →' }))
        await act(async () => { await i18n.changeLanguage('es') })
        expect(screen.getByDisplayValue('Product Management & Backlog')).toBeInTheDocument()
        expect(screen.getByDisplayValue('Automated Testing')).toBeInTheDocument()
        expect(screen.queryByDisplayValue('Pruebas automatizadas')).not.toBeInTheDocument()
        nextSpanishStep()
        fireEvent.click(screen.getByRole('button', { name: '🏭 Inicializar Fábrica' }))
        await waitFor(() => expect(init).toHaveBeenCalledOnce())
        expect(init.mock.calls[0][0].agents).toEqual([
          expect.objectContaining({ role: 'PO', specialty: 'Product Management & Backlog', persona: 'External persona' }),
          expect.objectContaining({ role: 'QA', specialty: 'Automated Testing', persona: 'Automated Testing' }),
        ])
      })

      it('localizes all six steps, validation, generated team defaults, options, and review', async () => {
        await renderSpanishWizard()
        expect(screen.getByRole('heading', { name: '🏭 Nueva Fábrica' })).toBeInTheDocument()
        for (const step of ['Proyecto', 'Empresa', 'Autonomía', 'Permisos', 'Equipo', 'Revisión']) {
          expect(screen.getByText(step)).toBeInTheDocument()
        }
        expect(screen.getByLabelText('Carpeta del proyecto')).toHaveAttribute('placeholder', '~/code/mi-app')
        expect(screen.getByText('Daemon del espacio de trabajo conectado en ana-mbp (macOS)')).toBeInTheDocument()
        expect(screen.getByText('Aún no se ha analizado ningún proyecto.')).toBeInTheDocument()
        nextSpanishStep()
        expect(screen.getByRole('heading', { name: 'Detalles de la empresa' })).toBeInTheDocument()
        fireEvent.change(screen.getByPlaceholderText('Acme Corp'), { target: { value: 'A' } })
        expect(screen.getByText('El nombre debe tener al menos 2 caracteres.')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Siguiente →' })).toBeDisabled()
        fireEvent.change(screen.getByPlaceholderText('Acme Corp'), { target: { value: 'Mi Fábrica' } })
        expect(screen.getByPlaceholderText('Una breve descripción de lo que construye esta fábrica…')).toBeInTheDocument()
        expect(screen.getByRole('option', { name: 'Mediano — hasta 8 tareas, una funcionalidad completa' })).toHaveValue('M')
        expect(screen.getByRole('option', { name: 'Nueva York' })).toHaveValue('America/New_York')
        nextSpanishStep()
        expect(screen.getByText('Nivel 2 — Gestor de excepciones')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: /Nivel 1 — Copiloto/ }))
        expect(screen.getByText('Supervisión humana completa')).toBeInTheDocument()
        nextSpanishStep()
        expect(screen.getByText('Git / Control de versiones')).toBeInTheDocument()
        expect(screen.getAllByRole('option', { name: 'Solo lectura' })[0]).toHaveValue('read_only')
        expect(screen.getByText('Requerir aprobación humana antes de cualquier despliegue')).toBeInTheDocument()
        expect(screen.getByText(/En el nivel de autonomía 1/)).toBeInTheDocument()
        nextSpanishStep()
        expect(screen.getByRole('heading', { name: 'Crea tu equipo de IA' })).toBeInTheDocument()
        expect(screen.getByDisplayValue('Gestión de producto y trabajo pendiente')).toBeInTheDocument()
        expect(screen.getByDisplayValue('Pruebas automatizadas')).toBeInTheDocument()
        expect(screen.getAllByRole('option', { name: '💻 Desarrollador' })[0]).toHaveValue('Dev')
        expect(screen.getAllByRole('option', { name: 'Intermedio (2–5 años)' })[0]).toHaveValue('Mid')
        expect(screen.getAllByText('Cargando modelos…')).toHaveLength(4)
        expect(screen.getAllByTitle('Eliminar')).toHaveLength(4)
        expect(screen.getByText('4.5 M de tokens')).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: '+ Añadir agente' }))
        expect(screen.getAllByTitle('Eliminar')).toHaveLength(5)
        nextSpanishStep()
        expect(screen.getByRole('heading', { name: 'Revisar e inicializar' })).toBeInTheDocument()
        expect(screen.getByText('Equipo — 5 agentes')).toBeInTheDocument()
        expect(screen.getByText(/Sprints de alcance M/)).toBeInTheDocument()
        expect(screen.getByText('Nivel 1')).toBeInTheDocument()
        expect(screen.getByText('5.5 M de tokens/mes')).toBeInTheDocument()
        expect(screen.getAllByRole('button', { name: 'Editar' })).toHaveLength(4)
        expect(screen.getByRole('button', { name: '🏭 Inicializar Fábrica' })).toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(/companyNew\./)
      })

      it('localizes the folder picker and the daemon start help', async () => {
        vi.spyOn(api, 'browseWorkspace').mockRejectedValue(
          new ApiError(503, 'Service is starting up.', 'Workspace daemon not connected'))
        await renderSpanishWizard()
        fireEvent.click(screen.getByRole('button', { name: '📂 Examinar' }))
        const dialog = await screen.findByRole('dialog', { name: 'Elige la carpeta del proyecto' })
        expect(await within(dialog).findByText('El daemon del espacio de trabajo no está conectado.')).toBeInTheDocument()
        expect(within(dialog).getByText('./scripts/start-daemon.sh')).toBeInTheDocument()
        expect(within(dialog).getByRole('button', { name: 'Usar esta carpeta' })).toBeDisabled()
        fireEvent.click(within(dialog).getByRole('button', { name: 'Cerrar' }))
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(/folderPicker\.|workspaceDaemon\./)
      })

      it('localizes scanning and discovery errors', async () => {
        let rejectDiscovery!: (error: Error) => void
        vi.spyOn(api, 'discoverTeam').mockImplementation(() => new Promise((_, reject) => { rejectDiscovery = reject }))
        await renderSpanishWizard()
        fireEvent.change(screen.getByLabelText('Carpeta del proyecto'), { target: { value: '/projects/demo' } })
        fireEvent.click(screen.getByRole('button', { name: '🔍 Analizar' }))
        expect(await screen.findByText('Analizando…')).toBeInTheDocument()
        await act(async () => { rejectDiscovery(new Error('Repositorio inaccesible')) })
        expect(await screen.findByText('Error al analizar el proyecto: Repositorio inaccesible')).toBeInTheDocument()
      })

      it.each(['ai', 'rules'] as const)('localizes detected stack metadata and %s team suggestions', async teamSource => {
        vi.spyOn(api, 'discoverTeam').mockResolvedValue({
          discovery_id: 1,
          detected_stack: {
            name: 'demo', language: 'TypeScript', frameworks: ['React'], databases: [], infra: [],
            complexity: 'High', file_count: 1, team_source: teamSource,
          },
          suggested_team: [{
            role: 'Dev', seniority: 'Mid', specialty: 'TypeScript',
            model: 'legacy-model-id', system_prompt: 'User-provided prompt',
          }],
        })
        await renderSpanishWizard()
        fireEvent.change(screen.getByLabelText('Carpeta del proyecto'), { target: { value: '/projects/demo' } })
        fireEvent.click(screen.getByRole('button', { name: '🔍 Analizar' }))
        expect(await screen.findByText(/Tecnologías detectadas/)).toBeInTheDocument()
        expect(screen.getByText('Lenguaje principal')).toBeInTheDocument()
        expect(screen.getByText('1 archivo analizado')).toBeInTheDocument()
        expect(screen.getByText('Complejidad alta')).toBeInTheDocument()
        expect(screen.getByText(teamSource === 'ai' ? /Equipo sugerido por IA/ : 'Sugerencia basada en reglas')).toBeInTheDocument()
        for (let step = 0; step < 4; step++) nextSpanishStep()
        expect(screen.getByText('Equipo sugerido según las tecnologías detectadas. Personalízalo según tus necesidades.')).toBeInTheDocument()
        expect(screen.getByRole('option', { name: 'legacy-model-id (sin resolver)' })).toHaveValue('legacy-model-id')
        fireEvent.click(screen.getByRole('button', { name: /Instrucciones del sistema/ }))
        expect(screen.getByDisplayValue('User-provided prompt')).toBeInTheDocument()
      })

      it('localizes model tiers while preserving model identifiers and descriptions', async () => {
        modelCatalogue.models = [
          { id: 'model-id', provider: 'gemini', tier: 'strategic', description: 'Catalogue-provided description' },
        ]
        await renderSpanishWizard()
        nextSpanishStep()
        fireEvent.change(screen.getByPlaceholderText('Acme Corp'), { target: { value: 'Mi Fábrica' } })
        for (let step = 1; step < 4; step++) nextSpanishStep()
        expect(screen.getAllByRole('group', { name: '🔵 Estratégico' })).toHaveLength(4)
        expect(screen.getAllByRole('option', { name: 'model-id (gemini)' })[0]).toHaveValue('model-id')
        fireEvent.change(screen.getAllByRole('combobox')[2], { target: { value: 'model-id' } })
        expect(screen.getByText('Catalogue-provided description')).toBeInTheDocument()
      })

      it.each([
        { message: '', expected: 'Error desconocido' },
        { message: 'Servicio no disponible', expected: 'Servicio no disponible' },
      ])('localizes initialization failures and preserves API identifiers ($expected)', async ({ message, expected }) => {
        const alert = vi.spyOn(window, 'alert').mockImplementation(() => {})
        vi.spyOn(console, 'error').mockImplementation(() => {})
        const init = vi.spyOn(api, 'initCompany').mockRejectedValue(new Error(message))
        await renderSpanishWizard()
        nextSpanishStep()
        fireEvent.change(screen.getByPlaceholderText('Acme Corp'), { target: { value: 'Mi Fábrica' } })
        for (let step = 1; step < 5; step++) nextSpanishStep()
        fireEvent.click(screen.getByRole('button', { name: '🏭 Inicializar Fábrica' }))
        await waitFor(() => expect(alert).toHaveBeenCalledWith(`Error al inicializar la fábrica: ${expected}`))
        if (message) expect(await screen.findByText(`Error al inicializar la fábrica: ${message}`)).toBeInTheDocument()
        expect(init.mock.calls[0][0]).toEqual(expect.objectContaining({
          company_name: 'Mi Fábrica', default_scope_size: 'M', timezone: 'UTC',
          permissions: expect.objectContaining({ git_access: 'read_only', cloud_access: 'none' }),
          agents: expect.arrayContaining([expect.objectContaining({ role: 'Dev', seniority: 'Mid' })]),
        }))
      })
    })

  afterEach(() => vi.restoreAllMocks())

  it.each([
    { scenario: 'first company', memberships: [] },
    { scenario: 'second company', memberships: [{ company_id: 7, human_role: 'Owner' as const }] },
  ])('keeps the created company and workspace when refresh fails ($scenario; issue #6)', async ({ memberships }) => {
    useAuthStore.setState({ memberships })
    if (memberships.length) useAppStore.getState().setCompany(7, 'Existing Factory')
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
    const init = vi.spyOn(api, 'initCompany').mockResolvedValue({
      company_id: 14, sprint_id: 5, task_count: 0, message: 'Created',
    })
    let rejectProfile!: (error: Error) => void
    const me = vi.spyOn(api, 'me')
      .mockImplementationOnce(() => new Promise((_, reject) => { rejectProfile = reject }))
      .mockResolvedValue({
        user_id: 1, email: 'user@example.com', full_name: 'User',
        memberships: [...memberships, { company_id: 14, human_role: 'Owner' }],
      })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/companies/new']}>
          <CurrentPath />
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/companies/new" element={<CompanyNew />} />
              <Route path="/sprints/5" element={<div>Created workspace</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Next →' }))
    fireEvent.change(screen.getByPlaceholderText('Acme Corp'), { target: { value: 'New Factory' } })
    for (let step = 1; step < 5; step++) {
      fireEvent.click(screen.getByRole('button', { name: 'Next →' }))
    }
    fireEvent.click(screen.getByRole('button', { name: /Initialize Factory/ }))
    expect(await screen.findByRole('status')).toBeInTheDocument()
    expect(me).toHaveBeenCalledOnce()
    expect(useAppStore.getState().companyId).toBe(14)

    await act(async () => { rejectProfile(new Error('Profile unavailable')) })

    expect(screen.getByRole('alert')).toHaveTextContent('Profile unavailable')
    expect(useAppStore.getState()).toMatchObject({ companyId: 14, companyName: 'New Factory' })
    expect(screen.getByTestId('current-path')).toHaveTextContent('/sprints/5')

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Created workspace')).toBeInTheDocument()
    expect(init).toHaveBeenCalledOnce()
    client.clear()
  })
})

describe('project folder on the user\'s computer', () => {
  const listing = {
    host: MAC_HOST,
    path: '/Users/ana/code',
    parent: '/Users/ana',
    entries: [{ name: 'app-link', path: '/Users/ana/code/app-link', is_git: true }],
    shortcuts: [{ name: 'Home', path: '/Users/ana' }],
    roots: [{ name: '/', path: '/' }],
    truncated: false,
  }
  const githubProject = inspection('/Users/ana/code/la-fabrique', {
    name: 'la-fabrique',
    git: {
      is_repo: true,
      branch: 'main',
      remote_url: 'git@github.com:careb36/la-fabrique.git',
      provider: 'github',
      web_url: 'https://github.com/careb36/la-fabrique',
    },
  })

  let client: QueryClient

  beforeEach(() => {
    useAuthStore.setState({ token: 'valid-token', expiresAt: Date.now() + 60_000, meLoaded: true })
    daemon.status = { data: { connected: true, host: MAC_HOST, jetstream: true }, isPending: false, error: null }
    client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  })

  afterEach(() => {
    client.clear()
    delete window.electronAPI
    vi.restoreAllMocks()
  })

  function renderWizard() {
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <CompanyNew />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('starts with an empty field and a placeholder for the host platform', () => {
    vi.spyOn(api, 'inspectWorkspace')
    renderWizard()
    const input = screen.getByLabelText('Project folder')
    expect(input).toHaveValue('')
    expect(input).toHaveAttribute('placeholder', '~/code/my-app')
    expect(screen.getByRole('button', { name: '🔍 Scan' })).toBeDisabled()
    expect(screen.getByText('Workspace daemon connected on ana-mbp (macOS)')).toBeInTheDocument()
  })

  it('says it cannot tell when the daemon state is unknown, and shows how to start it only when absent', () => {
    daemon.status = {
      data: { connected: false, state: 'unknown', reason: 'no answer within 3 s', host: null, jetstream: true },
      isPending: false,
      error: null,
    }
    const { unmount } = renderWizard()
    expect(screen.getByText(/Cannot tell whether the workspace daemon is running: no answer within 3 s/)).toBeInTheDocument()
    expect(screen.queryByText('./scripts/start-daemon.sh')).not.toBeInTheDocument()
    unmount()

    daemon.status = {
      data: { connected: false, state: 'absent', reason: 'no daemon is listening', host: null, jetstream: true },
      isPending: false,
      error: null,
    }
    renderWizard()
    expect(screen.queryByText(/Cannot tell whether/)).not.toBeInTheDocument()
    expect(screen.getByText('./scripts/start-daemon.sh')).toBeInTheDocument()
  })

  it('inspects the folder chosen in the picker and shows the canonical path, provider and branch', async () => {
    const browse = vi.spyOn(api, 'browseWorkspace').mockResolvedValue(listing)
    const inspect = vi.spyOn(api, 'inspectWorkspace').mockResolvedValue(githubProject)
    renderWizard()

    fireEvent.click(screen.getByRole('button', { name: /Browse/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Choose a project folder' })
    expect(browse).toHaveBeenCalledWith(undefined)
    await within(dialog).findByText('app-link')
    browse.mockResolvedValue({ ...listing, path: '/Users/ana/code/app-link', parent: '/Users/ana/code', entries: [] })
    fireEvent.click(within(dialog).getByRole('button', { name: /app-link/ }))
    expect(browse).toHaveBeenLastCalledWith('/Users/ana/code/app-link')
    await within(dialog).findByText('/Users/ana/code/app-link')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Use this folder' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(inspect).toHaveBeenCalledWith('/Users/ana/code/app-link')
    const card = await screen.findByTestId('project-card')
    expect(within(card).getByText('la-fabrique')).toBeInTheDocument()
    expect(within(card).getByTestId('project-provider')).toHaveTextContent('GitHub')
    expect(within(card).getByText('main')).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: 'https://github.com/careb36/la-fabrique' }))
      .toHaveAttribute('href', 'https://github.com/careb36/la-fabrique')
    // The field now holds the canonical path the daemon resolved, not the symlink chosen.
    expect(screen.getByLabelText('Project folder')).toHaveValue('/Users/ana/code/la-fabrique')
    expect(screen.getByRole('button', { name: '🔍 Scan' })).toBeEnabled()
  })

  it('says when a folder is not a git repository', async () => {
    vi.spyOn(api, 'inspectWorkspace').mockResolvedValue(inspection('/Users/ana/notes', { name: 'notes' }))
    renderWizard()
    const input = screen.getByLabelText('Project folder')
    fireEvent.change(input, { target: { value: '/Users/ana/notes' } })
    fireEvent.blur(input)
    expect(await screen.findByTestId('project-provider')).toHaveTextContent('Not a git repository')
    expect(screen.getByText(/not a git clone/)).toBeInTheDocument()
  })

  it('shows an error and keeps Scan disabled when the folder does not exist', async () => {
    const discover = vi.spyOn(api, 'discoverTeam')
    vi.spyOn(api, 'inspectWorkspace').mockResolvedValue(
      inspection('/Users/ana/code/missing', { exists: false, is_dir: false, git: null }))
    renderWizard()
    const input = screen.getByLabelText('Project folder')
    fireEvent.change(input, { target: { value: '~/code/missing' } })
    fireEvent.blur(input)

    expect(await screen.findByText('This folder does not exist on ana-mbp: /Users/ana/code/missing'))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: '🔍 Scan' })).toBeDisabled()
    fireEvent.keyDown(input, { key: 'Enter' })
    await act(async () => {})
    expect(discover).not.toHaveBeenCalled()
    expect(screen.queryByTestId('project-card')).not.toBeInTheDocument()
  })

  it('opens the native dialog in the desktop app instead of the daemon picker', async () => {
    const selectDirectory = vi.fn().mockResolvedValue('/Users/ana/code/la-fabrique')
    window.electronAPI = {
      platform: 'darwin',
      versions: { node: '', chrome: '', electron: '' },
      selectDirectory,
      onNavigate: () => () => {},
      getBackendUrl: async () => '',
      getAppVersion: async () => '',
      openExternal: async () => {},
    }
    const browse = vi.spyOn(api, 'browseWorkspace').mockResolvedValue(listing)
    const inspect = vi.spyOn(api, 'inspectWorkspace').mockResolvedValue(githubProject)
    renderWizard()

    fireEvent.click(screen.getByRole('button', { name: /Browse$/ }))
    await waitFor(() => expect(inspect).toHaveBeenCalledWith('/Users/ana/code/la-fabrique'))
    expect(selectDirectory).toHaveBeenCalledOnce()
    expect(browse).not.toHaveBeenCalled()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(await screen.findByTestId('project-card')).toBeInTheDocument()

    // The daemon picker stays available as a secondary action.
    fireEvent.click(screen.getByRole('button', { name: 'Browse via the workspace daemon' }))
    expect(await screen.findByRole('dialog', { name: 'Choose a project folder' })).toBeInTheDocument()
    expect(browse).toHaveBeenCalledWith('/Users/ana/code/la-fabrique')
  })

  it('does nothing when the native dialog is cancelled', async () => {
    window.electronAPI = {
      platform: 'win32',
      versions: { node: '', chrome: '', electron: '' },
      selectDirectory: vi.fn().mockResolvedValue(null),
      onNavigate: () => () => {},
      getBackendUrl: async () => '',
      getAppVersion: async () => '',
      openExternal: async () => {},
    }
    const inspect = vi.spyOn(api, 'inspectWorkspace')
    renderWizard()
    fireEvent.click(screen.getByRole('button', { name: /Browse$/ }))
    await waitFor(() => expect(window.electronAPI!.selectDirectory).toHaveBeenCalledOnce())
    expect(inspect).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Project folder')).toHaveValue('')
  })

  it('lets a typed path be scanned when the daemon is down, and sends the canonical discovery path to init_company', async () => {
    daemon.status = { data: { connected: false, host: null }, isPending: false, error: null }
    vi.spyOn(api, 'inspectWorkspace').mockRejectedValue(
      new ApiError(503, 'Service is starting up.', 'Workspace daemon not connected'))
    const discover = vi.spyOn(api, 'discoverTeam').mockResolvedValue({
      discovery_id: 3,
      project_path: 'C:\\Users\\ana\\source\\repos\\la-fabrique',
      project: null,
      detected_stack: {
        name: 'la-fabrique', language: 'TypeScript', frameworks: [], databases: [], infra: [],
        complexity: 'Low', file_count: 2,
      },
      suggested_team: [],
    })
    const init = vi.spyOn(api, 'initCompany').mockImplementation(() => new Promise(() => {}))
    renderWizard()

    const input = screen.getByLabelText('Project folder')
    fireEvent.change(input, { target: { value: 'c:\\users\\ana\\source\\repos\\la-fabrique' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 Scan' }))

    await screen.findByText(/Stack detected/)
    expect(discover).toHaveBeenCalledWith(null, 'c:\\users\\ana\\source\\repos\\la-fabrique')
    expect(screen.getAllByText('The workspace daemon is not connected.').length).toBeGreaterThan(0)
    expect(screen.getByText('You can still type the folder path and scan it.')).toBeInTheDocument()
    expect(input).toHaveValue('C:\\Users\\ana\\source\\repos\\la-fabrique')

    for (let step = 0; step < 5; step++) fireEvent.click(screen.getByRole('button', { name: 'Next →' }))
    fireEvent.click(screen.getByRole('button', { name: /Initialize Factory/ }))
    await waitFor(() => expect(init).toHaveBeenCalledOnce())
    expect(init.mock.calls[0][0].project_path).toBe('C:\\Users\\ana\\source\\repos\\la-fabrique')
  })

  it('scans with one inspection when leaving the field by clicking Scan', async () => {
    let resolveInspect!: (value: WorkspaceInspection) => void
    const inspect = vi.spyOn(api, 'inspectWorkspace')
      .mockImplementation(() => new Promise(resolve => { resolveInspect = resolve }))
    const discover = vi.spyOn(api, 'discoverTeam').mockImplementation(() => new Promise(() => {}))
    renderWizard()

    const input = screen.getByLabelText('Project folder')
    fireEvent.change(input, { target: { value: '~/code/la-fabrique' } })
    fireEvent.blur(input)
    expect(await screen.findByText('Checking folder…')).toBeInTheDocument()
    const scan = screen.getByRole('button', { name: '🔍 Scan' })
    expect(scan).toBeEnabled()
    fireEvent.click(scan)

    await act(async () => { resolveInspect(githubProject) })
    await waitFor(() => expect(discover).toHaveBeenCalledWith(null, '/Users/ana/code/la-fabrique'))
    expect(inspect).toHaveBeenCalledOnce()
    expect(inspect).toHaveBeenCalledWith('~/code/la-fabrique')
  })

  it('shows the Windows start command and placeholder when the desktop app runs on Windows', () => {
    daemon.status = { data: { connected: false, host: null }, isPending: false, error: null }
    window.electronAPI = {
      platform: 'win32',
      versions: { node: '', chrome: '', electron: '' },
      selectDirectory: async () => null,
      onNavigate: () => () => {},
      getBackendUrl: async () => '',
      getAppVersion: async () => '',
      openExternal: async () => {},
    }
    renderWizard()
    expect(screen.getByLabelText('Project folder'))
      .toHaveAttribute('placeholder', 'C:\\Users\\you\\source\\repos\\my-app')
    expect(screen.getByText('.\\scripts\\start-daemon.ps1')).toBeInTheDocument()
    expect(screen.queryByText('./scripts/start-daemon.sh')).not.toBeInTheDocument()
  })
})
