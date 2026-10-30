import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { api, type AuthProfile, type AuthUser, type CompanyMembership } from '../services/api'
import { useAppStore } from './useAppStore'
import { queryClient } from '../lib/queryClient'

interface AuthState {
  token: string | null
  expiresAt: number | null
  user: AuthUser | null
  memberships: CompanyMembership[]
  meLoaded: boolean
  loadingMe: boolean
  profileError: string | null
  login: (email: string, password: string) => Promise<void>
  adoptSession: (token: string, expiresInSeconds: number) => void
  loadMe: () => Promise<void>
  logout: () => void
  getValidToken: () => string | null
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      expiresAt: null,
      user: null,
      memberships: [],
      meLoaded: false,
      loadingMe: false,
      profileError: null,

      login: async (email, password) => {
        queryClient.clear()
        const response = await api.login(email, password)
        set({
          token: response.access_token,
          expiresAt: Date.now() + response.expires_in * 1000,
          meLoaded: false,
          profileError: null,
        })
        await get().loadMe()
      },

      // The desktop launcher already holds the operator's key and mints a
      // session for this browser, so the UI opens signed in. Ordinary installs
      // never see this path: they log in through the form.
      adoptSession: (token, expiresInSeconds) => {
        queryClient.clear()
        set({
          token,
          expiresAt: Date.now() + Math.max(60, expiresInSeconds) * 1000,
          meLoaded: false,
          loadingMe: false,
          profileError: null,
        })
      },

      loadMe: async () => {
        const token = get().token
        set({ loadingMe: true, profileError: null })
        try {
          const profile: AuthProfile = await api.me()
          if (get().token !== token) return
          const { user_id, email, full_name, support_admin, memberships } = profile
          set({
            user: { user_id, email, full_name, support_admin: Boolean(support_admin) },
            memberships,
            meLoaded: true,
          })
        } catch (error) {
          if (get().token !== token) return
          set({ profileError: error instanceof Error ? error.message : String(error) })
          throw error
        } finally {
          if (get().token === token) set({ loadingMe: false })
        }
      },

      logout: () => {
        queryClient.clear()
        set({
          token: null,
          expiresAt: null,
          user: null,
          memberships: [],
          meLoaded: false,
          loadingMe: false,
          profileError: null,
        })
        useAppStore.getState().setCompany(null, null)
        useAppStore.getState().setActiveSprint(null)
      },

      getValidToken: () => {
        const { token, expiresAt } = get()
        if (!token || !expiresAt || expiresAt <= Date.now()) {
          if (token || expiresAt) get().logout()
          return null
        }
        return token
      },
    }),
    {
      name: 'fabrique-auth-storage',
      partialize: ({ token, expiresAt, user, memberships }) => ({
        token,
        expiresAt,
        user,
        memberships,
      }),
    },
  ),
)
