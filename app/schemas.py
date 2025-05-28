# app/schemas.py
from pydantic import BaseModel, HttpUrl, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

# --- Pydantic Models ---
class InitialConfigResponse(BaseModel):
    """
    Response model for the initial configuration endpoint.
    Contains default settings and initial data for the frontend.
    """
    default_rss_feeds: List[str]
    all_db_feed_sources: List[Dict[str, Any]]
    default_articles_per_page: int
    default_summary_prompt: str
    default_chat_prompt: str
    default_tag_generation_prompt: str
    default_rss_fetch_interval_minutes: int
    path_to_extension: str
    use_headless_browser: bool

    class Config:
        from_attributes = True # or orm_mode = True for Pydantic v1

class FeedSourceResponse(BaseModel):
    """
    Response model for an individual RSS feed source.
    """
    id: int
    url: str
    name: Optional[str] = None
    fetch_interval_minutes: int

    class Config:
        from_attributes = True

class NewsPageQuery(BaseModel):
    """
    Request model for querying a page of news summaries.
    Includes pagination, filtering, and custom prompt options.
    """
    page: int = 1
    page_size: int = Field(default_factory=lambda: 10) 
    feed_source_ids: Optional[List[int]] = None
    tag_ids: Optional[List[int]] = None
    keyword: Optional[str] = None
    summary_prompt: Optional[str] = None
    tag_generation_prompt: Optional[str] = None

class ArticleTagResponse(BaseModel):
    """
    Response model for an individual tag associated with an article.
    """
    id: int
    name: str

    class Config:
        from_attributes = True

class ArticleResult(BaseModel):
    """
    Response model for a single processed article, including its summary and tags.
    """
    id: int
    title: Optional[str] = None
    url: str # This is the original article URL
    summary: Optional[str] = None
    publisher: Optional[str] = None
    published_date: Optional[datetime] = None
    source_feed_url: Optional[str] = None
    tags: List[ArticleTagResponse] = []
    error_message: Optional[str] = None

    class Config:
        from_attributes = True

class PaginatedSummariesAPIResponse(BaseModel):
    """
    Response model for a paginated list of news summaries.
    Includes metadata about the pagination and the list of articles.
    """
    search_source: str
    requested_page: int
    page_size: int
    total_articles_available: int
    total_pages: int
    processed_articles_on_page: List[ArticleResult]

class ChatHistoryItem(BaseModel):
    """
    Model for a single item in a chat history, representing either a user message or an AI response.
    """
    role: str 
    content: str

    class Config:
        from_attributes = True

class ChatQuery(BaseModel):
    """
    Request model for initiating or continuing a chat about an article.
    """
    article_id: int
    question: str
    chat_prompt: Optional[str] = None
    chat_history: Optional[List[ChatHistoryItem]] = None

class ChatResponse(BaseModel):
    """
    Response model for a chat interaction, providing the AI's answer.
    """
    article_id: int
    question: str
    answer: str
    error_message: Optional[str] = None

class AddFeedRequest(BaseModel):
    """
    Request model for adding a new RSS feed source.
    """
    url: HttpUrl
    name: Optional[str] = None
    fetch_interval_minutes: Optional[int] = Field(default_factory=lambda: 60)

class UpdateFeedRequest(BaseModel):
    """
    Request model for updating an existing RSS feed source's settings.
    """
    name: Optional[str] = None
    fetch_interval_minutes: Optional[int] = None

class RegenerateSummaryRequest(BaseModel):
    """
    Request model for regenerating an article's summary, optionally with a custom prompt and tag regeneration.
    """
    custom_prompt: Optional[str] = None
    regenerate_tags: bool = True

# NEW Pydantic Model for Sanitized Content Response
class SanitizedArticleContentResponse(BaseModel):
    """
    Response model for returning the sanitized full HTML content of an article.
    """
    article_id: int
    original_url: str
    title: Optional[str] = None
    sanitized_html_content: Optional[str] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True
