from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.db import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Message(Base):
    __tablename__ = "messages"
    # Constraints are named explicitly so Alembic can recreate them in SQLite batch mode.
    # The unique (conversation_id, seq) pair also rejects two requests writing the same turn concurrently.
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_id_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", name="fk_messages_conversation_id"), index=True
    )
    seq: Mapped[int]  # position of the message in its conversation, starting at 1
    role: Mapped[str] = mapped_column(String(20))  # "user" | "assistant" | "system-notification" | "note"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
