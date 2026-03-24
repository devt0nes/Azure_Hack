import * as signalR from '@microsoft/signalr'

const SIGNALR_URL = import.meta.env.VITE_SIGNALR_URL || ''

export function createSignalRConnection(callbacks = {}) {
  // Note: SignalR hub endpoint (/hub) not yet implemented in backend
  // Return a dummy connection that logs a warning
  console.warn('SignalR hub endpoint not implemented in backend. Real-time updates disabled.')
  return {
    async start() {
      return false
    },
    async stop() {},
    get state() {
      return 'Disconnected'
    },
  }
}
