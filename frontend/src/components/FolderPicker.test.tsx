import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { FolderPicker } from './FolderPicker'
import { api, ApiError, type WorkspaceBrowseResponse } from '../services/api'

const WINDOWS_HOST = { hostname: 'ana-pc', platform: 'win32', home: 'C:\\Users\\ana', sep: '\\' }

// Entry paths deliberately differ from `path + sep + name` (a junction to
// another drive) so any string joining in the picker would be caught.
const repos: WorkspaceBrowseResponse = {
  host: WINDOWS_HOST,
  path: 'C:\\Users\\ana\\source\\repos',
  parent: 'C:\\Users\\ana\\source',
  entries: [
    { name: 'la-fabrique', path: 'C:\\Users\\ana\\source\\repos\\la-fabrique', is_git: true },
    { name: 'notes', path: 'D:\\mounted\\notes', is_git: false },
  ],
  shortcuts: [
    { name: 'Home', path: 'C:\\Users\\ana' },
    { name: 'source/repos', path: 'C:\\Users\\ana\\source\\repos' },
  ],
  roots: [
    { name: 'C:\\', path: 'C:\\' },
    { name: 'D:\\', path: 'D:\\' },
  ],
  truncated: false,
}

const notes: WorkspaceBrowseResponse = {
  ...repos,
  path: 'D:\\mounted\\notes',
  parent: 'D:\\mounted',
  entries: [],
}

afterEach(() => vi.restoreAllMocks())

function renderPicker(props: Partial<Parameters<typeof FolderPicker>[0]> = {}) {
  const onSelect = vi.fn()
  const onClose = vi.fn()
  render(<FolderPicker onSelect={onSelect} onClose={onClose} {...props} />)
  return { onSelect, onClose }
}

