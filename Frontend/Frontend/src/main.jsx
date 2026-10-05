import { Component, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './CustomerApp.jsx'
import './index.css'

class StartupBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error) { console.error('caughtIn4K could not initialize:', error.name) }
  render() {
    return this.state.failed ? <main className="customer-app">
      <h1>caughtIn4K</h1>
      <p role="alert">Your account session could not be loaded. Allow browser storage and reload, or contact support. If a network command was pending, check its outcome before clearing browser data.</p>
      <button onClick={() => window.location.reload()}>Reload</button>
    </main> : this.props.children
  }
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <StartupBoundary><App /></StartupBoundary>
  </StrictMode>,
)
