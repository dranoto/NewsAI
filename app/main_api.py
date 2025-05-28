# app/main_api.py
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, Field
from typing import List, Optional, Dict, Any
import math
from datetime import datetime, timezone, timedelta
import asyncio
import logging

from sqlalchemy.orm import Session as SQLAlchemySession, joinedload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, and_, func as sql_func
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from langchain_google_genai import GoogleGenerativeAI # For type hinting LLM instances
from langchain_core.documents import Document

from . import rss_client, scraper, summarizer, config as app_config, database
from .database import Article, Summary, ChatHistory, RSSFeedSource, Tag, get_db, db_session_scope, create_db_and_tables, article_tag_association

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(title="News Summarizer API & Frontend (DB & Scheduler & Tags & Search & Chat History & Extension)", version="1.8.5") # Version increment

# --- Global Variables & Scheduler ---
llm_summary_instance: Optional[GoogleGenerativeAI] = None
llm_chat_instance: Optional[GoogleGenerativeAI] = None
llm_tag_instance: Optional[GoogleGenerativeAI] = None
scheduler = AsyncIOScheduler(timezone="UTC")
rss_update_lock = asyncio.Lock()

@app.on_event("startup")
async def startup_event():
    global llm_summary_instance, llm_chat_instance, llm_tag_instance, scheduler
    logger.info("MAIN_API: Application startup initiated...")

    logger.info("MAIN_API: Initializing database...")
    database.create_db_and_tables()

    with db_session_scope() as db:
        if app_config.RSS_FEED_URLS:
            logger.info(f"MAIN_API: Ensuring initial RSS feeds are in DB: {app_config.RSS_FEED_URLS}")
            rss_client.add_initial_feeds_to_db(db, app_config.RSS_FEED_URLS)
        else:
            logger.info("MAIN_API: No initial RSS_FEED_URLS configured in app_config to add to DB.")

    logger.info("MAIN_API: Attempting to initialize LLM instances...")
    try:
        if not app_config.GEMINI_API_KEY:
            logger.critical("MAIN_API: CRITICAL ERROR: GEMINI_API_KEY not found. LLM features will be disabled.")
        else:
            llm_summary_instance = summarizer.initialize_llm(
                api_key=app_config.GEMINI_API_KEY,
                model_name=app_config.DEFAULT_SUMMARY_MODEL_NAME,
                temperature=0.2, max_output_tokens=app_config.SUMMARY_MAX_OUTPUT_TOKENS
            )
            if llm_summary_instance: logger.info(f"MAIN_API: Summarization LLM ({app_config.DEFAULT_SUMMARY_MODEL_NAME}) initialized.")
            else: logger.critical("MAIN_API: CRITICAL ERROR: Summarization LLM failed to initialize.")

            llm_chat_instance = summarizer.initialize_llm(
                api_key=app_config.GEMINI_API_KEY,
                model_name=app_config.DEFAULT_CHAT_MODEL_NAME,
                temperature=0.5, 
                max_output_tokens=app_config.CHAT_MAX_OUTPUT_TOKENS
            )
            if llm_chat_instance: logger.info(f"MAIN_API: Chat LLM ({app_config.DEFAULT_CHAT_MODEL_NAME}) initialized.")
            else: logger.critical("MAIN_API: CRITICAL ERROR: Chat LLM failed to initialize.")

            llm_tag_instance = summarizer.initialize_llm(
                api_key=app_config.GEMINI_API_KEY,
                model_name=app_config.DEFAULT_TAG_MODEL_NAME,
                temperature=0.1, 
                max_output_tokens=app_config.TAG_MAX_OUTPUT_TOKENS
            )
            if llm_tag_instance: logger.info(f"MAIN_API: Tag Generation LLM ({app_config.DEFAULT_TAG_MODEL_NAME}) initialized.")
            else: logger.critical("MAIN_API: CRITICAL ERROR: Tag Generation LLM failed to initialize.")

    except Exception as e:
        logger.critical(f"MAIN_API: CRITICAL ERROR during LLM Init: {e}.", exc_info=True)
        llm_summary_instance = None
        llm_chat_instance = None
        llm_tag_instance = None


    if not scheduler.running:
        scheduler.add_job(
            trigger_rss_update_all_feeds,
            trigger=IntervalTrigger(minutes=app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES),
            id="update_all_feeds_job",
            name="Periodic RSS Feed Update",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc), # Run immediately on startup
            max_instances=1, # Ensure only one instance of this job runs at a time
            coalesce=True # If multiple runs are missed, only run the latest one
        )
        scheduler.start()
        logger.info(f"MAIN_API: APScheduler started. RSS feeds will be checked every {app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES} minutes.")
    else:
        logger.info("MAIN_API: APScheduler already running.")

    logger.info("MAIN_API: Application startup complete.")

@app.on_event("shutdown")
def shutdown_event():
    global scheduler
    if scheduler.running:
        logger.info("MAIN_API: Shutting down APScheduler...")
        scheduler.shutdown()
    logger.info("MAIN_API: Application shutdown complete.")


async def trigger_rss_update_all_feeds():
    if rss_update_lock.locked():
        logger.info("SCHEDULER_JOB/BG_TASK: RSS update already in progress. Skipping this run.")
        return

    async with rss_update_lock:
        logger.info("SCHEDULER_JOB/BG_TASK: Acquired lock. Triggering update_all_subscribed_feeds...")
        try:
            with db_session_scope() as db: # Creates a new session for this background task
                await rss_client.update_all_subscribed_feeds(db)
            logger.info("SCHEDULER_JOB/BG_TASK: update_all_subscribed_feeds task finished successfully.")
        except Exception as e:
            logger.error(f"SCHEDULER_JOB/BG_TASK: Exception during update_all_subscribed_feeds: {e}", exc_info=True)
        # Lock is released automatically when exiting the 'async with' block
    logger.info("SCHEDULER_JOB/BG_TASK: Lock released.")


# --- Pydantic Models ---
class InitialConfigResponse(BaseModel):
    default_rss_feeds: List[str]
    all_db_feed_sources: List[Dict[str, Any]]
    default_articles_per_page: int
    default_summary_prompt: str
    default_chat_prompt: str
    default_tag_generation_prompt: str
    default_rss_fetch_interval_minutes: int
    path_to_extension: str # Added
    use_headless_browser: bool # Added

