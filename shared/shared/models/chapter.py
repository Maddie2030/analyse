import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("series_id", "chapter_number", name="uq_chapters_series_chapter_number"),
        UniqueConstraint("series_id", "slug", name="uq_chapters_series_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    series_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("series.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    chapter_number: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("NOW()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
        nullable=False
    )

    # Relationship mappings
    series: Mapped["Series"] = relationship("Series", back_populates="chapters")
    pages: Mapped[list["Page"]] = relationship(
        "Page", back_populates="chapter", cascade="all, delete-orphan"
    )


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("chapter_id", "page_number", name="uq_pages_chapter_page_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    chapter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    media_generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    responsive_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    responsive_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    responsive_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    encoding_version: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="4"
    )
    encoding_rows: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    encoding_columns: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    encoding_seed: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Relationship mapping
    chapter: Mapped["Chapter"] = relationship("Chapter", back_populates="pages")
