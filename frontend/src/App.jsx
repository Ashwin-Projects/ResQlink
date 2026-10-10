import React, { useEffect, useState } from 'react';
import Navbar from './components/Navbar';
import LoginView from './components/LoginView';
import DashboardView from './components/DashboardView';
import ResourceView from './components/ResourceView';
import RequestView from './components/RequestView';
import MatchingDemoView from './components/MatchingDemoView';
import MapView from './components/MapView';
import HazardDemoView from './components/HazardDemoView';
import AuditView from './components/AuditView';
import EvaluationView from './components/EvaluationView';
import { capabilitiesFor, clearSession, consumeLogoutReason, getSession, onSessionChange } from './auth/session';

export default function App() {
  const [session, setSessionState] = useState(() => getSession());
  const [notice, setNotice] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [selectedRequestForMatch, setSelectedRequestForMatch] = useState(null);

  // Login, logout and 401 responses (expired / revoked token) all flow through the session store.
  useEffect(() => onSessionChange((s) => {
    setSessionState(s);
    if (!s) {
      setNotice(consumeLogoutReason());
      setActiveTab('dashboard');
      setSelectedRequestForMatch(null);
    } else {
      setNotice(null);
    }
  }), []);

  // Expire the UI session when the token's exp is reached (the API rejects it anyway).
  useEffect(() => {
    if (!session?.expiresAt) return undefined;
    const ms = session.expiresAt - Date.now();
    const t = setTimeout(() => getSession(), Math.max(0, Math.min(ms, 2 ** 31 - 1)));
    return () => clearTimeout(t);
  }, [session]);

  // New page -> start at the top.
  useEffect(() => { window.scrollTo(0, 0); }, [activeTab]);

  if (!session) return <LoginView notice={notice} />;

  const role = session.user?.role;
  const caps = capabilitiesFor(role);
  const tab = caps.tabs.includes(activeTab) ? activeTab : 'dashboard';
  const handleMatchSelect = caps.canMatch ? (req) => {
    setSelectedRequestForMatch(req);
    setActiveTab('matching');
  } : null;

  return (
    <div className="app-shell">
      <Navbar activeTab={tab} setActiveTab={setActiveTab} allowedTabs={caps.tabs}
              user={session.user} onLogout={() => clearSession()} />

      <main className="main" id="main">
        <div className="page" key={tab}>
          {tab === 'dashboard' && <DashboardView onNavigate={setActiveTab} allowedTabs={caps.tabs} role={role} />}
          {tab === 'resources' && <ResourceView />}
          {tab === 'requests' && <RequestView onMatchSelect={handleMatchSelect} role={role} />}
          {tab === 'matching' && <MatchingDemoView selectedRequest={selectedRequestForMatch} />}
          {tab === 'map' && <MapView />}
          {tab === 'hazard_sim' && <HazardDemoView />}
          {tab === 'audit' && <AuditView />}
          {tab === 'evaluation' && <EvaluationView />}
        </div>
      </main>
    </div>
  );
}
