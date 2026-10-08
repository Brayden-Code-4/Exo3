import os
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Conversation, Message

load_dotenv()

RODIUMAI_URL = "https://api.rodiumai.io/v1/chat/completions"
RODIUMAI_API_KEY = os.environ["RODIUMAI_API_KEY"]
MODEL = os.getenv("RODIUMAI_MODEL", "anthropic/claude-sonnet-4-5-20250929")
PREVIEW_LENGTH = 60

# Roles the LLM understands. Anything else stored in the DB (e.g. notifications) stays out of its prompt.
LLM_ROLES = {"user", "assistant"}
NOTIFICATION_ROLE = "system-notification"
NOTIFICATION_EVERY = 10  # a notification each time the dialogue reaches a multiple of this many messages
NOTIFICATION_TEXT = "Notification système : Une dizaine de messages écrits."
# Custom role: a personal note written by the student. Shown in the chat, stored like any message,
# but never sent to the LLM (see build_llm_history).
NOTE_ROLE = "note"
NOTE_MAX_LENGTH = 2000

# The system prompt lives in its own Markdown file so it can be edited and reviewed like any other document.
PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8").strip()

app = FastAPI(title="Study Buddy Chatbot")


class ConversationResponse(BaseModel):
    conversation_id: int


class ConversationSummary(BaseModel):
    id: int
    created_at: datetime
    preview: str | None  # first user message, truncated; None while the conversation is empty


class ChatRequest(BaseModel):
    conversation_id: int
    message: str


class ChatResponse(BaseModel):
    reply: str
    notification: str | None = None  # set when this turn also stored a system-notification


class NoteRequest(BaseModel):
    content: str = Field(min_length=1, max_length=NOTE_MAX_LENGTH)


class MessageResponse(BaseModel):
    seq: int
    role: str
    content: str
    created_at: datetime


def load_messages(db: Session, conversation_id: int) -> list[Message]:
    # A conversation's messages in order; 404 if the conversation doesn't exist.
    if db.get(Conversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.seq)
    ).all()


def build_llm_history(rows: list[Message]) -> list[dict]:
    # The DB history is not necessarily what the LLM sees: it is filtered here, just before building the request.
    history = []
    for m in rows:
        if m.role == NOTE_ROLE:
            # Personal notes are private to the student: they are never sent to the LLM.
            continue
        if m.role not in LLM_ROLES:
            # Other app-only roles (system-notification) are not part of the dialogue either.
            continue
        history.append({"role": m.role, "content": m.content})
    return history


def next_seq(rows: list[Message]) -> int:
    # seq follows every stored row (notes and notifications included) so it stays unique.
    return rows[-1].seq + 1 if rows else 1


@app.post("/conversations", status_code=201)
def create_conversation(db: Session = Depends(get_db)) -> ConversationResponse:
    conversation = Conversation()
    db.add(conversation)
    db.commit()
    return ConversationResponse(conversation_id=conversation.id)


@app.get("/conversations")
def list_conversations(db: Session = Depends(get_db)) -> list[ConversationSummary]:
    # Newest first, each joined to its first user message for the preview (a note may come before it).
    first_user_seq = (
        select(func.min(Message.seq))
        .where(Message.conversation_id == Conversation.id, Message.role == "user")
        .correlate(Conversation)
        .scalar_subquery()
    )
    rows = db.execute(
        select(Conversation, Message.content)
        .outerjoin(Message, and_(Message.conversation_id == Conversation.id, Message.seq == first_user_seq))
        .order_by(Conversation.id.desc())
    ).all()
    return [
        ConversationSummary(
            id=conversation.id,
            created_at=conversation.created_at,
            preview=content[:PREVIEW_LENGTH] if content else None,
        )
        for conversation, content in rows
    ]


@app.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, db: Session = Depends(get_db)) -> list[MessageResponse]:
    return [
        MessageResponse(seq=m.seq, role=m.role, content=m.content, created_at=m.created_at)
        for m in load_messages(db, conversation_id)
    ]


@app.post("/conversations/{conversation_id}/notes", status_code=201)
def add_note(conversation_id: int, req: NoteRequest, db: Session = Depends(get_db)) -> MessageResponse:
    # A note is stored like any other message but triggers no LLM call.
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="La note est vide.")
    rows = load_messages(db, conversation_id)
    note = Message(conversation_id=conversation_id, seq=next_seq(rows), role=NOTE_ROLE, content=content)
    db.add(note)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="The conversation was updated concurrently, please retry.")
    return MessageResponse(seq=note.seq, role=note.role, content=note.content, created_at=note.created_at)


@app.post("/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    # Load this conversation from the database, in message order.
    rows = load_messages(db, req.conversation_id)
    history = build_llm_history(rows)
    seq = next_seq(rows)
    user_message = {"role": "user", "content": req.message}

    # The LLM is stateless: resend the system prompt + the whole conversation each turn.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history, user_message]

    try:
        response = httpx.post(
            RODIUMAI_URL,
            headers={"Authorization": f"Bearer {RODIUMAI_API_KEY}"},
            json={
                "model": MODEL,
                "messages": messages, 
                "max_tokens": 512,
                "stream": False,
            },
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="The LLM API call failed.") from exc

    reply = response.json()["choices"][0]["message"]["content"]

    # Only record the turn once the call succeeded, so a failure doesn't leave a dangling user message.
    db.add_all([
        Message(conversation_id=req.conversation_id, seq=seq, role="user", content=req.message),
        Message(conversation_id=req.conversation_id, seq=seq + 1, role="assistant", content=reply),
    ])

    # Count only the dialogue (user + assistant): counting notifications too would shift the total
    # off the multiples of 10 for good after the first one.
    notification = None
    if (len(history) + 2) % NOTIFICATION_EVERY == 0:
        notification = NOTIFICATION_TEXT
        db.add(Message(
            conversation_id=req.conversation_id, seq=seq + 2, role=NOTIFICATION_ROLE, content=notification
        ))

    try:
        db.commit()
    except IntegrityError:
        # Another request already wrote these seq numbers in this conversation while we waited for the LLM.
        db.rollback()
        raise HTTPException(
            status_code=409, detail="The conversation was updated concurrently, please retry."
        )
    return ChatResponse(reply=reply, notification=notification)
