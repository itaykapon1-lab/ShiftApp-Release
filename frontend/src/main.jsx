import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import ErrorBoundary from './components/common/ErrorBoundary.jsx'
import { HelpProvider } from './help'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <HelpProvider>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </HelpProvider>
  </StrictMode>,
)
