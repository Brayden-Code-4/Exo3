import { useEffect, useState } from 'react'
import './App.css'
import {
  createConversation,
  getMessages,
  listConversations,
  sendMessage,
  type ConversationSummary,
} from './api'
import ChatWindow, { type ChatMessage } from './components/ChatWindow'
import Sidebar from './components/Sidebar'

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'Une erreur est survenue.'
}

export default function App() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // On startup, load the history and open the most recent conversation.
  useEffect(() => {
    listConversations()
      .then((list) => {
        setConversations(list)
        if (list.length > 0) setActiveId(list[0].id)
      })
      .catch((err) => setError(errorMessage(err)))
  }, [])

  // Load the messages whenever another conversation is opened.
  useEffect(() => {
    if (activeId === null) return
    let cancelled = false
    getMessages(activeId)
      .then((list) => {
        if (!cancelled) setMessages(list.map(({ role, content }) => ({ role, content })))
      })
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [activeId])

  function selectConversation(id: number) {
    if (loading || id === activeId) return
    setError(null)
    setDraft('')
    setMessages([])
    setActiveId(id)
  }

  async function handleNew() {
    if (loading) return
    setError(null)
    try {
      const id = await createConversation()
      setConversations((list) => [
        { id, created_at: new Date().toISOString(), preview: null },
        ...list,
      ])
      setDraft('')
      setMessages([])
      setActiveId(id)
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function handleSend() {
    if (activeId === null) return
    const text = draft.trim()
    const isFirstMessage = messages.length === 0
    setError(null)
    setDraft('')
    setMessages((list) => [...list, { role: 'user', content: text }])
    setLoading(true)
    try {
      const { reply, notification } = await sendMessage(activeId, text)
      setMessages((list) => [
        ...list,
        { role: 'assistant', content: reply },
        ...(notification ? [{ role: 'system-notification' as const, content: notification }] : []),
      ])
      // The first message becomes the conversation's preview in the sidebar.
      if (isFirstMessage) setConversations(await listConversations())
    } catch (err) {
      // The backend didn't save the turn: drop the optimistic message and give the text back.
      setMessages((list) => list.slice(0, -1))
      setDraft(text)
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onSelect={selectConversation}
        onNew={handleNew}
      />
      <main className="main">
        {error && (
          <div className="error" role="alert">
            {error}
            <button onClick={() => setError(null)} aria-label="Fermer">
              ×
            </button>
          </div>
        )}
        {activeId === null ? (
          <div className="empty">
            <p>Aucune conversation ouverte.</p>
            <button className="new-button" onClick={handleNew}>
              + Nouvelle conversation
            </button>
          </div>
        ) : (
          <ChatWindow
            messages={messages}
            loading={loading}
            draft={draft}
            onDraftChange={setDraft}
            onSend={handleSend}
          />
        )}
      </main>
    </div>
  )
}
