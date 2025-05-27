# app/database.py
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint, Index, Table
from sqlalchemy.orm import sessionmaker, Session as SQLAlchemySession, relationship, declarative_base
from sqlalchemy.sql import func
from contextlib import contextmanager
from typing import Generator, Any

from . import config

DATABASE_URL = config.DATABASE_URL

# Ensure the directory for the SQLite database exists
if DATABASE_URL.startswith("sqlite:///./"):
    db_file_path = DATABASE_URL.replace("sqlite:///./", "")
    db_dir = os.path.dirname(db_file_path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
            print(f"DATABASE: Created directory '{db_dir}' for SQLite database.")
        except OSError as e:
            print(f"DATABASE: Error creating directory '{db_dir}': {e}. Database might fail to create if path is invalid.")
elif DATABASE_URL.startswith("sqlite:///"):
    db_file_path = DATABASE_URL.replace("sqlite:///", "/")
    db_dir = os.path.dirname(db_file_path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
            print(f"DATABASE: Created directory '{db_dir}' for SQLite database (absolute path).")
        except OSError as e:
            print(f"DATABASE: Error creating directory '{db_dir}': {e}.")


engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 15  # Increased timeout to 15 seconds (default is 5)
        } if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

@contextmanager
def db_session_scope() -> Generator[SQLAlchemySession, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def get_db() -> Generator[SQLAlchemySession, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Association Table for Article and Tag ---
article_tag_association = Table('article_tag_association', Base.metadata,
    Column('article_id', Integer, ForeignKey('articles.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

# --- Database Models ---
class RSSFeedSource(Base):
    __tablename__ = "rss_feed_sources"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    last_fetched_at = Column(DateTime(timezone=True), nullable=True)
    fetch_interval_minutes = Column(Integer, default=60)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    articles = relationship("Article", back_populates="feed_source", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<RSSFeedSource(id={self.id}, url='{self.url}', name='{self.name}')>"

class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    feed_source_id = Column(Integer, ForeignKey("rss_feed_sources.id"), nullable=True)

    url = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=True)
    publisher_name = Column(String, nullable=True)
    published_date = Column(DateTime(timezone=True), nullable=True, index=True)

    scraped_content = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    feed_source = relationship("RSSFeedSource", back_populates="articles")
    summaries = relationship("Summary", back_populates="article", cascade="all, delete-orphan")
    chat_history = relationship("ChatHistory", back_populates="article", cascade="all, delete-orphan")
    
    # Relationship to Tag model (many-to-many)
    tags = relationship("Tag", secondary=article_tag_association, back_populates="articles")

    __table_args__ = (
        Index('ix_articles_published_date_id', 'published_date', 'id'),
    )

    def __repr__(self):
        return f"<Article(id={self.id}, title='{self.title[:50]}...', url='{self.url}')>"

class Summary(Base):
    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)

    summary_text = Column(Text, nullable=False)
    prompt_used = Column(Text, nullable=True)
    model_used = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    article = relationship("Article", back_populates="summaries")

    def __repr__(self):
        return f"<Summary(id={self.id}, article_id={self.article_id}, text_start='{self.summary_text[:50]}...')>"

class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)

    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    prompt_used = Column(Text, nullable=True)
    model_used = Column(String, nullable=True)

    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    article = relationship("Article", back_populates="chat_history")

    def __repr__(self):
        return f"<ChatHistory(id={self.id}, article_id={self.article_id}, question='{self.question[:50]}...')>"

class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False) # Tag names should be unique

    # Relationship to Article model (many-to-many)
    articles = relationship("Article", secondary=article_tag_association, back_populates="tags")

    def __repr__(self):
        return f"<Tag(id={self.id}, name='{self.name}')>"


def create_db_and_tables():
    print("Attempting to create database tables...")
    try:
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully (if they didn't exist).")
    except Exception as e:
        print(f"Error creating database tables: {e}")

if __name__ == "__main__":
    create_db_and_tables()
