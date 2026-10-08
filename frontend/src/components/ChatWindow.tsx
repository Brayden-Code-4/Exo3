import { useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react'
import Markdown from 'react-markdown'
import type { ModelInfo, Role } from '../api'

export interface ChatMessage {
  role: Role
  content: string
  model?: string | null
  promptTokens?: number | null
  completionTokens?: number | null
  interrupted?: boolean
  streaming?: boolean // answer still being generated
}

interface ChatWindowProps {
  messages: ChatMessage[]
  busy: boolean // a note is being saved or an answer is streaming
  streaming: boolean
  draft: string
  noteMode: boolean
  models: ModelInfo[]
  model: string
  onModelChange: (model: string) => void
  onDraftChange: (value: string) => void
  onNoteModeChange: (value: boolean) => void
  onSend: () => void
  onStop: () => void
}

const numberFormat = new Intl.NumberFormat('fr-FR')

function AnswerMeta({ message, models }: { message: ChatMessage; models: ModelInfo[] }) {
  if (message.streaming) return null
  const label = models.find((m) => m.id === message.model)?.label ?? message.model
  const parts: string[] = []
  if (label) parts.push(label)
  if (message.promptTokens != null && message.completionTokens != null) {
    const total = message.promptTokens + message.completionTokens
    parts.push(
      `${numberFormat.format(total)} tokens (${numberFormat.format(message.promptTokens)} entrée · ${numberFormat.format(message.completionTokens)} sortie)`,
    )
  }
  if (message.interrupted) parts.push('⏹ réponse interrompue')
  if (parts.length === 0) return null
  return <div className="answer-meta">{parts.join(' · ')}</div>
}

export default function ChatWindow({
  messages,
  busy,
  streaming,
  draft,
  noteMode,
  models,
  model,
  onModelChange,
  onDraftChange,
  onNoteModeChange,
  onSend,
  onStop,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Keep the latest message in view, also while the answer grows.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: streaming ? 'auto' : 'smooth' })
  }, [messages, streaming])

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!busy && draft.trim()) onSend()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter inserts a new line.
    if (event.key === 'Enter' && !event.shiftKey) handleSubmit(event)
  }

  return (
    <section className="chat">
      <header className="chat-header">
        <label className="model-picker">
          Modèle
          <select value={model} onChange={(e) => onModelChange(e.target.value)} disabled={streaming}>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      </header>
      <div className="messages">
        {messages.length === 0 && (
          <p className="muted center">Pose ta première question Python à Study Buddy.</p>
        )}
        {messages.map((m, i) =>
          m.role === 'system-notification' ? (
            <div key={i} className="notification">
              {m.content}
            </div>
          ) : m.role === 'note' ? (
            <div key={i} className="note" title="Note personnelle : jamais envoyée au tuteur">
              <span className="note-label">📝 Ma note</span>
              {m.content}
            </div>
          ) : m.role === 'assistant' ? (
            <div key={i} className="answer">
              <div className={`bubble assistant${m.streaming ? ' streaming' : ''}`}>
                {/* The LLM answers in Markdown. */}
                {m.content ? <Markdown>{m.content}</Markdown> : <span className="typing">…</span>}
              </div>
              <AnswerMeta message={m} models={models} />
            </div>
          ) : (
            <div key={i} className={`bubble ${m.role}`}>
              {m.content}
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>
      <form className={`composer${noteMode ? ' note-mode' : ''}`} onSubmit={handleSubmit}>
        <label className="note-toggle" title="Une note reste dans la conversation mais n'est jamais envoyée au tuteur">
          <input
            type="checkbox"
            checked={noteMode}
            onChange={(e) => onNoteModeChange(e.target.checked)}
            disabled={busy}
          />
          Note
        </label>
        <textarea
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={noteMode ? 'Écris une note pour toi (non envoyée au tuteur)…' : 'Écris ton message…'}
          rows={2}
          disabled={busy}
          autoFocus
        />
        {streaming ? (
          <button type="button" className="stop-button" onClick={onStop}>
            ⏹ Stop
          </button>
        ) : (
          <button type="submit" disabled={busy || !draft.trim()}>
            {noteMode ? 'Ajouter la note' : 'Envoyer'}
          </button>
        )}
      </form>
    </section>
  )
}
