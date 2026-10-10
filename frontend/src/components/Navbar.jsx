import React from 'react';
import {
  LayoutDashboard,
  FileText,
  Boxes,
  GitMerge,
  Map,
  ShieldCheck,
  AlertTriangle,
  BarChart3,
  LogOut,
} from 'lucide-react';

// Operational pages vs. technical / demonstration pages.
const SECTIONS = [
  {
    label: 'Operations',
    items: [
      { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
      { id: 'requests', label: 'Requests', icon: FileText },
      { id: 'resources', label: 'Resources', icon: Boxes },
      { id: 'matching', label: 'Matching', icon: GitMerge },
      { id: 'map', label: 'Live Map', icon: Map },
      { id: 'audit', label: 'Audit Trail', icon: ShieldCheck },
    ],
  },
  {
    label: 'Technical / Demo',
    items: [
      { id: 'hazard_sim', label: 'Hazard Simulator', icon: AlertTriangle, tag: 'Demo' },
      { id: 'evaluation', label: 'Evaluation', icon: BarChart3, tag: 'Bench' },
    ],
  },
];

const initials = (name) => (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(s => s[0].toUpperCase()).join('');

export default function Navbar({ activeTab, setActiveTab, allowedTabs = [], user, onLogout }) {
  return (
    <aside className="sidebar" aria-label="Primary">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">RQ</div>
        <div>
          <div className="brand-title">ResQLink</div>
          <div className="brand-subtitle">Emergency Resource Coordination</div>
        </div>
      </div>

      {SECTIONS.map(section => {
        const items = section.items.filter(item => allowedTabs.includes(item.id));   // role-aware
        if (!items.length) return null;
        return (
          <nav className="nav-group" key={section.label} aria-label={section.label}>
            <div className="nav-section-label">{section.label}</div>
            {items.map(item => {
              const Icon = item.icon;
              const active = activeTab === item.id;
              return (
                <button key={item.id} type="button" className={`nav-btn ${active ? 'active' : ''}`}
                        aria-current={active ? 'page' : undefined} onClick={() => setActiveTab(item.id)}>
                  <Icon size={16} className="nav-icon" />
                  <span className="nav-label">{item.label}</span>
                  {item.tag && <span className="nav-tag" aria-hidden="true">{item.tag}</span>}
                </button>
              );
            })}
          </nav>
        );
      })}

      {user && (
        <div className="sidebar-footer" data-testid="user-badge">
          <div className="user-badge">
            <div className="user-avatar" aria-hidden="true">{initials(user.display_name)}</div>
            <div className="user-meta">
              <span className="user-badge-name" title={`Signed in as ${user.display_name}`}>{user.display_name}</span>
              <span className={`badge badge-role-${user.role}`}>{user.role}</span>
            </div>
          </div>
          <button type="button" className="btn btn-secondary btn-sm" onClick={onLogout} aria-label="Sign out">
            <LogOut size={14} /><span>Sign out</span>
          </button>
        </div>
      )}
    </aside>
  );
}
