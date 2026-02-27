import * as signalR from '@microsoft/signalr'

const SIGNALR_URL = import.meta.env.VITE_SIGNALR_URL || ''

export function createSignalRConnection(callbacks = {}) {
  // If no SignalR URL is configured, return a dummy connection
  if (!SIGNALR_URL) {
    console.warn('VITE_SIGNALR_URL not configured. SignalR disabled.')
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

  const connection = new signalR.HubConnectionBuilder()
    .withUrl(SIGNALR_URL)
    .withAutomaticReconnect()
    .configureLogging(signalR.LogLevel.Information)
    .build()

  connection.on('AgentStatusUpdate', (data) => {
    if (callbacks.onAgentStatusUpdate) {
      callbacks.onAgentStatusUpdate(data)
    }
  })

  connection.on('LogMessage', (data) => {
    if (callbacks.onLogMessage) {
      callbacks.onLogMessage(data)
    }
  })

  connection.on('CostUpdate', (data) => {
    if (callbacks.onCostUpdate) {
      callbacks.onCostUpdate(data)
    }
  })

  connection.onreconnecting(() => {
    if (callbacks.onReconnecting) {
      callbacks.onReconnecting()
    }
  })

  connection.onreconnected(() => {
    if (callbacks.onReconnected) {
      callbacks.onReconnected()
    }
  })

  connection.onclose(() => {
    if (callbacks.onClose) {
      callbacks.onClose()
    }
  })

  return {
    async start() {
      try {
        await connection.start()
        console.log('SignalR connected')
        return true
      } catch (error) {
        console.error('SignalR connection failed:', error)
        return false
      }
    },
    async stop() {
      try {
        await connection.stop()
        console.log('SignalR disconnected')
      } catch (error) {
        console.error('SignalR disconnect failed:', error)
      }
    },
    get state() {
      return connection.state
    },
  }
}
