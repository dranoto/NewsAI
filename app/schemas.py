# app/schemas.py
from pydantic import BaseModel, HttpUrl, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

# --- Pydantic Models ---
class InitialConfigResponse(BaseModel):
    default_rss_feeds: List[str]
    all_db_feed_sources: List[Dict[str, Any]]
    default_articles_per_page: int
    default_summary_prompt: str
    default_chat_prompt: str
    default_tag_generation_prompt: str
    default_rss_fetch_interval_minutes: int
    path_to_extension: str
    use_headless_browser: bool
    class Config: from_attributes = True

class FeedSourceResponse(BaseModel):
    id: int
    url: str
    name: Optional[str] = None
    fetch_interval_minutes: int
    class Config: from_attributes = True

class NewsPageQuery(BaseModel):
    page: int = 1
    page_size: int = Field(default_factory=lambda: 10) 
    feed_source_ids: Optional[List[int]] = None
    tag_ids: Optional[List[int]] = None
    keyword: Optional[str] = None
    summary_prompt: Optional[str] = None
    tag_generation_prompt: Optional[str] = None

class ArticleTagResponse(BaseModel):
    id: int
    name: str
    class Config: from_attributes = True

class ArticleResult(BaseModel):
    id: int
    title: Optional[str] = None
    url: str 
    summary: Optional[str] = None
    publisher: Optional[str] = None
    published_date: Optional[datetime] = None # This is publication date
    created_at: Optional[datetime] = None # NEW: Add created_at for polling logic
    source_feed_url: Optional[str] = None
    tags: List[ArticleTagResponse] = []
    error_message: Optional[str] = None
    class Config: from_attributes = True

class PaginatedSummariesAPIResponse(BaseModel):
    search_source: str
    requested_page: int
    page_size: int
    total_articles_available: int
    total_pages: int
    processed_articles_on_page: List[ArticleResult]
    # Optionally, add the latest article timestamp of this batch here
    # latest_article_timestamp_in_batch: Optional[datetime] = None 

class ChatHistoryItem(BaseModel):
    role: str 
    content: str
    class Config: from_attributes = True

class ChatQuery(BaseModel):
    article_id: int
    question: str
    chat_prompt: Optional[str] = None
    chat_history: Optional[List[ChatHistoryItem]] = None

class ChatResponse(BaseModel):
    article_id: int
    question: str
    answer: str
    error_message: Optional[str] = None

class AddFeedRequest(BaseModel):
    url: HttpUrl
    name: Optional[str] = None
    fetch_interval_minutes: Optional[int] = Field(default_factory=lambda: 60)

class UpdateFeedRequest(BaseModel):
    name: Optional[str] = None
    fetch_interval_minutes: Optional[int] = None

class RegenerateSummaryRequest(BaseModel):
    custom_prompt: Optional[str] = None
    regenerate_tags: bool = True

class SanitizedArticleContentResponse(BaseModel):
    article_id: int
    original_url: str
    title: Optional[str] = None
    sanitized_html_content: Optional[str] = None
    error_message: Optional[str] = None
    class Config: from_attributes = True

# NEW Pydantic Model for Polling Response
class NewArticleCheckResponse(BaseModel):
    new_articles_available: bool
    latest_article_timestamp: Optional[datetime] = None
    article_count: Optional[int] = 0 # Number of new articles since last check
