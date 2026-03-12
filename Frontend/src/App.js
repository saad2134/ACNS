/**
 * App.js
 * Root application component.
 */

import React, { Suspense, Component } from 'react';
import { Routes, Route } from 'react-router-dom';

import Navbar from './components/Navbar';

// Lazy-load pages so a crash in one won't blank the entire app
const Home            = React.lazy(() => import('./pages/Home'));
const ReportIssue     = React.lazy(() => import('./pages/ReportIssue'));
const LeaderboardPage = React.lazy(() => import('./pages/LeaderboardPage'));
const AdminDashboard  = React.lazy(() => import('./pages/AdminDashboard'));
const Login           = React.lazy(() => import('./pages/Login'));
const NotFound        = React.lazy(() => import('./pages/NotFound'));

/* --- Top-level Error Boundary --- */
class AppErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', background: '#1a1a2e', minHeight: '100vh' }}>
          <h2 style={{ color: '#ff5252' }}>Something went wrong</h2>
          <p style={{ color: '#90a4ae' }}>{String(this.state.error)}</p>
          <button onClick={() => window.location.reload()}
            style={{ marginTop: 16, padding: '10px 24px', background: '#00d4ff', color: '#000', border: 'none', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}>
            Reload Page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

/* --- Loading Spinner --- */
const Loader = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
    <h2 style={{ color: '#00d4ff' }}>Loading...</h2>
  </div>
);

function App() {
  return (
    <AppErrorBoundary>
      <div className="App">
        <Navbar />

        <Suspense fallback={<Loader />}>
          <Routes>
            <Route path="/"            element={<Home />} />
            <Route path="/report"      element={<ReportIssue />} />
            <Route path="/leaderboard" element={<LeaderboardPage />} />
            <Route path="/admin"       element={<AdminDashboard />} />
            <Route path="/login"       element={<Login />} />
            <Route path="*"          element={<NotFound />} />
          </Routes>
        </Suspense>
      </div>
    </AppErrorBoundary>
  );
}

export default App;
