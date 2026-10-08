import { useEffect, useRef, useState } from 'react'
import './App.css'
import {
  addNote,
  createConversation,
  getMessages,
  listConversations,
  listModels,
  streamChat,
  type ConversationSummary,
  type Message,
  type ModelInfo,
} from './api'
import ChatWindow, { type ChatMessage } from './components/ChatWindow'
import Sidebar from './components/Sidebar'

const MODEL_STORAGE_KEY = 'study-buddy-model'

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'Une erreur est survenue.'
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}

function toChatMessage(m: Message): ChatMessage {
  return {
    role: m.role,
    content: m.content,
    model: m.model,
    promptTokens: m.prompt_tokens,
    completionTokens: m.completion_tokens,
    interrupted: m.interrupted,
  }
}

// A message that failed because of the LLM, kept so it can be sent again in one click.
interface FailedSend {
  conversationId: number
  text: string
}

export default function App() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [savingNote, setSavingNote] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [noteMode, setNoteMode] = useState(false)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [model, setModel] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [failed, setFailed] = useState<FailedSend | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const busy = streaming || savingNote

  // On startup, load the allowed models and the history, and open the most recent conversation.
  useEffect(() => {
    listModels()
      .then(({ default: defaultModel, models }) => {
        setModels(models)
        // Remember the last choice, as long as the server still allows it.
        const saved = localStorage.getItem(MODEL_STORAGE_KEY)
        setModel(models.some((m) => m.id === saved) ? saved! : defaultModel)
      })
      .catch((err) => setError(errorMessage(err)))
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
        if (!cancelled) setMessages(list.map(toChatMessage))
      })
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [activeId])

  function changeModel(id: string) {
    setModel(id)
    localStorage.setItem(MODEL_STORAGE_KEY, id)
  }

  function clearError() {
    setError(null)
    setFailed(null)
  }

  function selectConversation(id: number) {
    if (busy || id === activeId) return
    clearError()
    setDraft('')
    setMessages([])
    setActiveId(id)
  }

  async function handleNew() {
    if (busy) return
    clearError()
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

  async function handleAddNote() {
    if (activeId === null) return
    const text = draft.trim()
    clearError()
    setDraft('')
    setSavingNote(true)
    try {
      const note = await addNote(activeId, text)
      setMessages((list) => [...list, toChatMessage(note)])
    } catch (err) {
      setDraft(text)
      setError(errorMessage(err))
    } finally {
      setSavingNote(false)
    }
  }

  // Replace the answer being streamed (always the last message) with a new version.
  function updateLastAnswer(update: (m: ChatMessage) => ChatMessage) {
    setMessages((list) => [...list.slice(0, -1), update(list[list.length - 1])])
  }

  async function sendToModel(conversationId: number, text: string) {
    const isFirstMessage = !messages.some((m) => m.role === 'user')
    clearError()
    // Optimistic display: the question, then an empty answer filled as the chunks arrive.
    setMessages((list) => [
      ...list,
      { role: 'user', content: text },
      { role: 'assistant', content: '', model, streaming: true },
    ])
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let received = ''
    try {
      const { message, notification } = await streamChat(conversationId, text, model, {
        signal: controller.signal,
        onDelta: (piece) => {
          received += piece
          updateLastAnswer((m) => ({ ...m, content: received }))
        },
      })
      // Show the answer as saved by the backend (with its token usage).
      updateLastAnswer(() => toChatMessage(message))
      if (notification) {
        setMessages((list) => [...list, { role: 'system-notification', content: notification }])
      }
      // The first message becomes the conversation's preview in the sidebar.
      if (isFirstMessage) setConversations(await listConversations())
    } catch (err) {
      if (isAbort(err)) {
        // Stop: the backend keeps what was generated so far (marked as interrupted), we do the same.
        if (received.trim()) {
          updateLastAnswer((m) => ({ ...m, streaming: false, interrupted: true }))
          if (isFirstMessage) setConversations(await listConversations())
        } else {
          // Nothing generated yet: nothing is saved, the question goes back to the input.
          setMessages((list) => list.slice(0, -2))
          setDraft(text)
        }
      } else {
        // The backend saved nothing: remove the turn and offer to send it again.
        setMessages((list) => list.slice(0, -2))
        setError(errorMessage(err))
        setFailed({ conversationId, text })
      }
    } finally {
      abortRef.current = null
      setStreaming(false)
    }
  }

  function handleSend() {
    if (activeId === null) return
    if (noteMode) return handleAddNote()
    const text = draft.trim()
    setDraft('')
    return sendToModel(activeId, text)
  }

  function handleRetry() {
    if (!failed || busy || failed.conversationId !== activeId) return
    return sendToModel(failed.conversationId, failed.text)
  }

  function handleEditFailed() {
    if (!failed) return
    setDraft(failed.text)
    clearError()
  }

  function handleStop() {
    abortRef.current?.abort()
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
            <span>{error}</span>
            <span className="error-actions">
              {failed && failed.conversationId === activeId && (
                <>
                  <button className="retry-button" onClick={handleRetry} disabled={busy}>
                    ↻ Réessayer
                  </button>
                  <button className="link-button" onClick={handleEditFailed} disabled={busy}>
                    Modifier
                  </button>
                </>
              )}
              <button onClick={clearError} aria-label="Fermer">
                ×
              </button>
            </span>
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
            busy={busy}
            streaming={streaming}
            draft={draft}
            noteMode={noteMode}
            models={models}
            model={model}
            onModelChange={changeModel}
            onDraftChange={setDraft}
            onNoteModeChange={setNoteMode}
            onSend={handleSend}
            onStop={handleStop}
          />
        )}
      </main>
    </div>
  )
}
