import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AppState {
  companyId: number | null
  companyName: string | null
  activeSprintId: number | null
  setCompany: (id: number | null, name: string | null) => void
  setActiveSprint: (id: number | null) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      companyId: null,
      companyName: null,
      activeSprintId: null,

      setCompany: (id, name) => set(state => ({
        companyId: id, 
        companyName: name,
        activeSprintId: id !== state.companyId ? null : state.activeSprintId,
      })),

      setActiveSprint: (id) => set({ 
        activeSprintId: id 
      }),
    }),
    {
      name: 'fabrique-app-storage', // Nombre de la key en localStorage
    }
  )
)
