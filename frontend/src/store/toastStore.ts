import { create } from 'zustand'

export type ToastVariant = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: string
  variant: ToastVariant
  message: string
  duration?: number
}

interface ToastStore {
  toasts: Toast[]
  push: (toast: Omit<Toast, 'id'>) => void
  dismiss: (id: string) => void
}

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  push: (toast) => {
    const id = crypto.randomUUID()
    set(s => ({ toasts: [...s.toasts.slice(-2), { ...toast, id }] }))
    setTimeout(
      () => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })),
      toast.duration ?? 4_000
    )
  },
  dismiss: (id) => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })),
}))

export function useToast() {
  const push = useToastStore(s => s.push)
  return {
    success: (message: string) => push({ variant: 'success', message }),
    error:   (message: string) => push({ variant: 'error',   message }),
    warning: (message: string) => push({ variant: 'warning', message }),
    info:    (message: string) => push({ variant: 'info',    message }),
  }
}