class FeedSourceResponse(BaseModel):
    id: int
    url: str
    name: Optional[str] = None
    fetch_interval_minutes: int
    class Config:
        from_attributes = True

class NewsPageQuery(BaseModel):
    page: int = 1
    page_size: int = Field(default_factory=lambda: app_config.DEFAULT_PAGE_SIZE)
    feed_source_ids: Optional[List[int]] = None
    tag_ids: Optional[List[int]] = None
    keyword: Optional[str] = None
    summary_prompt: Optional[str] = None
    tag_generation_prompt: Optional[str] = None

class ArticleTagResponse(BaseModel):
    id: int
    name: str
    class Config:
        from_attributes = True

class ArticleResult(BaseModel):
    id: int
    title: str | None = None
    url: str
    summary: str | None = None
    publisher: str | None = None
    published_date: Optional[datetime] = None
    source_feed_url: str | None = None
    tags: List[ArticleTagResponse] = []
    error_message: str | None = None
    class Config:
        from_attributes = True

class PaginatedSummariesAPIResponse(BaseModel):
    search_source: str
    requested_page: int
    page_size: int
    total_articles_available: int
    total_pages: int
    processed_articles_on_page: list[ArticleResult]

class ChatHistoryItem(BaseModel):
    role: str # "user" or "ai"
    content: str
    class Config:
        from_attributes = True # Allow creation from ORM objects if needed

class ChatQuery(BaseModel):
    article_id: int
    question: str
    chat_prompt: Optional[str] = None
    chat_history: Optional[List[ChatHistoryItem]] = None # Expecting list of dicts from frontend

class ChatResponse(BaseModel):
    article_id: int
    question: str
    answer: str
    error_message: str | None = None

class AddFeedRequest(BaseModel):
    url: HttpUrl # FastAPI will validate this
    name: Optional[str] = None
    fetch_interval_minutes: Optional[int] = Field(default_factory=lambda: app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES)

class UpdateFeedRequest(BaseModel):
    name: Optional[str] = None
    fetch_interval_minutes: Optional[int] = None

class RegenerateSummaryRequest(BaseModel):
    custom_prompt: Optional[str] = None
    regenerate_tags: bool = True


# --- Helper for Preloading (Includes Tagging) ---
async def _preload_summaries_and_tags_for_articles(
    article_data_to_preload: List[Dict[str, Any]],
    custom_summary_prompt: Optional[str] = None,
    custom_tag_prompt: Optional[str] = None
):
    if not article_data_to_preload or (not llm_summary_instance and not llm_tag_instance):
        if not llm_summary_instance: logger.warning("BACKGROUND PRELOAD: Summarization LLM not available.")
        if not llm_tag_instance: logger.warning("BACKGROUND PRELOAD: Tag Generation LLM not available.")
        if not article_data_to_preload: logger.info("BACKGROUND PRELOAD: No articles provided for preloading.")
        return

    logger.info(f"BACKGROUND PRELOAD: Starting for {len(article_data_to_preload)} articles (Summaries & Tags).")
    processed_count = 0
    successfully_summarized_count = 0
    successfully_tagged_count = 0

    with db_session_scope() as db: # Use a dedicated session for this background task
        for i, article_data in enumerate(article_data_to_preload):
            article_id = article_data.get("id")
            article_url = article_data.get("url")

            logger.info(f"BACKGROUND PRELOAD: Processing item {i+1}/{len(article_data_to_preload)}: Article ID {article_id}, URL {article_url[:60]}...")

            if not article_id or not article_url:
                logger.warning(f"BACKGROUND PRELOAD: Skipping item {i+1} due to missing ID or URL: {article_data}")
                continue

            try:
                article_db_obj = db.query(Article).options(joinedload(Article.tags)).filter(Article.id == article_id).first()
                if not article_db_obj:
                    logger.warning(f"BACKGROUND PRELOAD: Article ID {article_id} not found in DB. Skipping.")
                    continue

                scraped_content = article_db_obj.scraped_content
                needs_scraping = not scraped_content or scraped_content.startswith("Error:") or scraped_content.startswith("Content Error:")
                
                if needs_scraping:
                    logger.info(f"BACKGROUND PRELOAD: Scraping for Article ID {article_id} ({article_url[:50]}...)")
                    scraped_docs = await scraper.scrape_urls(
                        [article_url],
                        path_to_extension_folder=app_config.PATH_TO_EXTENSION,
                        use_headless_browser=app_config.USE_HEADLESS_BROWSER
                    )
                    current_scraped_content_error = None
                    if scraped_docs and scraped_docs[0]:
                        sc_doc = scraped_docs[0]
                        if not sc_doc.metadata.get("error") and sc_doc.page_content and sc_doc.page_content.strip():
                            scraped_content = sc_doc.page_content
                            article_db_obj.scraped_content = scraped_content
                            logger.info(f"BACKGROUND PRELOAD: Successfully scraped Article ID {article_id}. Length: {len(scraped_content)}")
                        else:
                            error_val = sc_doc.metadata.get("error", "Unknown scraping error during preload")
                            article_db_obj.scraped_content = f"Scraping Error: {error_val}"
                            current_scraped_content_error = article_db_obj.scraped_content
                    else:
                        article_db_obj.scraped_content = "Scraping Error: No document returned by scraper."
                        current_scraped_content_error = article_db_obj.scraped_content
                    
                    db.add(article_db_obj)
                    try:
                        db.commit()
                        db.refresh(article_db_obj)
                    except Exception as e_commit_scrape:
                        db.rollback()
                        logger.error(f"BACKGROUND PRELOAD: Error committing scraped content for Article ID {article_id}: {e_commit_scrape}", exc_info=True)
                        continue # Skip to next article if commit fails
                    
                    if current_scraped_content_error:
                        logger.warning(f"BACKGROUND PRELOAD: Scraping failed for Article ID {article_id}. Error: {current_scraped_content_error}. Skipping summarization & tagging.")
                        continue

                # Summarization
                if llm_summary_instance and scraped_content and not scraped_content.startswith("Error:"):
                    existing_summary = db.query(Summary).filter(Summary.article_id == article_id).order_by(Summary.created_at.desc()).first()
                    needs_summary = not existing_summary or not existing_summary.summary_text or \
                                    existing_summary.summary_text.startswith("Error:") or \
                                    existing_summary.summary_text.lower().startswith("content empty") or \
                                    existing_summary.summary_text.lower().startswith("content too short")
                    
                    if needs_summary:
                        logger.info(f"BACKGROUND PRELOAD: Summarizing Article ID {article_id} ({article_url[:50]}...)")
                        lc_doc = Document(page_content=scraped_content, metadata={"source": article_url, "id": article_id})
                        summary_text = await summarizer.summarize_document_content(lc_doc, llm_summary_instance, custom_summary_prompt)
                        
                        # Delete old summaries before adding new one
                        db.query(Summary).filter(Summary.article_id == article_id).delete(synchronize_session=False)

                        new_summary_db = Summary(
                            article_id=article_id,
                            summary_text=summary_text,
                            prompt_used=custom_summary_prompt or app_config.DEFAULT_SUMMARY_PROMPT,
                            model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME
                        )
                        db.add(new_summary_db)
                        try:
                            db.commit()
                            logger.info(f"BACKGROUND PRELOAD: Saved summary for Article ID {article_id}. Length: {len(summary_text)}")
                            successfully_summarized_count +=1
                        except Exception as e_commit_sum:
                            db.rollback()
                            logger.error(f"BACKGROUND PRELOAD: Error committing summary for Article ID {article_id}: {e_commit_sum}", exc_info=True)

                # Tag Generation
                db.refresh(article_db_obj) # Ensure tags collection is fresh before checking
                if llm_tag_instance and scraped_content and not scraped_content.startswith("Error:"):
                    if not article_db_obj.tags: # Only generate if no tags exist
                        logger.info(f"BACKGROUND PRELOAD: Generating tags for Article ID {article_id} ({article_url[:50]}...)")
                        tag_names = await summarizer.generate_tags_for_text(scraped_content, llm_tag_instance, custom_tag_prompt)
                        
                        if tag_names:
                            for tag_name in tag_names:
                                tag_name_cleaned = tag_name.strip().lower() 
                                if not tag_name_cleaned: continue

                                tag_db = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                                if not tag_db:
                                    tag_db = Tag(name=tag_name_cleaned)
                                    db.add(tag_db)
                                    try:
                                        db.flush() # Flush to get ID or catch IntegrityError if another concurrent process created it
                                    except IntegrityError: # Tag was created by another process concurrently
                                        db.rollback()
                                        tag_db = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                                    except Exception as e_flush_tag:
                                        db.rollback()
                                        logger.error(f"BACKGROUND PRELOAD: Error flushing new tag '{tag_name_cleaned}' for Article ID {article_id}: {e_flush_tag}", exc_info=True)
                                        continue # Skip this tag

                                if tag_db and tag_db not in article_db_obj.tags:
                                    article_db_obj.tags.append(tag_db)
                            
                            try:
                                db.commit() # Commit changes to article_db_obj.tags and any new Tag objects
                                logger.info(f"BACKGROUND PRELOAD: Saved tags for Article ID {article_id}: {tag_names}")
                                successfully_tagged_count += 1
                            except Exception as e_commit_tags:
                                db.rollback()
                                logger.error(f"BACKGROUND PRELOAD: Error committing tags for Article ID {article_id}: {e_commit_tags}", exc_info=True)
                
                elif not scraped_content or scraped_content.startswith("Error:"):
                     logger.warning(f"BACKGROUND PRELOAD: Skipping summary & tags for Article ID {article_id} due to missing/error content ('{str(scraped_content)[:50]}...').")


            except Exception as e_article_preload:
                logger.error(f"BACKGROUND PRELOAD: UNHANDLED EXCEPTION while processing Article ID {article_id} (URL: {article_url}): {e_article_preload}", exc_info=True)
                db.rollback() # Rollback any uncommitted changes for this article
            finally:
                processed_count += 1

    logger.info(f"BACKGROUND PRELOAD: Finished processing batch. Attempted: {processed_count}/{len(article_data_to_preload)}. Summarized: {successfully_summarized_count}. Tagged: {successfully_tagged_count}.")


