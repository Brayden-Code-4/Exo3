import type { ConversationSummary } from '../api'

interface SidebarProps {
  conversations: ConversationSummary[]
  activeId: number | null
  onSelect: (id: number) => void
  onNew: () => void
}

const dateFormat = new Intl.DateTimeFormat('fr-FR', { dateStyle: 'short', timeStyle: 'short' })

function formatDate(value: string): string {
  // SQLite returns naive UTC timestamps ("2026-10-02T17:05:00"); mark them as UTC.
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`
  return dateFormat.format(new Date(iso))
}

export default function Sidebar({ conversations, activeId, onSelect, onNew }: SidebarProps) {
  return (
    <aside className="sidebar">
      <h1 className="sidebar-title">Study Buddy</h1>
      <button className="new-button" onClick={onNew}>
        + Nouvelle conversation
      </button>
      <nav className="conversation-list">
        {conversations.length === 0 && <p className="muted">Aucune conversation.</p>}
        {conversations.map((c) => (
          <button
            key={c.id}
            className={`conversation-item${c.id === activeId ? ' active' : ''}`}
            onClick={() => onSelect(c.id)}
          >
            <span className="conversation-preview">{c.preview ?? 'Nouvelle conversation'}</span>
            <span className="conversation-date">{formatDate(c.created_at)}</span>
          </button>
        ))}
      </nav>
    </aside>
  )
}