describe('FolderPicker', () => {
  it('lists the folders, shortcuts and drives of the start view', async () => {
    const browse = vi.spyOn(api, 'browseWorkspace').mockResolvedValue(repos)
    renderPicker()

    const dialog = screen.getByRole('dialog', { name: 'Choose a project folder' })
    expect(within(dialog).getByRole('status')).toHaveTextContent('Loading folders…')
    expect(await within(dialog).findByTestId('folder-picker-path')).toHaveTextContent('C:\\Users\\ana\\source\\repos')
    expect(browse).toHaveBeenCalledWith(undefined)
    expect(within(dialog).getByText('On ana-pc (Windows)')).toBeInTheDocument()

    const folders = within(within(dialog).getByRole('list', { name: 'Folders' })).getAllByRole('button')
    expect(folders.map(button => button.textContent)).toEqual(['📁la-fabriquegit repo', '📁notes'])
    expect(within(within(dialog).getByRole('group', { name: 'Shortcuts' })).getAllByRole('button')
      .map(button => button.textContent)).toEqual(['Home', 'source/repos'])
    expect(within(within(dialog).getByRole('group', { name: 'Drives' })).getAllByRole('button')
      .map(button => button.textContent)).toEqual(['C:\\', 'D:\\'])
  })

  it('shows the git badge only for git repositories', async () => {
    vi.spyOn(api, 'browseWorkspace').mockResolvedValue(repos)
    renderPicker()
    const git = await screen.findByRole('button', { name: /la-fabrique/ })
    expect(within(git).getByTitle('This folder is a git repository')).toHaveTextContent('git repo')
    expect(within(screen.getByRole('button', { name: /notes/ })).queryByText('git repo')).not.toBeInTheDocument()
    expect(screen.getAllByText('git repo')).toHaveLength(1)
  })

  it('enters a folder by requesting exactly the path the API returned for it', async () => {
    const browse = vi.spyOn(api, 'browseWorkspace').mockResolvedValueOnce(repos).mockResolvedValueOnce(notes)
    renderPicker()
    fireEvent.click(await screen.findByRole('button', { name: /notes/ }))
    expect(browse).toHaveBeenLastCalledWith('D:\\mounted\\notes')
    expect(await screen.findByText('No subfolders here.')).toBeInTheDocument()
    expect(screen.getByTestId('folder-picker-path')).toHaveTextContent('D:\\mounted\\notes')
  })

  it('goes up using the parent the API returned, and hides Up at a root', async () => {
    const browse = vi.spyOn(api, 'browseWorkspace')
      .mockResolvedValueOnce(repos)
      .mockResolvedValueOnce({ ...repos, path: 'C:\\', parent: null, entries: [] })
    renderPicker()
    fireEvent.click(await screen.findByRole('button', { name: 'Go to the parent folder' }))
    expect(browse).toHaveBeenLastCalledWith('C:\\Users\\ana\\source')
    expect(await screen.findByText('No subfolders here.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Go to the parent folder' })).not.toBeInTheDocument()
  })

  it('opens shortcuts and drives by their paths', async () => {
    const browse = vi.spyOn(api, 'browseWorkspace').mockResolvedValue(repos)
    renderPicker()
    const drives = await screen.findByRole('group', { name: 'Drives' })
    fireEvent.click(within(drives).getByRole('button', { name: 'D:\\' }))
    expect(browse).toHaveBeenLastCalledWith('D:\\')
    fireEvent.click(await within(await screen.findByRole('group', { name: 'Shortcuts' })).findByRole('button', { name: 'Home' }))
    expect(browse).toHaveBeenLastCalledWith('C:\\Users\\ana')
  })

  it('returns the current folder from "Use this folder"', async () => {
    vi.spyOn(api, 'browseWorkspace').mockResolvedValueOnce(repos).mockResolvedValueOnce(notes)
    const { onSelect } = renderPicker()
    fireEvent.click(await screen.findByRole('button', { name: /notes/ }))
    await screen.findByText('No subfolders here.')
    fireEvent.click(screen.getByRole('button', { name: 'Use this folder' }))
    expect(onSelect).toHaveBeenCalledWith('D:\\mounted\\notes')
  })

  it('starts at the given folder', async () => {
    const browse = vi.spyOn(api, 'browseWorkspace').mockResolvedValue(notes)
    renderPicker({ initialPath: 'D:\\mounted\\notes' })
    await screen.findByText('No subfolders here.')
    expect(browse).toHaveBeenCalledWith('D:\\mounted\\notes')
  })

  it.each([
    { platform: 'win32', shown: ['.\\scripts\\start-daemon.ps1'], hidden: ['./scripts/start-daemon.sh'] },
    { platform: 'darwin', shown: ['./scripts/start-daemon.sh'], hidden: ['.\\scripts\\start-daemon.ps1'] },
    { platform: 'linux', shown: ['./scripts/start-daemon.sh'], hidden: ['.\\scripts\\start-daemon.ps1'] },
    { platform: undefined, shown: ['./scripts/start-daemon.sh', '.\\scripts\\start-daemon.ps1'], hidden: [] },
  ])('explains how to start the daemon on a 503 (platform $platform)', async ({ platform, shown, hidden }) => {
    vi.spyOn(api, 'browseWorkspace').mockRejectedValue(
      new ApiError(503, 'Service is starting up.', 'Workspace daemon not connected'))
    renderPicker({ platform })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The workspace daemon is not connected.')
    expect(alert).toHaveTextContent('Workspace daemon not connected')
    for (const command of shown) expect(within(alert).getByText(command)).toBeInTheDocument()
    for (const command of hidden) expect(within(alert).queryByText(command)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use this folder' })).toBeDisabled()
  })

  it('retries after the daemon comes up', async () => {
    const browse = vi.spyOn(api, 'browseWorkspace')
      .mockRejectedValueOnce(new ApiError(503, 'Service is starting up.'))
      .mockResolvedValueOnce(repos)
    renderPicker({ initialPath: 'C:\\Users\\ana\\source\\repos' })
    fireEvent.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('button', { name: /la-fabrique/ })).toBeInTheDocument()
    expect(browse).toHaveBeenNthCalledWith(2, 'C:\\Users\\ana\\source\\repos')
  })

  it.each([404, 403])('shows the server detail for a %i and offers the home folder', async status => {
    const browse = vi.spyOn(api, 'browseWorkspace')
      .mockRejectedValueOnce(new ApiError(status, 'Generic message', `Cannot open C:\\nope (${status})`))
      .mockResolvedValueOnce(repos)
    renderPicker({ initialPath: 'C:\\nope' })
    expect(await screen.findByRole('alert')).toHaveTextContent(`Could not open this folder: Cannot open C:\\nope (${status})`)
    fireEvent.click(screen.getByRole('button', { name: 'Go to the home folder' }))
    expect(browse).toHaveBeenLastCalledWith(undefined)
    expect(await screen.findByRole('button', { name: /la-fabrique/ })).toBeInTheDocument()
  })

  it('notes a truncated listing', async () => {
    vi.spyOn(api, 'browseWorkspace').mockResolvedValue({ ...repos, truncated: true })
    renderPicker()
    expect(await screen.findByText(/Only the first folders are shown/)).toBeInTheDocument()
  })

  it('closes with Escape, the close button and Cancel', async () => {
    vi.spyOn(api, 'browseWorkspace').mockResolvedValue(repos)
    const { onClose, onSelect } = renderPicker()
    await screen.findByRole('button', { name: /la-fabrique/ })
    expect(screen.getByRole('dialog')).toHaveFocus()
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).toHaveBeenCalledTimes(3)
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('keeps focus inside the dialog after entering a folder', async () => {
    vi.spyOn(api, 'browseWorkspace').mockResolvedValueOnce(repos).mockResolvedValueOnce(notes)
    renderPicker()
    const entry = await screen.findByRole('button', { name: /notes/ })
    entry.focus()
    fireEvent.click(entry)
    await screen.findByText('No subfolders here.')
    expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement)
  })
})