# --- API Endpoints ---
@app.get("/api/initial-config", response_model=InitialConfigResponse)
async def get_initial_config_endpoint(db: SQLAlchemySession = Depends(get_db)):
    db_feeds = db.query(RSSFeedSource).order_by(RSSFeedSource.name).all()
    db_feed_sources_response = [
        {"id": feed.id, "url": feed.url, "name": feed.name, "fetch_interval_minutes": feed.fetch_interval_minutes}
        for feed in db_feeds
    ]
    return InitialConfigResponse(
        default_rss_feeds=app_config.RSS_FEED_URLS,
        all_db_feed_sources=db_feed_sources_response,
        default_articles_per_page=app_config.DEFAULT_PAGE_SIZE,
        default_summary_prompt=app_config.DEFAULT_SUMMARY_PROMPT,
        default_chat_prompt=app_config.DEFAULT_CHAT_PROMPT,
        default_tag_generation_prompt=app_config.DEFAULT_TAG_GENERATION_PROMPT,
        default_rss_fetch_interval_minutes=app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES,
        path_to_extension=app_config.PATH_TO_EXTENSION, # Added
        use_headless_browser=app_config.USE_HEADLESS_BROWSER # Added
    )

@app.post("/api/get-news-summaries", response_model=PaginatedSummariesAPIResponse)
async def get_news_summaries_endpoint(query: NewsPageQuery, background_tasks: BackgroundTasks, db: SQLAlchemySession = Depends(get_db)):
    if not llm_summary_instance and not llm_tag_instance: # Check if core services are up
        raise HTTPException(status_code=503, detail="Core AI services (Summarization/Tagging LLM) unavailable.")

    # Base query construction
    db_query = db.query(Article)
    search_source_display_parts = []

    if query.feed_source_ids:
        db_query = db_query.filter(Article.feed_source_id.in_(query.feed_source_ids))
        source_names = db.query(RSSFeedSource.name).filter(RSSFeedSource.id.in_(query.feed_source_ids)).all()
        search_source_display_parts.append(f"Feeds: {', '.join([name[0] for name in source_names if name[0]]) or 'Selected Feeds'}")

    if query.tag_ids:
        # Apply filter for each tag ID ensuring article has all specified tags (AND logic for multiple tags)
        for tag_id in query.tag_ids:
            db_query = db_query.filter(Article.tags.any(Tag.id == tag_id))
        
        tag_names = db.query(Tag.name).filter(Tag.id.in_(query.tag_ids)).all()
        search_source_display_parts.append(f"Tags: {', '.join([name[0] for name in tag_names if name[0]]) or 'Selected Tags'}")


    if query.keyword:
        keyword_like = f"%{query.keyword}%"
        db_query = db_query.filter(
            or_(
                Article.title.ilike(keyword_like),
                Article.scraped_content.ilike(keyword_like),
                # Consider searching in summaries too if they are reliably populated
                # Article.summaries.any(Summary.summary_text.ilike(keyword_like)) 
            )
        )
        search_source_display_parts.append(f"Keyword: '{query.keyword}'")

    search_source_display = " & ".join(search_source_display_parts) if search_source_display_parts else "All Articles"
    
    # Eager load related data to reduce individual queries per article
    db_query = db_query.options(joinedload(Article.tags), joinedload(Article.feed_source)) # Keep joinedload for summaries if needed later
    db_query = db_query.order_by(Article.published_date.desc().nullslast(), Article.id.desc())

    # Pagination logic
    total_articles_available = db_query.count()
    total_pages = math.ceil(total_articles_available / query.page_size) if query.page_size > 0 else 0

    current_page_for_slice = query.page
    if current_page_for_slice < 1: current_page_for_slice = 1
    if current_page_for_slice > total_pages and total_pages > 0 : current_page_for_slice = total_pages # Cap page to max if out of bounds

    offset = (current_page_for_slice - 1) * query.page_size
    articles_from_db = db_query.limit(query.page_size).offset(offset).all()

    results_on_page = []
    articles_needing_processing_db_objects = [] # Store full DB objects for on-demand processing

    for article_db_obj in articles_from_db:
        # Initial assembly of article data for response
        article_result_data = {
            "id": article_db_obj.id,
            "title": article_db_obj.title,
            "url": article_db_obj.url,
            "publisher": article_db_obj.feed_source.name if article_db_obj.feed_source else article_db_obj.publisher_name,
            "published_date": article_db_obj.published_date,
            "source_feed_url": article_db_obj.feed_source.url if article_db_obj.feed_source else None,
            "summary": None, # Will be populated if exists or generated
            "tags": [ArticleTagResponse.from_orm(tag) for tag in article_db_obj.tags], # Populate from eager-loaded tags
            "error_message": None
        }

        # Check for existing summary
        latest_summary_obj = db.query(Summary).filter(Summary.article_id == article_db_obj.id).order_by(Summary.created_at.desc()).first()

        needs_processing = False
        current_error_parts = []

        # Check if scraping is needed
        if not article_db_obj.scraped_content or article_db_obj.scraped_content.startswith("Error:"):
            needs_processing = True
            current_error_parts.append("Content needs scraping.")
        
        # Check if summarization is needed
        if not latest_summary_obj or latest_summary_obj.summary_text.startswith("Error:"):
            needs_processing = True
            # Add specific error from summary if it exists, otherwise generic message
            current_error_parts.append(latest_summary_obj.summary_text if latest_summary_obj and latest_summary_obj.summary_text.startswith("Error:") else "Summary needs generation.")
        elif latest_summary_obj: # Summary exists and is not an error
            article_result_data["summary"] = latest_summary_obj.summary_text
        
        # Check if tags are needed (tags are already loaded via joinedload)
        if not article_db_obj.tags: # Check if the .tags collection is empty
            needs_processing = True
            current_error_parts.append("Tags need generation.")
        
        if current_error_parts:
            article_result_data["error_message"] = " | ".join(current_error_parts)

        if needs_processing:
            articles_needing_processing_db_objects.append(article_db_obj) # Add the full DB object

        results_on_page.append(ArticleResult(**article_result_data))

    # On-demand processing for articles on the current page that need it
    if articles_needing_processing_db_objects:
        logger.info(f"MAIN API: Found {len(articles_needing_processing_db_objects)} articles needing scraping/summary/tags for current page.")

        for art_db_obj_to_process in articles_needing_processing_db_objects:
            # Refresh the object to ensure it's current, especially if it was modified in a loop iteration
            # (though less critical here as we process one by one from a list of objects already fetched)
            db.refresh(art_db_obj_to_process) 
            if art_db_obj_to_process.feed_source: db.refresh(art_db_obj_to_process.feed_source)

            scraped_content_for_ai = art_db_obj_to_process.scraped_content
            
            # --- Scraping (if needed) ---
            if not scraped_content_for_ai or scraped_content_for_ai.startswith("Error:"):
                logger.info(f"MAIN API: Scraping {art_db_obj_to_process.url[:70]}...")
                scraped_docs = await scraper.scrape_urls(
                    [art_db_obj_to_process.url],
                    path_to_extension_folder=app_config.PATH_TO_EXTENSION,
                    use_headless_browser=app_config.USE_HEADLESS_BROWSER
                )
                if scraped_docs and scraped_docs[0] and not scraped_docs[0].metadata.get("error") and scraped_docs[0].page_content:
                    scraped_content_for_ai = scraped_docs[0].page_content
                    art_db_obj_to_process.scraped_content = scraped_content_for_ai
                else:
                    error_val = scraped_docs[0].metadata.get("error", "Unknown scraping error") if scraped_docs and scraped_docs[0] else "Scraping failed"
                    art_db_obj_to_process.scraped_content = f"Scraping Error: {error_val}"
                    scraped_content_for_ai = art_db_obj_to_process.scraped_content # Update local var with error string
                db.add(art_db_obj_to_process)
                try: 
                    db.commit() 
                    db.refresh(art_db_obj_to_process) # Refresh after commit
                except Exception as e_commit: 
                    db.rollback()
                    logger.error(f"Error committing scrape for article {art_db_obj_to_process.id}: {e_commit}", exc_info=True)
                    # Update results_on_page to reflect scraping error immediately
                    for res_art in results_on_page:
                        if res_art.id == art_db_obj_to_process.id:
                            res_art.error_message = art_db_obj_to_process.scraped_content # Show the scraping error
                            break
                    continue # Skip further processing for this article if scraping commit failed

            # --- Summarization (if valid content and LLM available) ---
            if llm_summary_instance and scraped_content_for_ai and not scraped_content_for_ai.startswith("Error:"):
                # Re-check if summary is still needed (e.g. if scraping just happened)
                latest_summary_obj = db.query(Summary).filter(Summary.article_id == art_db_obj_to_process.id).order_by(Summary.created_at.desc()).first()
                if not latest_summary_obj or latest_summary_obj.summary_text.startswith("Error:"):
                    logger.info(f"MAIN API: Summarizing {art_db_obj_to_process.url[:70]}...")
                    lc_doc_to_summarize = Document(page_content=scraped_content_for_ai, metadata={"source": art_db_obj_to_process.url, "id": art_db_obj_to_process.id})
                    summary_text = await summarizer.summarize_document_content(
                        lc_doc_to_summarize, llm_summary_instance, query.summary_prompt # Use prompt from query
                    )
                    # Delete old summaries before adding new one
                    db.query(Summary).filter(Summary.article_id == art_db_obj_to_process.id).delete(synchronize_session=False)
                    new_summary_db = Summary(
                        article_id=art_db_obj_to_process.id,
                        summary_text=summary_text,
                        prompt_used=query.summary_prompt or app_config.DEFAULT_SUMMARY_PROMPT,
                        model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME
                    )
                    db.add(new_summary_db)
                    try: 
                        db.commit()
                        db.refresh(new_summary_db) # Refresh the summary object
                    except Exception as e_commit: 
                        db.rollback()
                        logger.error(f"Error committing summary for article {art_db_obj_to_process.id}: {e_commit}", exc_info=True)
                        summary_text = f"Error saving summary: {e_commit}" # Reflect error in summary_text
                    
                    # Update the summary in the response object
                    for res_art in results_on_page:
                        if res_art.id == art_db_obj_to_process.id:
                            res_art.summary = summary_text if not summary_text.startswith("Error:") else None
                            if summary_text.startswith("Error:"):
                                res_art.error_message = (res_art.error_message + " | " if res_art.error_message else "") + summary_text
                            else: # Clear summary related error if successful
                                if res_art.error_message: res_art.error_message = res_art.error_message.replace("Summary needs generation.","").replace("Summary processing issue.","").replace(" | "," ").strip()
                            break
            
            # --- Tag Generation (if valid content, LLM available, and no existing tags) ---
            db.refresh(art_db_obj_to_process) # Refresh to get latest state, including .tags collection
            if llm_tag_instance and scraped_content_for_ai and not scraped_content_for_ai.startswith("Error:") and not art_db_obj_to_process.tags:
                logger.info(f"MAIN API: Generating tags for {art_db_obj_to_process.url[:70]}...")
                tag_names_generated = await summarizer.generate_tags_for_text(
                    scraped_content_for_ai, llm_tag_instance, query.tag_generation_prompt # Use prompt from query
                )
                if tag_names_generated:
                    art_db_obj_to_process.tags.clear() # Clear existing tags in session before adding new ones
                    db.flush() # Process the clear operation

                    newly_added_tags_for_response = []
                    for tag_name in tag_names_generated:
                        tag_name_cleaned = tag_name.strip().lower()
                        if not tag_name_cleaned: continue
                        
                        tag_db_obj = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                        if not tag_db_obj:
                            tag_db_obj = Tag(name=tag_name_cleaned)
                            db.add(tag_db_obj)
                            try:
                                db.flush() # Get ID or catch IntegrityError
                            except IntegrityError: 
                                db.rollback() # Rollback only the flush attempt for this tag
                                tag_db_obj = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                            except Exception as e_flush:
                                db.rollback()
                                logger.error(f"MAIN API: Error flushing new tag '{tag_name_cleaned}' for article {art_db_obj_to_process.id}: {e_flush}", exc_info=True)
                                continue # Skip this tag
                        
                        if tag_db_obj: # Ensure tag_db_obj is valid
                           art_db_obj_to_process.tags.append(tag_db_obj)
                           newly_added_tags_for_response.append(ArticleTagResponse.from_orm(tag_db_obj))
                    
                    try: 
                        db.commit() # Commit all tag changes for this article
                        db.refresh(art_db_obj_to_process) # Refresh to get the final state of tags
                        # Update tags in the response object
                        for res_art in results_on_page:
                            if res_art.id == art_db_obj_to_process.id:
                                res_art.tags = [ArticleTagResponse.from_orm(t) for t in art_db_obj_to_process.tags] # Use refreshed tags
                                # Clean up tag-related error message if successful
                                if res_art.error_message and "Tags need generation." in res_art.error_message:
                                    res_art.error_message = res_art.error_message.replace("Tags need generation.", "").replace(" | ", "").strip()
                                    if not res_art.error_message: res_art.error_message = None # Set to None if empty
                                break
                    except Exception as e_commit_tags: 
                        db.rollback()
                        logger.error(f"Error committing tags for article {art_db_obj_to_process.id}: {e_commit_tags}", exc_info=True)
                        # Update error message for this article in results_on_page
                        for res_art in results_on_page:
                            if res_art.id == art_db_obj_to_process.id:
                                res_art.error_message = (res_art.error_message + " | " if res_art.error_message else "") + f"Error saving tags: {e_commit_tags}"
                                break
            
            # Final update of error message in results_on_page based on the processing outcome
            for res_art in results_on_page:
                if res_art.id == art_db_obj_to_process.id:
                    final_error_parts = []
                    if art_db_obj_to_process.scraped_content and art_db_obj_to_process.scraped_content.startswith("Error:"):
                        final_error_parts.append(art_db_obj_to_process.scraped_content)
                    
                    summary_final_check = db.query(Summary).filter(Summary.article_id == art_db_obj_to_process.id).order_by(Summary.created_at.desc()).first()
                    if summary_final_check:
                        if summary_final_check.summary_text.startswith("Error:"):
                            final_error_parts.append(summary_final_check.summary_text)
                        # Update summary in response regardless, it might have been set before error or is now None
                        res_art.summary = summary_final_check.summary_text if not summary_final_check.summary_text.startswith("Error:") else None
                    elif not (art_db_obj_to_process.scraped_content and art_db_obj_to_process.scraped_content.startswith("Error:")): # Only add pending if no scrape error
                         final_error_parts.append("Summary still pending or failed.")
                    
                    db.refresh(art_db_obj_to_process) 
                    res_art.tags = [ArticleTagResponse.from_orm(t) for t in art_db_obj_to_process.tags] 
                    if not art_db_obj_to_process.tags and not (art_db_obj_to_process.scraped_content and art_db_obj_to_process.scraped_content.startswith("Error:")):
                        final_error_parts.append("Tags still pending or failed.")
                    
                    res_art.error_message = " | ".join(final_error_parts) if final_error_parts else None


    logger.info(f"MAIN API: Preparing to send {len(results_on_page)} articles to frontend.")

    # Background preloading for the next page
    if current_page_for_slice < total_pages:
        next_page_offset = current_page_for_slice * query.page_size
        # Construct the query for preloading IDs and URLs for the next page
        preload_db_query = db.query(Article.id, Article.url) # Select only id and url
        if query.feed_source_ids: preload_db_query = preload_db_query.filter(Article.feed_source_id.in_(query.feed_source_ids))
        if query.tag_ids:
            for tag_id in query.tag_ids: preload_db_query = preload_db_query.filter(Article.tags.any(Tag.id == tag_id))
        if query.keyword:
            keyword_like = f"%{query.keyword}%"
            preload_db_query = preload_db_query.filter(or_(Article.title.ilike(keyword_like), Article.scraped_content.ilike(keyword_like)))
        
        next_page_articles_for_preload = preload_db_query.order_by(Article.published_date.desc().nullslast(), Article.id.desc())\
                                          .limit(query.page_size).offset(next_page_offset).all()

        article_data_for_preload = [{"id": art_id, "url": art_url} for art_id, art_url in next_page_articles_for_preload]

        if article_data_for_preload:
            logger.info(f"MAIN API: Scheduling preload for {len(article_data_for_preload)} articles for next page.")
            background_tasks.add_task(
                _preload_summaries_and_tags_for_articles,
                article_data_for_preload,
                query.summary_prompt, # Pass current page's prompts for preloading next
                query.tag_generation_prompt
            )

    return PaginatedSummariesAPIResponse(
        search_source=search_source_display, requested_page=current_page_for_slice,
        page_size=query.page_size, total_articles_available=total_articles_available,
        total_pages=total_pages, processed_articles_on_page=results_on_page
    )

