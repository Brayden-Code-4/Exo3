import { useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react'
import Markdown from 'react-markdown'
import type { Role } from '../api'

export interface ChatMessage {
  role: Role
  content: string
}

interface ChatWindowProps {
  messages: ChatMessage[]
  loading: boolean
  draft: string
  onDraftChange: (value: string) => void
  onSend: () => void
}

export default function ChatWindow({ messages, loading, draft, onDraftChange, onSend }: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Keep the latest message in view.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!loading && draft.trim()) onSend()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter inserts a new line.
    if (event.key === 'Enter' && !event.shiftKey) handleSubmit(event)
  }

  return (
    <section className="chat">
      <div className="messages">
        {messages.length === 0 && !loading && (
          <p className="muted center">Pose ta première question à Study Buddy.</p>
        )}
        {messages.map((m, i) =>
          m.role === 'system-notification' ? (
            <div key={i} className="notification">
              {m.content}
            </div>
          ) : (
            <div key={i} className={`bubble ${m.role}`}>
              {/* The LLM answers in Markdown; user messages are shown as typed. */}
              {m.role === 'assistant' ? <Markdown>{m.content}</Markdown> : m.content}
            </div>
          ),
        )}
        {loading && <div className="bubble assistant typing">…</div>}
        <div ref={bottomRef} />
      </div>
      <form className="composer" onSubmit={handleSubmit}>
        <textarea
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Écris ton message…"
          rows={2}
          disabled={loading}
          autoFocus
        />
        <button type="submit" disabled={loading || !draft.trim()}>
          Envoyer
        </button>
      </form>
    </section>
  )
}
