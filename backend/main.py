import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import llm
from config import ALLOWED_MODELS, DEFAULT_MODEL
from database.db import SessionLocal, get_db
from database.models import Conversation, Message

logger = logging.getLogger("study_buddy")

PREVIEW_LENGTH = 60

# Roles the LLM understands. Anything else stored in the DB (notifications, notes) stays out of its prompt.
LLM_ROLES = {"user", "assistant"}
NOTIFICATION_ROLE = "system-notification"
NOTIFICATION_EVERY = 10  # a notification each time the dialogue reaches a multiple of this many messages
NOTIFICATION_TEXT = "Notification système : Une dizaine de messages écrits."
# Custom role: a personal note written by the student. Shown in the chat, stored like any message,
# but never sent to the LLM (see build_llm_history).
NOTE_ROLE = "note"
NOTE_MAX_LENGTH = 2000
MESSAGE_MAX_LENGTH = 8000
# Added to a stopped answer when it is sent back to the LLM, so the model knows it was cut.
INTERRUPTED_MARKER = "\n\n[Réponse interrompue par l'étudiant.]"

# The system prompt lives in its own Markdown file so it can be edited and reviewed like any other document.
PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8").strip()

@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await llm.client.aclose()


app = FastAPI(title="Study Buddy Chatbot", lifespan=lifespan)


class ConversationResponse(BaseModel):
    conversation_id: int


class ConversationSummary(BaseModel):
    id: int
    created_at: datetime
    preview: str | None  # first user message, truncated; None while the conversation is empty


class ChatRequest(BaseModel):
    conversation_id: int
    message: str = Field(min_length=1, max_length=MESSAGE_MAX_LENGTH)
    model: str  # must be one of GET /models, checked server side


class NoteRequest(BaseModel):
    content: str = Field(min_length=1, max_length=NOTE_MAX_LENGTH)


class MessageResponse(BaseModel):
    seq: int
    role: str
    content: str
    created_at: datetime
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    interrupted: bool = False

    @classmethod
    def from_row(cls, m: Message) -> "MessageResponse":
        return cls(
            seq=m.seq,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            model=m.model,
            prompt_tokens=m.prompt_tokens,
            completion_tokens=m.completion_tokens,
            interrupted=m.interrupted,
        )


class ModelInfo(BaseModel):
    id: str
    label: str


class ModelsResponse(BaseModel):
    default: str
    models: list[ModelInfo]


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
        content = m.content
        if m.role == "assistant" and m.interrupted:
            content += INTERRUPTED_MARKER
        history.append({"role": m.role, "content": content})
    return history


def next_seq(rows: list[Message]) -> int:
    # seq follows every stored row (notes and notifications included) so it stays unique.
    return rows[-1].seq + 1 if rows else 1


def check_model(model: str) -> str:
    # Never trust the client: only the models listed on the server can be used.
    if model not in ALLOWED_MODELS:
        raise HTTPException(status_code=400, detail=f"Modèle non autorisé : {model!r}.")
    return model


def sse(event: dict) -> str:
    # One Server-Sent Event per JSON object; the frontend splits the stream on blank lines.
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def save_turn(
    conversation_id: int,
    user_text: str,
    reply: str,
    model: str,
    usage: llm.Usage | None,
    interrupted: bool,
) -> tuple[Message, str | None]:
    """Store the user message and the assistant reply in one transaction, once the stream is over."""
    with SessionLocal() as db:
        rows = load_messages(db, conversation_id)
        seq = next_seq(rows)
        assistant = Message(
            conversation_id=conversation_id,
            seq=seq + 1,
            role="assistant",
            content=reply,
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
            interrupted=interrupted,
        )
        db.add_all([
            Message(conversation_id=conversation_id, seq=seq, role="user", content=user_text),
            assistant,
        ])

        # Count only the dialogue (user + assistant): counting notifications or notes too would shift
        # the total off the multiples of 10 for good after the first one.
        notification = None
        dialogue_length = len(build_llm_history(rows)) + 2
        if dialogue_length % NOTIFICATION_EVERY == 0:
            notification = NOTIFICATION_TEXT
            db.add(Message(
                conversation_id=conversation_id, seq=seq + 2, role=NOTIFICATION_ROLE, content=notification
            ))
        db.commit()
        db.refresh(assistant)
        db.expunge(assistant)
        return assistant, notification


async def stream_turn(stream: llm.LLMStream, conversation_id: int, user_text: str, model: str):
    """Relay the LLM stream to the browser, then save the turn.

    - complete answer: user message + answer saved together, then a "done" event;
    - API error in the middle: nothing is saved, an "error" event tells the client it can resend;
    - client gone (Stop button): the part already generated is saved with interrupted=True.
    """
    parts: list[str] = []
    try:
        try:
            async for piece in stream:
                parts.append(piece)
                yield sse({"type": "delta", "content": piece})
        except llm.LLMError as exc:
            logger.warning("LLM stream failed: %s", exc)
            yield sse({
                "type": "error",
                "detail": "La réponse du modèle a été interrompue par une erreur. Rien n'a été enregistré, tu peux renvoyer ton message.",
            })
            return

        reply = "".join(parts)
        if not reply.strip():
            yield sse({"type": "error", "detail": "Le modèle a renvoyé une réponse vide. Rien n'a été enregistré."})
            return
        try:
            assistant, notification = save_turn(conversation_id, user_text, reply, model, stream.usage, False)
        except IntegrityError:
            yield sse({"type": "error", "detail": "La conversation a été modifiée en même temps, renvoie ton message."})
            return
        yield sse({
            "type": "done",
            "message": MessageResponse.from_row(assistant).model_dump(mode="json"),
            "notification": notification,
        })
    except (asyncio.CancelledError, GeneratorExit):
        # The browser closed the connection (Stop button, tab closed): keep what was generated so far.
        reply = "".join(parts)
        if reply.strip():
            try:
                save_turn(conversation_id, user_text, reply, model, stream.usage, True)
            except Exception:
                logger.exception("Could not save the interrupted answer")
        raise
    finally:
        await stream.aclose()


@app.get("/models")
def list_models() -> ModelsResponse:
    return ModelsResponse(
        default=DEFAULT_MODEL,
        models=[ModelInfo(id=model_id, label=label) for model_id, label in ALLOWED_MODELS.items()],
    )


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
    return [MessageResponse.from_row(m) for m in load_messages(db, conversation_id)]


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
    return MessageResponse.from_row(note)


@app.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    model = check_model(req.model)
    user_text = req.message.strip()
    if not user_text:
        raise HTTPException(status_code=422, detail="Le message est vide.")

    # Load this conversation from the database, in message order, and build what the LLM will see.
    with SessionLocal() as db:
        history = build_llm_history(load_messages(db, req.conversation_id))

    # The LLM is stateless: resend the system prompt + the whole conversation each turn.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": user_text}]

    # Open the stream before answering, so an API refusal (bad key, quota...) is still a plain 502.
    try:
        stream = await llm.open_stream(model, messages)
    except llm.LLMError as exc:
        logger.warning("LLM call refused: %s", exc)
        raise HTTPException(status_code=502, detail="L'appel au modèle a échoué.") from exc

    return StreamingResponse(
        stream_turn(stream, req.conversation_id, user_text, model),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