@app.post("/api/articles/{article_id}/regenerate-summary", response_model=ArticleResult)
async def regenerate_article_summary(
    article_id: int,
    request: RegenerateSummaryRequest,
    db: SQLAlchemySession = Depends(get_db)
):
    if not llm_summary_instance:
        raise HTTPException(status_code=503, detail="Summarization LLM not available.")

    article_db = db.query(Article).options(joinedload(Article.tags), joinedload(Article.feed_source)).filter(Article.id == article_id).first()
    if not article_db:
        raise HTTPException(status_code=404, detail="Article not found.")

    logger.info(f"API: Regenerate summary request for Article ID {article_id} with prompt: {'Custom' if request.custom_prompt else 'Default'}")

    scraped_content = article_db.scraped_content
    # Re-scrape if content is missing or was an error
    if not scraped_content or scraped_content.startswith("Error:") or scraped_content.startswith("Content Error:"):
        logger.info(f"API: Content for Article ID {article_id} is missing or an error. Re-scraping...")
        scraped_docs = await scraper.scrape_urls(
            [article_db.url],
            path_to_extension_folder=app_config.PATH_TO_EXTENSION,
            use_headless_browser=app_config.USE_HEADLESS_BROWSER
        )
        if scraped_docs and scraped_docs[0] and not scraped_docs[0].metadata.get("error") and scraped_docs[0].page_content:
            scraped_content = scraped_docs[0].page_content
            article_db.scraped_content = scraped_content
            db.add(article_db) # Add to session
            db.commit() # Commit the new scraped content
            db.refresh(article_db) # Refresh to get the latest state
        else:
            error_msg = scraped_docs[0].metadata.get("error", "Failed to re-scrape content") if scraped_docs and scraped_docs[0] else "Failed to re-scrape content"
            article_db.scraped_content = f"Scraping Error: {error_msg}" # Update content with error
            db.add(article_db)
            db.commit()
            logger.error(f"API: Failed to re-scrape content for Article ID {article_id}: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Failed to get content for summarization: {error_msg}")

    # After potential re-scrape, check content again
    if not scraped_content or scraped_content.startswith("Error:") or scraped_content.startswith("Content Error:"):
        logger.error(f"API: Article content for ID {article_id} is still invalid after attempting re-scrape.")
        raise HTTPException(status_code=500, detail="Article content is still invalid after attempting re-scrape.")

    # Proceed with summarization
    lc_doc = Document(page_content=scraped_content, metadata={"source": article_db.url, "id": article_db.id})
    prompt_to_use = request.custom_prompt if request.custom_prompt and request.custom_prompt.strip() else app_config.DEFAULT_SUMMARY_PROMPT
    new_summary_text = await summarizer.summarize_document_content(lc_doc, llm_summary_instance, prompt_to_use)

    # Delete old summaries before adding the new one
    deleted_summaries_count = db.query(Summary).filter(Summary.article_id == article_id).delete(synchronize_session=False)
    if deleted_summaries_count > 0:
        logger.info(f"API: Deleted {deleted_summaries_count} old summary/summaries for Article ID {article_id} before regeneration.")
    
    new_summary_db_obj = Summary(
        article_id=article_id,
        summary_text=new_summary_text,
        prompt_used=prompt_to_use,
        model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME
    )
    db.add(new_summary_db_obj)
    try:
        db.commit()
        db.refresh(new_summary_db_obj)
        logger.info(f"API: Regenerated and saved new summary ID {new_summary_db_obj.id} for Article ID {article_id}")
    except Exception as e:
        db.rollback()
        logger.error(f"API: Error saving regenerated summary for Article ID {article_id}: {e}", exc_info=True)
        new_summary_text = f"Error saving summary: {e}" # Update text to reflect error

    # Regenerate tags if requested and LLM is available
    if request.regenerate_tags and llm_tag_instance and scraped_content and not scraped_content.startswith("Error:"):
        logger.info(f"API: Regenerating tags for Article ID {article_id} as part of summary regeneration.")
        
        # Clear existing tags for the article
        if article_db.tags:
            article_db.tags.clear()
            try:
                db.commit() # Commit the clear operation
                db.refresh(article_db) # Ensure the object reflects the cleared state
                logger.info(f"API: Cleared existing tags for Article ID {article_id}.")
            except Exception as e_clear_tags:
                db.rollback()
                logger.error(f"API: Error clearing tags for Article ID {article_id}: {e_clear_tags}", exc_info=True)
                # Decide if to proceed with tag generation or not. For now, we'll try.

        tag_names_generated = await summarizer.generate_tags_for_text(
            scraped_content, llm_tag_instance, None # Use default tag prompt
        )
        if tag_names_generated:
            for tag_name in tag_names_generated:
                tag_name_cleaned = tag_name.strip().lower()
                if not tag_name_cleaned: continue
                
                tag_db_obj = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                if not tag_db_obj:
                    tag_db_obj = Tag(name=tag_name_cleaned)
                    db.add(tag_db_obj)
                    try:
                        db.flush() # To get ID or catch IntegrityError
                    except IntegrityError: 
                        db.rollback() # Rollback flush
                        tag_db_obj = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                    except Exception as e_flush_tag:
                        db.rollback()
                        logger.error(f"API: Error flushing new tag '{tag_name_cleaned}' for article {article_id}: {e_flush_tag}", exc_info=True)
                        continue # Skip this tag
                
                if tag_db_obj and tag_db_obj not in article_db.tags: # Check if not already added in this session
                    article_db.tags.append(tag_db_obj)
            try:
                db.commit() # Commit all tag changes for this article
                db.refresh(article_db) # Refresh to get the latest tags
                logger.info(f"API: Regenerated and saved tags for Article ID {article_id}: {tag_names_generated}")
            except Exception as e_commit_tags:
                db.rollback()
                logger.error(f"API: Error saving regenerated tags for Article ID {article_id}: {e_commit_tags}", exc_info=True)
    
    db.refresh(article_db) # Final refresh of the article object

    return ArticleResult(
        id=article_db.id,
        title=article_db.title,
        url=article_db.url,
        summary=new_summary_text, # This will contain error if saving failed
        publisher=article_db.feed_source.name if article_db.feed_source else article_db.publisher_name,
        published_date=article_db.published_date,
        source_feed_url=article_db.feed_source.url if article_db.feed_source else None,
        tags=[ArticleTagResponse.from_orm(tag) for tag in article_db.tags], # Use the latest tags
        error_message=None if not new_summary_text.startswith("Error:") else new_summary_text
    )

