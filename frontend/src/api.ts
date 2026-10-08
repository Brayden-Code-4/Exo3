// Thin typed wrappers around the FastAPI backend (proxied under /api by Vite).
// The browser only talks to our backend: the RodiumAI key stays on the server.

// 'note' is our custom role: a personal note of the student, stored but never sent to the LLM.
export type Role = 'user' | 'assistant' | 'system-notification' | 'note'

export interface ConversationSummary {
  id: number
  created_at: string
  preview: string | null
}

export interface Message {
  seq: number
  role: Role
  content: string
  created_at: string
  model: string | null
  prompt_tokens: number | null
  completion_tokens: number | null
  interrupted: boolean
}

export interface ModelInfo {
  id: string
  label: string
}

export interface ModelsList {
  default: string
  models: ModelInfo[]
}

async function errorFrom(response: Response): Promise<Error> {
  // FastAPI errors look like {"detail": "..."} (or a list of validation errors for a 422).
  const body = await response.json().catch(() => null)
  const detail = typeof body?.detail === 'string' ? body.detail : null
  return new Error(detail ?? `Erreur ${response.status}`)
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new Error('Impossible de joindre le serveur.')
  }
  if (!response.ok) throw await errorFrom(response)
  return response
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init)
  return response.json() as Promise<T>
}

export function listModels(): Promise<ModelsList> {
  return request('/models')
}

export function listConversations(): Promise<ConversationSummary[]> {
  return request('/conversations')
}

export async function createConversation(): Promise<number> {
  const { conversation_id } = await request<{ conversation_id: number }>('/conversations', {
    method: 'POST',
  })
  return conversation_id
}

export function getMessages(conversationId: number): Promise<Message[]> {
  return request(`/conversations/${conversationId}/messages`)
}

export function addNote(conversationId: number, content: string): Promise<Message> {
  return request(`/conversations/${conversationId}/notes`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
}

export interface ChatResult {
  message: Message // the assistant answer, as saved in the database
  notification: string | null // set when the backend also stored a system-notification
}

// Events sent by POST /chat, one per "data: {...}" block.
type StreamEvent =
  | { type: 'delta'; content: string }
  | { type: 'done'; message: Message; notification: string | null }
  | { type: 'error'; detail: string }

interface StreamOptions {
  signal: AbortSignal // aborting it = Stop button
  onDelta: (text: string) => void
}

export async function streamChat(
  conversationId: number,
  message: string,
  model: string,
  { signal, onDelta }: StreamOptions,
): Promise<ChatResult> {
  const response = await send('/chat', {
    method: 'POST',
    body: JSON.stringify({ conversation_id: conversationId, message, model }),
    signal,
  })
  if (!response.body) throw new Error('Le navigateur ne permet pas de lire la réponse en streaming.')

  // EventSource can't POST, so the stream is read by hand: bytes -> text -> "data: ..." blocks.
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // Events are separated by a blank line; the last piece may be incomplete, keep it for later.
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() ?? ''
      for (const block of blocks) {
        if (!block.startsWith('data: ')) continue
        const event = JSON.parse(block.slice('data: '.length)) as StreamEvent
        if (event.type === 'delta') onDelta(event.content)
        else if (event.type === 'done') return { message: event.message, notification: event.notification }
        else if (event.type === 'error') throw new Error(event.detail)
      }
    }
  } finally {
    reader.releaseLock()
  }
  throw new Error('La connexion au serveur a été coupée avant la fin de la réponse.')
}