@app.delete("/api/admin/cleanup-old-data", status_code=200)
async def cleanup_old_data_endpoint(days_old: int = Query(30, ge=1), db: SQLAlchemySession = Depends(get_db)):
    if days_old <= 0:
        raise HTTPException(status_code=400, detail="days_old parameter must be positive.")

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
    logger.info(f"API: Admin request to delete data older than {days_old} days (before {cutoff_date}).")

    # Find articles to delete
    articles_to_delete_query = db.query(Article).filter(Article.published_date < cutoff_date)
    
    # Get IDs for logging and targeted deletion (though cascade should handle related)
    article_ids_to_delete = [article.id for article in articles_to_delete_query.all()]
    article_deleted_count = len(article_ids_to_delete)

    if article_deleted_count > 0:
        # Deleting articles will cascade to summaries, chat_history, and article_tag_association
        # due to `cascade="all, delete-orphan"` on relationships in Article model.
        # Tags themselves are not deleted unless they become orphaned and you have specific logic for that.
        db.query(Article).filter(Article.id.in_(article_ids_to_delete)).delete(synchronize_session=False)
        logger.info(f"API: Deleted {article_deleted_count} old article records (and their related summaries/chat history/tags via ORM relationships or explicit delete).")
    else:
        logger.info("API: No old articles found to delete based on published_date.")

    db.commit()
    return {"message": f"Cleanup process completed. Deleted {article_deleted_count} articles (and related data) older than {days_old} days."}

@app.get("/api/article/{article_id}/chat-history", response_model=List[ChatHistoryItem])
async def get_article_chat_history(article_id: int, db: SQLAlchemySession = Depends(get_db)):
    db_history_items = db.query(ChatHistory).filter(ChatHistory.article_id == article_id).order_by(ChatHistory.timestamp.asc()).all()
    
    formatted_history = []
    for item in db_history_items:
        formatted_history.append(ChatHistoryItem(role="user", content=item.question))
        if item.answer: # Only add AI part if an answer exists
            formatted_history.append(ChatHistoryItem(role="ai", content=item.answer))
    return formatted_history


@app.post("/api/chat-with-article", response_model=ChatResponse)
async def chat_with_article_endpoint(query: ChatQuery, db: SQLAlchemySession = Depends(get_db)):
    if not llm_chat_instance:
        raise HTTPException(status_code=503, detail="Chat service (LLM) not initialized.")

    article_db = db.query(Article).filter(Article.id == query.article_id).first()
    if not article_db:
        raise HTTPException(status_code=404, detail="Article not found in database.")

    logger.info(f"CHAT API: Request for Article ID: {article_db.id}, Question: '{query.question[:50]}...'")
    if query.chat_history:
        logger.info(f"CHAT API: Received chat history with {len(query.chat_history)} turns.")

    article_text_for_chat = article_db.scraped_content or ""
    error_detail_for_chat = None # To store any errors encountered during content retrieval

    # If content is missing or an error, try to re-scrape
    if not article_text_for_chat or article_text_for_chat.startswith("Error:") or article_text_for_chat.startswith("Content Error:"):
        logger.info(f"CHAT API: Article {article_db.id} has no/error content ('{article_text_for_chat[:50]}...'). Attempting re-scrape.")
        scraped_docs = await scraper.scrape_urls(
            [str(article_db.url)], # Ensure URL is a string
            path_to_extension_folder=app_config.PATH_TO_EXTENSION,
            use_headless_browser=app_config.USE_HEADLESS_BROWSER
        )
        if scraped_docs and scraped_docs[0]:
            doc_item = scraped_docs[0]
            if not doc_item.metadata.get("error") and doc_item.page_content and doc_item.page_content.strip():
                article_text_for_chat = doc_item.page_content
                article_db.scraped_content = article_text_for_chat # Update DB object
                db.add(article_db)
                db.commit() # Commit the re-scraped content
                logger.info(f"CHAT API: Successfully re-scraped article {article_db.id} for chat. Length: {len(article_text_for_chat)}")
            else:
                error_detail_for_chat = doc_item.metadata.get("error", "Re-scraped content empty/error.")
                article_text_for_chat = "" # Ensure it's empty if re-scrape failed
        else:
            error_detail_for_chat = "Failed to re-scrape article for chat."
            article_text_for_chat = ""
        
        if error_detail_for_chat:
             logger.warning(f"CHAT API Error on re-scrape for Article {article_db.id}: {error_detail_for_chat}")


    # Get response from LLM
    answer = await summarizer.get_chat_response(
        llm_instance=llm_chat_instance,
        article_text=article_text_for_chat, # This will be empty if scraping failed
        question=query.question,
        chat_history=query.chat_history, # Pass the history from the request
        custom_chat_prompt_str=query.chat_prompt # Pass custom prompt from request
    )

    # Consolidate error messages
    final_error_message_for_response = error_detail_for_chat
    if answer.startswith("Error getting answer from AI:") or answer == "AI returned an empty answer.":
        # If LLM itself returned an error, it might be more relevant than a scraping error
        final_error_message_for_response = answer 
    
    # Save chat turn to DB if successful and not an error from LLM
    if not (answer.startswith("Error:") or answer == "AI returned an empty answer."):
        try:
            new_chat_item_db = ChatHistory(
                article_id=article_db.id,
                question=query.question,
                answer=answer,
                prompt_used=query.chat_prompt or app_config.DEFAULT_CHAT_PROMPT, # Store prompt used
                model_used=app_config.DEFAULT_CHAT_MODEL_NAME # Store model used
            )
            db.add(new_chat_item_db)
            db.commit()
            db.refresh(new_chat_item_db)
            logger.info(f"CHAT API: Saved new chat turn (Q&A) ID {new_chat_item_db.id} for article {article_db.id}")
        except Exception as e:
            db.rollback()
            logger.error(f"CHAT API: Error saving new chat turn to DB for article {article_db.id}: {e}", exc_info=True)
            # Append saving error to existing errors if any
            final_error_message_for_response = (final_error_message_for_response + " | " if final_error_message_for_response else "") + "Failed to save chat turn to database."

    logger.info(f"CHAT API: Sending response for article {article_db.id}. Answer starts: '{answer[:60]}...'. Error: {final_error_message_for_response}")
    return ChatResponse(
        article_id=article_db.id,
        question=query.question,
        answer=answer, # Send the raw answer from LLM, even if it's an error message from it
        error_message=final_error_message_for_response # This will contain scraping or saving errors
    )

# --- Feed Management Endpoints ---
@app.post("/api/feeds", response_model=FeedSourceResponse, status_code=201)
async def add_new_feed_source(feed_request: AddFeedRequest, db: SQLAlchemySession = Depends(get_db)):
    # Check if feed URL already exists
    existing_feed = db.query(RSSFeedSource).filter(RSSFeedSource.url == str(feed_request.url)).first()
    if existing_feed:
        raise HTTPException(status_code=409, detail="Feed URL already exists in the database.")

    new_feed = RSSFeedSource(
        url=str(feed_request.url), # Convert HttpUrl to string for DB
        name=feed_request.name or str(feed_request.url).split('/')[2].replace("www.","") if len(str(feed_request.url).split('/')) > 2 else str(feed_request.url), # Guess name if not provided
        fetch_interval_minutes=feed_request.fetch_interval_minutes or app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES
    )
    db.add(new_feed)
    try:
        db.commit()
        db.refresh(new_feed)
        logger.info(f"API: Added new feed source: {new_feed.url}")
        return new_feed
    except IntegrityError: # Should be caught by the check above, but as a safeguard
        db.rollback()
        raise HTTPException(status_code=409, detail="Feed URL already exists (IntegrityError).")
    except Exception as e:
        db.rollback()
        logger.error(f"API: Error adding feed {feed_request.url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not add feed: {e}")


@app.get("/api/feeds", response_model=List[FeedSourceResponse])
async def get_all_feed_sources(db: SQLAlchemySession = Depends(get_db)):
    feeds = db.query(RSSFeedSource).order_by(RSSFeedSource.name).all()
    return feeds

@app.put("/api/feeds/{feed_id}", response_model=FeedSourceResponse)
async def update_feed_source_settings(feed_id: int, feed_update: UpdateFeedRequest, db: SQLAlchemySession = Depends(get_db)):
    feed_db = db.query(RSSFeedSource).filter(RSSFeedSource.id == feed_id).first()
    if not feed_db:
        raise HTTPException(status_code=404, detail="Feed source not found.")

    updated = False
    if feed_update.name is not None: # Allow setting name to empty string if desired
        feed_db.name = feed_update.name
        updated = True
    if feed_update.fetch_interval_minutes is not None:
        if feed_update.fetch_interval_minutes > 0:
            feed_db.fetch_interval_minutes = feed_update.fetch_interval_minutes
            updated = True
        else:
            raise HTTPException(status_code=400, detail="Fetch interval must be positive.")

    if updated:
        db.add(feed_db)
        db.commit()
        db.refresh(feed_db)
        logger.info(f"API: Updated feed source ID {feed_id}. New interval: {feed_db.fetch_interval_minutes}, New name: '{feed_db.name}'")
    return feed_db

@app.delete("/api/feeds/{feed_id}", status_code=204) # 204 No Content on successful deletion
async def delete_feed_source(feed_id: int, db: SQLAlchemySession = Depends(get_db)):
    feed_db = db.query(RSSFeedSource).filter(RSSFeedSource.id == feed_id).first()
    if not feed_db:
        raise HTTPException(status_code=404, detail="Feed source not found.")

    # Deletion will cascade to articles, summaries, chat history, and associations due to ORM setup
    db.delete(feed_db)
    db.commit()
    logger.info(f"API: Deleted feed source ID {feed_id} and its related data (articles, summaries, chat, tags via cascade).")
    return None # Return None for 204 response

@app.post("/api/trigger-rss-refresh", status_code=202) # 202 Accepted
async def manual_trigger_rss_refresh(background_tasks: BackgroundTasks):
    logger.info("API: Manual RSS refresh triggered via endpoint.")
    # Add the task to background tasks to run after response is sent
    background_tasks.add_task(trigger_rss_update_all_feeds)
    return {"message": "RSS feed refresh process has been initiated in the background."}


# --- Static Files & Index ---
# Ensure the 'static_frontend' directory exists at the root of your project or adjust path
app.mount("/static", StaticFiles(directory="static_frontend"), name="static_frontend_files")

@app.get("/")
async def serve_index():
    return FileResponse('static_frontend/index.html')
