# app/main_api.py
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, Field
from typing import List, Optional, Dict, Any
import math
from datetime import datetime, timezone, timedelta
import asyncio

from sqlalchemy.orm import Session as SQLAlchemySession, joinedload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_, and_, func as sql_func # Added for query building
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import rss_client, scraper, summarizer, config as app_config, database
from .database import Article, Summary, ChatHistory, RSSFeedSource, Tag, get_db, db_session_scope, create_db_and_tables, article_tag_association

app = FastAPI(title="News Summarizer API & Frontend (DB & Scheduler & Tags & Search)", version="1.7.0") # Version increment

# --- Global Variables & Scheduler ---
llm_summary_instance: Optional[summarizer.GoogleGenerativeAI] = None
llm_chat_instance: Optional[summarizer.GoogleGenerativeAI] = None
llm_tag_instance: Optional[summarizer.GoogleGenerativeAI] = None
scheduler = AsyncIOScheduler(timezone="UTC")
rss_update_lock = asyncio.Lock()

@app.on_event("startup")
async def startup_event():
    global llm_summary_instance, llm_chat_instance, llm_tag_instance, scheduler
    print("MAIN_API: Application startup initiated...")

    print("MAIN_API: Initializing database...")
    database.create_db_and_tables()

    with db_session_scope() as db:
        if app_config.RSS_FEED_URLS:
            print(f"MAIN_API: Ensuring initial RSS feeds are in DB: {app_config.RSS_FEED_URLS}")
            rss_client.add_initial_feeds_to_db(db, app_config.RSS_FEED_URLS)
        else:
            print("MAIN_API: No initial RSS_FEED_URLS configured in app_config to add to DB.")

    print("MAIN_API: Attempting to initialize LLM instances...")
    try:
        if not app_config.GEMINI_API_KEY:
            print("MAIN_API: CRITICAL ERROR: GEMINI_API_KEY not found. LLM features will be disabled.")
        else:
            llm_summary_instance = summarizer.initialize_llm(
                api_key=app_config.GEMINI_API_KEY,
                model_name=app_config.DEFAULT_SUMMARY_MODEL_NAME,
                temperature=0.2, max_output_tokens=400
            )
            if llm_summary_instance: print(f"MAIN_API: Summarization LLM ({app_config.DEFAULT_SUMMARY_MODEL_NAME}) initialized.")
            else: print("MAIN_API: CRITICAL ERROR: Summarization LLM failed to initialize.")

            llm_chat_instance = summarizer.initialize_llm(
                api_key=app_config.GEMINI_API_KEY,
                model_name=app_config.DEFAULT_CHAT_MODEL_NAME,
                temperature=0.5, max_output_tokens=1536
            )
            if llm_chat_instance: print(f"MAIN_API: Chat LLM ({app_config.DEFAULT_CHAT_MODEL_NAME}) initialized.")
            else: print("MAIN_API: CRITICAL ERROR: Chat LLM failed to initialize.")

            llm_tag_instance = summarizer.initialize_llm(
                api_key=app_config.GEMINI_API_KEY,
                model_name=app_config.DEFAULT_TAG_MODEL_NAME,
                temperature=0.1,
                max_output_tokens=100
            )
            if llm_tag_instance: print(f"MAIN_API: Tag Generation LLM ({app_config.DEFAULT_TAG_MODEL_NAME}) initialized.")
            else: print("MAIN_API: CRITICAL ERROR: Tag Generation LLM failed to initialize.")

    except Exception as e:
        print(f"MAIN_API: CRITICAL ERROR during LLM Init: {e}.")
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
            next_run_time=datetime.now(timezone.utc),
            max_instances=1,
            coalesce=True
        )
        scheduler.start()
        print(f"MAIN_API: APScheduler started. RSS feeds will be checked every {app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES} minutes.")
    else:
        print("MAIN_API: APScheduler already running.")

    print("MAIN_API: Application startup complete.")

@app.on_event("shutdown")
def shutdown_event():
    global scheduler
    if scheduler.running:
        print("MAIN_API: Shutting down APScheduler...")
        scheduler.shutdown()
    print("MAIN_API: Application shutdown complete.")


async def trigger_rss_update_all_feeds():
    if rss_update_lock.locked():
        print("SCHEDULER_JOB/BG_TASK: RSS update already in progress. Skipping this run.")
        return

    async with rss_update_lock:
        print("SCHEDULER_JOB/BG_TASK: Acquired lock. Triggering update_all_subscribed_feeds...")
        try:
            with db_session_scope() as db:
                await rss_client.update_all_subscribed_feeds(db)
            print("SCHEDULER_JOB/BG_TASK: update_all_subscribed_feeds task finished successfully.")
        except Exception as e:
            print(f"SCHEDULER_JOB/BG_TASK: Exception during update_all_subscribed_feeds: {e}")
            import traceback
            traceback.print_exc()
    print("SCHEDULER_JOB/BG_TASK: Lock released.")


# --- Pydantic Models ---
class InitialConfigResponse(BaseModel):
    default_rss_feeds: List[str]
    all_db_feed_sources: List[Dict[str, Any]]
    default_articles_per_page: int
    default_summary_prompt: str
    default_chat_prompt: str
    default_tag_generation_prompt: str
    default_rss_fetch_interval_minutes: int

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
    tag_ids: Optional[List[int]] = None # For filtering by specific tag IDs
    keyword: Optional[str] = None      # For keyword search
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
    id: int
    question: str
    answer: Optional[str] = None
    timestamp: datetime
    class Config:
        from_attributes = True

class ChatQuery(BaseModel):
    article_id: int
    question: str
    chat_prompt: Optional[str] = None

class ChatResponse(BaseModel):
    article_id: int
    question: str
    answer: str
    new_chat_history_item: Optional[ChatHistoryItem] = None
    error_message: str | None = None

class AddFeedRequest(BaseModel):
    url: HttpUrl
    name: Optional[str] = None
    fetch_interval_minutes: Optional[int] = Field(default_factory=lambda: app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES)

class UpdateFeedRequest(BaseModel):
    name: Optional[str] = None
    fetch_interval_minutes: Optional[int] = None

class RegenerateSummaryRequest(BaseModel):
    custom_prompt: Optional[str] = None


# --- Helper for Preloading (Includes Tagging) ---
async def _preload_summaries_and_tags_for_articles(
    article_data_to_preload: List[Dict[str, Any]],
    custom_summary_prompt: Optional[str] = None,
    custom_tag_prompt: Optional[str] = None
):
    if not article_data_to_preload or (not llm_summary_instance and not llm_tag_instance):
        if not llm_summary_instance: print("BACKGROUND PRELOAD: Summarization LLM not available.")
        if not llm_tag_instance: print("BACKGROUND PRELOAD: Tag Generation LLM not available.")
        if not article_data_to_preload: print("BACKGROUND PRELOAD: No articles provided for preloading.")
        return

    print(f"BACKGROUND PRELOAD: Starting for {len(article_data_to_preload)} articles (Summaries & Tags).")
    processed_count = 0
    successfully_summarized_count = 0
    successfully_tagged_count = 0

    with db_session_scope() as db:
        for i, article_data in enumerate(article_data_to_preload):
            article_id = article_data.get("id")
            article_url = article_data.get("url")

            print(f"BACKGROUND PRELOAD: Processing item {i+1}/{len(article_data_to_preload)}: Article ID {article_id}, URL {article_url[:60]}...")

            if not article_id or not article_url:
                print(f"BACKGROUND PRELOAD: Skipping item {i+1} due to missing ID or URL: {article_data}")
                continue

            try:
                article_db_obj = db.query(Article).options(joinedload(Article.tags)).filter(Article.id == article_id).first() # Eager load tags
                if not article_db_obj:
                    print(f"BACKGROUND PRELOAD: Article ID {article_id} not found in DB. Skipping.")
                    continue

                # --- Scraping (if needed) ---
                scraped_content = article_db_obj.scraped_content
                needs_scraping = not scraped_content or scraped_content.startswith("Error:") or scraped_content.startswith("Content Error:")
                
                if needs_scraping:
                    print(f"BACKGROUND PRELOAD: Scraping for Article ID {article_id} ({article_url[:50]}...)")
                    scraped_docs = await scraper.scrape_urls([article_url], [])
                    current_scraped_content_error = None
                    if scraped_docs and scraped_docs[0]:
                        sc_doc = scraped_docs[0]
                        if not sc_doc.metadata.get("error") and sc_doc.page_content and sc_doc.page_content.strip():
                            scraped_content = sc_doc.page_content
                            article_db_obj.scraped_content = scraped_content
                            print(f"BACKGROUND PRELOAD: Successfully scraped Article ID {article_id}. Length: {len(scraped_content)}")
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
                        print(f"BACKGROUND PRELOAD: Error committing scraped content for Article ID {article_id}: {e_commit_scrape}")
                        continue 
                    
                    if current_scraped_content_error:
                        print(f"BACKGROUND PRELOAD: Scraping failed for Article ID {article_id}. Error: {current_scraped_content_error}. Skipping summarization & tagging.")
                        continue

                # --- Summarization (if needed and LLM available) ---
                if llm_summary_instance and scraped_content and not scraped_content.startswith("Error:"):
                    existing_summary = db.query(Summary).filter(Summary.article_id == article_id).order_by(Summary.created_at.desc()).first()
                    needs_summary = not existing_summary or not existing_summary.summary_text or \
                                    existing_summary.summary_text.startswith("Error:") or \
                                    existing_summary.summary_text.lower().startswith("content empty") or \
                                    existing_summary.summary_text.lower().startswith("content too short")
                    
                    if needs_summary:
                        print(f"BACKGROUND PRELOAD: Summarizing Article ID {article_id} ({article_url[:50]}...)")
                        lc_doc = scraper.Document(page_content=scraped_content, metadata={"source": article_url, "id": article_id})
                        summary_text = await summarizer.summarize_document_content(lc_doc, llm_summary_instance, custom_summary_prompt)
                        
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
                            print(f"BACKGROUND PRELOAD: Saved summary for Article ID {article_id}. Length: {len(summary_text)}")
                            successfully_summarized_count +=1
                        except Exception as e_commit_sum:
                            db.rollback()
                            print(f"BACKGROUND PRELOAD: Error committing summary for Article ID {article_id}: {e_commit_sum}")
                    # else:
                        # print(f"BACKGROUND PRELOAD: Article ID {article_id} already has a valid summary. Skipping summarization.")

                # --- Tag Generation (if needed and LLM available) ---
                db.refresh(article_db_obj) # Refresh to ensure tags are current before checking
                if llm_tag_instance and scraped_content and not scraped_content.startswith("Error:"):
                    if not article_db_obj.tags: 
                        print(f"BACKGROUND PRELOAD: Generating tags for Article ID {article_id} ({article_url[:50]}...)")
                        tag_names = await summarizer.generate_tags_for_text(scraped_content, llm_tag_instance, custom_tag_prompt)
                        
                        if tag_names:
                            # article_db_obj.tags.clear() # Not strictly needed due to 'if not article_db_obj.tags'
                            for tag_name in tag_names:
                                tag_name_cleaned = tag_name.strip().lower() 
                                if not tag_name_cleaned: continue

                                tag_db = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                                if not tag_db:
                                    tag_db = Tag(name=tag_name_cleaned)
                                    db.add(tag_db)
                                    try:
                                        db.flush() 
                                    except IntegrityError: 
                                        db.rollback()
                                        tag_db = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                                    except Exception as e_flush_tag:
                                        db.rollback()
                                        print(f"BACKGROUND PRELOAD: Error flushing new tag '{tag_name_cleaned}' for Article ID {article_id}: {e_flush_tag}")
                                        continue 

                                if tag_db and tag_db not in article_db_obj.tags:
                                    article_db_obj.tags.append(tag_db)
                            
                            try:
                                db.commit() 
                                print(f"BACKGROUND PRELOAD: Saved tags for Article ID {article_id}: {tag_names}")
                                successfully_tagged_count += 1
                            except Exception as e_commit_tags:
                                db.rollback()
                                print(f"BACKGROUND PRELOAD: Error committing tags for Article ID {article_id}: {e_commit_tags}")
                        # else:
                            # print(f"BACKGROUND PRELOAD: No tags generated for Article ID {article_id}.")
                    # else:
                        # print(f"BACKGROUND PRELOAD: Article ID {article_id} already has tags. Skipping tag generation.")
                
                elif not scraped_content or scraped_content.startswith("Error:"):
                     print(f"BACKGROUND PRELOAD: Skipping summary & tags for Article ID {article_id} due to missing/error content ('{str(scraped_content)[:50]}...').")


            except Exception as e_article_preload:
                print(f"BACKGROUND PRELOAD: UNHANDLED EXCEPTION while processing Article ID {article_id} (URL: {article_url}): {e_article_preload}")
                db.rollback() 
            finally:
                processed_count += 1

    print(f"BACKGROUND PRELOAD: Finished processing batch. Attempted: {processed_count}/{len(article_data_to_preload)}. Summarized: {successfully_summarized_count}. Tagged: {successfully_tagged_count}.")


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
        default_rss_fetch_interval_minutes=app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES
    )

@app.post("/api/get-news-summaries", response_model=PaginatedSummariesAPIResponse)
async def get_news_summaries_endpoint(query: NewsPageQuery, background_tasks: BackgroundTasks, db: SQLAlchemySession = Depends(get_db)):
    if not llm_summary_instance and not llm_tag_instance:
        raise HTTPException(status_code=503, detail="Core AI services (Summarization/Tagging LLM) unavailable.")

    db_query = db.query(Article)
    search_source_display_parts = []

    if query.feed_source_ids:
        db_query = db_query.filter(Article.feed_source_id.in_(query.feed_source_ids))
        source_names = db.query(RSSFeedSource.name).filter(RSSFeedSource.id.in_(query.feed_source_ids)).all()
        search_source_display_parts.append(f"Feeds: {', '.join([name[0] for name in source_names if name[0]]) or 'Selected Feeds'}")

    if query.tag_ids:
        # Filter for articles that have ALL specified tags
        for tag_id in query.tag_ids:
            db_query = db_query.filter(Article.tags.any(Tag.id == tag_id))
        
        # To get names for display (optional, can be slow if many tags)
        tag_names = db.query(Tag.name).filter(Tag.id.in_(query.tag_ids)).all()
        search_source_display_parts.append(f"Tags: {', '.join([name[0] for name in tag_names if name[0]]) or 'Selected Tags'}")


    if query.keyword:
        keyword_like = f"%{query.keyword}%"
        db_query = db_query.filter(
            or_(
                Article.title.ilike(keyword_like),
                Article.scraped_content.ilike(keyword_like),
                # Optionally search in summaries too, but might require another join or subquery if summaries are frequently updated
                # Article.summaries.any(Summary.summary_text.ilike(keyword_like)) # More complex
            )
        )
        search_source_display_parts.append(f"Keyword: '{query.keyword}'")

    search_source_display = " & ".join(search_source_display_parts) if search_source_display_parts else "All Articles"
    
    # Eager load tags to prevent N+1 queries when accessing article_db_obj.tags later
    db_query = db_query.options(joinedload(Article.tags))
    db_query = db_query.order_by(Article.published_date.desc().nullslast(), Article.id.desc())

    total_articles_available = db_query.count() # Count after all filters
    total_pages = math.ceil(total_articles_available / query.page_size) if query.page_size > 0 else 0

    current_page_for_slice = query.page
    if current_page_for_slice < 1: current_page_for_slice = 1
    if current_page_for_slice > total_pages and total_pages > 0 : current_page_for_slice = total_pages

    offset = (current_page_for_slice - 1) * query.page_size
    articles_from_db = db_query.limit(query.page_size).offset(offset).all()

    results_on_page = []
    articles_needing_processing_db_objects = []

    for article_db_obj in articles_from_db:
        article_result_data = {
            "id": article_db_obj.id,
            "title": article_db_obj.title,
            "url": article_db_obj.url,
            "publisher": article_db_obj.feed_source.name if article_db_obj.feed_source else article_db_obj.publisher_name,
            "published_date": article_db_obj.published_date,
            "source_feed_url": article_db_obj.feed_source.url if article_db_obj.feed_source else None,
            "summary": None,
            "tags": [ArticleTagResponse.from_orm(tag) for tag in article_db_obj.tags],
            "error_message": None
        }

        latest_summary_obj = db.query(Summary).filter(Summary.article_id == article_db_obj.id).order_by(Summary.created_at.desc()).first()

        needs_processing = False
        current_error_parts = []

        if not article_db_obj.scraped_content or article_db_obj.scraped_content.startswith("Error:"):
            needs_processing = True
            current_error_parts.append("Content needs scraping.")
        
        if not latest_summary_obj or latest_summary_obj.summary_text.startswith("Error:"):
            needs_processing = True
            current_error_parts.append(latest_summary_obj.summary_text if latest_summary_obj and latest_summary_obj.summary_text.startswith("Error:") else "Summary needs generation.")
        elif latest_summary_obj:
            article_result_data["summary"] = latest_summary_obj.summary_text
        
        if not article_db_obj.tags: # Check if tags list is empty
            needs_processing = True
            current_error_parts.append("Tags need generation.")
        
        if current_error_parts:
            article_result_data["error_message"] = " | ".join(current_error_parts)

        if needs_processing:
            articles_needing_processing_db_objects.append(article_db_obj)

        results_on_page.append(ArticleResult(**article_result_data))

    if articles_needing_processing_db_objects:
        print(f"MAIN API: Found {len(articles_needing_processing_db_objects)} articles needing scraping/summary/tags for current page.")

        for art_db_obj_to_process in articles_needing_processing_db_objects:
            db.refresh(art_db_obj_to_process) # Ensure fresh state, especially for .tags
            db.refresh(art_db_obj_to_process.feed_source) if art_db_obj_to_process.feed_source else None


            scraped_content_for_ai = art_db_obj_to_process.scraped_content
            
            if not scraped_content_for_ai or scraped_content_for_ai.startswith("Error:"):
                print(f"MAIN API: Scraping {art_db_obj_to_process.url[:70]}...")
                scraped_docs = await scraper.scrape_urls([art_db_obj_to_process.url], [])
                if scraped_docs and scraped_docs[0] and not scraped_docs[0].metadata.get("error") and scraped_docs[0].page_content:
                    scraped_content_for_ai = scraped_docs[0].page_content
                    art_db_obj_to_process.scraped_content = scraped_content_for_ai
                else:
                    error_val = scraped_docs[0].metadata.get("error", "Unknown scraping error") if scraped_docs and scraped_docs[0] else "Scraping failed"
                    art_db_obj_to_process.scraped_content = f"Scraping Error: {error_val}"
                    scraped_content_for_ai = art_db_obj_to_process.scraped_content 
                db.add(art_db_obj_to_process)
                try: db.commit() 
                except Exception as e_commit: db.rollback(); print(f"Error committing scrape: {e_commit}")
                db.refresh(art_db_obj_to_process)


            if llm_summary_instance and scraped_content_for_ai and not scraped_content_for_ai.startswith("Error:"):
                latest_summary_obj = db.query(Summary).filter(Summary.article_id == art_db_obj_to_process.id).order_by(Summary.created_at.desc()).first()
                if not latest_summary_obj or latest_summary_obj.summary_text.startswith("Error:"):
                    print(f"MAIN API: Summarizing {art_db_obj_to_process.url[:70]}...")
                    lc_doc_to_summarize = scraper.Document(page_content=scraped_content_for_ai, metadata={"source": art_db_obj_to_process.url, "id": art_db_obj_to_process.id})
                    summary_text = await summarizer.summarize_document_content(
                        lc_doc_to_summarize, llm_summary_instance, query.summary_prompt
                    )
                    db.query(Summary).filter(Summary.article_id == art_db_obj_to_process.id).delete(synchronize_session=False)
                    new_summary_db = Summary(
                        article_id=art_db_obj_to_process.id,
                        summary_text=summary_text,
                        prompt_used=query.summary_prompt or app_config.DEFAULT_SUMMARY_PROMPT,
                        model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME
                    )
                    db.add(new_summary_db)
                    try: db.commit()
                    except Exception as e_commit: db.rollback(); print(f"Error committing summary: {e_commit}")
                    
                    for res_art in results_on_page:
                        if res_art.id == art_db_obj_to_process.id:
                            res_art.summary = summary_text if not summary_text.startswith("Error:") else None
                            res_art.error_message = summary_text if summary_text.startswith("Error:") else None # Overwrite or clear error
                            break
            
            db.refresh(art_db_obj_to_process) # Refresh to get latest tags status
            if llm_tag_instance and scraped_content_for_ai and not scraped_content_for_ai.startswith("Error:") and not art_db_obj_to_process.tags:
                print(f"MAIN API: Generating tags for {art_db_obj_to_process.url[:70]}...")
                tag_names_generated = await summarizer.generate_tags_for_text(
                    scraped_content_for_ai, llm_tag_instance, query.tag_generation_prompt
                )
                if tag_names_generated:
                    current_tags_for_article_response = []
                    # art_db_obj_to_process.tags.clear() # Already checked if not art_db_obj_to_process.tags
                    for tag_name in tag_names_generated:
                        tag_name_cleaned = tag_name.strip().lower()
                        if not tag_name_cleaned: continue
                        
                        tag_db_obj = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                        if not tag_db_obj:
                            tag_db_obj = Tag(name=tag_name_cleaned)
                            db.add(tag_db_obj)
                            try:
                                db.flush() 
                            except IntegrityError: 
                                db.rollback()
                                tag_db_obj = db.query(Tag).filter(Tag.name == tag_name_cleaned).first()
                            except Exception as e_flush:
                                db.rollback()
                                print(f"MAIN API: Error flushing tag '{tag_name_cleaned}' for article {art_db_obj_to_process.id}: {e_flush}")
                                continue 
                        
                        if tag_db_obj and tag_db_obj not in art_db_obj_to_process.tags: 
                           art_db_obj_to_process.tags.append(tag_db_obj)
                        if tag_db_obj: # Ensure tag_db_obj is valid before creating response
                           current_tags_for_article_response.append(ArticleTagResponse.from_orm(tag_db_obj))
                    
                    try: 
                        db.commit()
                        for res_art in results_on_page:
                            if res_art.id == art_db_obj_to_process.id:
                                res_art.tags = current_tags_for_article_response
                                # Clear tag-related error if present
                                if res_art.error_message and "Tags need generation." in res_art.error_message:
                                    res_art.error_message = res_art.error_message.replace("Tags need generation.", "").replace(" | ", "").strip()
                                    if not res_art.error_message: res_art.error_message = None
                                break
                    except Exception as e_commit: db.rollback(); print(f"Error committing tags: {e_commit}")
            
            # Final error message update for the result after all processing attempts
            for res_art in results_on_page:
                if res_art.id == art_db_obj_to_process.id:
                    final_error_parts = []
                    if art_db_obj_to_process.scraped_content and art_db_obj_to_process.scraped_content.startswith("Error:"):
                        final_error_parts.append(art_db_obj_to_process.scraped_content)
                    
                    summary_check = db.query(Summary).filter(Summary.article_id == art_db_obj_to_process.id).order_by(Summary.created_at.desc()).first()
                    if not res_art.summary and summary_check and summary_check.summary_text.startswith("Error:"):
                         final_error_parts.append(summary_check.summary_text)
                    elif not res_art.summary and not (art_db_obj_to_process.scraped_content and art_db_obj_to_process.scraped_content.startswith("Error:")):
                         final_error_parts.append("Summary processing issue.")
                    
                    db.refresh(art_db_obj_to_process) # Get latest tags
                    if not art_db_obj_to_process.tags and not (art_db_obj_to_process.scraped_content and art_db_obj_to_process.scraped_content.startswith("Error:")):
                        final_error_parts.append("Tag processing issue.")
                    
                    res_art.error_message = " | ".join(final_error_parts) if final_error_parts else None


    print(f"MAIN API: Preparing to send {len(results_on_page)} articles to frontend.")

    if current_page_for_slice < total_pages:
        next_page_offset = current_page_for_slice * query.page_size
        # Ensure the preload query also respects current filters if desired, or fetches broadly
        preload_db_query = db.query(Article.id, Article.url) # Only fetch id and url for preload
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
            print(f"MAIN API: Scheduling preload for {len(article_data_for_preload)} articles for next page.")
            background_tasks.add_task(
                _preload_summaries_and_tags_for_articles,
                article_data_for_preload,
                query.summary_prompt,
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

    article_db = db.query(Article).options(joinedload(Article.tags)).filter(Article.id == article_id).first()
    if not article_db:
        raise HTTPException(status_code=404, detail="Article not found.")

    print(f"API: Regenerate summary request for Article ID {article_id} with prompt: {'Custom' if request.custom_prompt else 'Default'}")

    scraped_content = article_db.scraped_content
    if not scraped_content or scraped_content.startswith("Error:") or scraped_content.startswith("Content Error:"):
        print(f"API: Content for Article ID {article_id} is missing or an error. Re-scraping...")
        scraped_docs = await scraper.scrape_urls([article_db.url], [])
        if scraped_docs and scraped_docs[0] and not scraped_docs[0].metadata.get("error") and scraped_docs[0].page_content:
            scraped_content = scraped_docs[0].page_content
            article_db.scraped_content = scraped_content
            db.add(article_db)
            db.commit()
            db.refresh(article_db)
        else:
            error_msg = scraped_docs[0].metadata.get("error", "Failed to re-scrape content") if scraped_docs and scraped_docs[0] else "Failed to re-scrape content"
            article_db.scraped_content = f"Scraping Error: {error_msg}"
            db.add(article_db)
            db.commit()
            raise HTTPException(status_code=500, detail=f"Failed to get content for summarization: {error_msg}")

    if not scraped_content or scraped_content.startswith("Error:") or scraped_content.startswith("Content Error:"):
        raise HTTPException(status_code=500, detail="Article content is still invalid after attempting re-scrape.")

    lc_doc = scraper.Document(page_content=scraped_content, metadata={"source": article_db.url, "id": article_db.id})
    prompt_to_use = request.custom_prompt if request.custom_prompt and request.custom_prompt.strip() else app_config.DEFAULT_SUMMARY_PROMPT

    new_summary_text = await summarizer.summarize_document_content(
        lc_doc, llm_summary_instance, prompt_to_use
    )

    deleted_count = db.query(Summary).filter(Summary.article_id == article_id).delete(synchronize_session=False)
    if deleted_count > 0:
        print(f"API: Deleted {deleted_count} old summary/summaries for Article ID {article_id} before regeneration.")

    new_summary_db_obj = Summary(
        article_id=article_id,
        summary_text=new_summary_text,
        prompt_used=prompt_to_use,
        model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME
    )
    db.add(new_summary_db_obj)
    db.commit()
    db.refresh(new_summary_db_obj)
    db.refresh(article_db) # Refresh article to get its relationships updated

    return ArticleResult(
        id=article_db.id,
        title=article_db.title,
        url=article_db.url,
        summary=new_summary_text,
        publisher=article_db.feed_source.name if article_db.feed_source else article_db.publisher_name,
        published_date=article_db.published_date,
        source_feed_url=article_db.feed_source.url if article_db.feed_source else None,
        tags=[ArticleTagResponse.from_orm(tag) for tag in article_db.tags],
        error_message=None if not new_summary_text.startswith("Error:") else new_summary_text
    )

@app.delete("/api/admin/cleanup-old-data", status_code=200)
async def cleanup_old_data_endpoint(days_old: int = Query(30, ge=1), db: SQLAlchemySession = Depends(get_db)):
    if days_old <= 0:
        raise HTTPException(status_code=400, detail="days_old parameter must be positive.")

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
    print(f"API: Admin request to delete data older than {days_old} days (before {cutoff_date}).")

    articles_to_delete_query = db.query(Article).filter(Article.published_date < cutoff_date)
    
    # To correctly count, it's better to get IDs first if cascade delete is complex or for logging
    article_ids_to_delete = [article.id for article in articles_to_delete_query.all()]
    article_deleted_count = len(article_ids_to_delete)

    if article_deleted_count > 0:
        # Manually delete related ArticleTag associations first if cascade is not set up on the association table directly
        # However, SQLAlchemy's cascade on the 'tags' relationship in Article model should handle this.
        # For explicit control or if issues arise:
        # db.query(article_tag_association).filter(article_tag_association.c.article_id.in_(article_ids_to_delete)).delete(synchronize_session=False)
        
        # Then delete summaries, chat history (these should cascade from Article delete if relationships are correct)
        # db.query(Summary).filter(Summary.article_id.in_(article_ids_to_delete)).delete(synchronize_session=False)
        # db.query(ChatHistory).filter(ChatHistory.article_id.in_(article_ids_to_delete)).delete(synchronize_session=False)
        
        # Finally, delete the articles themselves
        db.query(Article).filter(Article.id.in_(article_ids_to_delete)).delete(synchronize_session=False)
        
        print(f"API: Deleted {article_deleted_count} old article records (and their related summaries/chat history/tags via ORM relationships or explicit delete).")
    else:
        print("API: No old articles found to delete based on published_date.")

    db.commit()
    return {"message": f"Cleanup process completed. Deleted {article_deleted_count} articles (and related data) older than {days_old} days."}

@app.get("/api/article/{article_id}/chat-history", response_model=List[ChatHistoryItem])
async def get_article_chat_history(article_id: int, db: SQLAlchemySession = Depends(get_db)):
    history_items = db.query(ChatHistory).filter(ChatHistory.article_id == article_id).order_by(ChatHistory.timestamp.asc()).all()
    if not history_items:
        return []
    return history_items

@app.post("/api/chat-with-article", response_model=ChatResponse)
async def chat_with_article_endpoint(query: ChatQuery, db: SQLAlchemySession = Depends(get_db)):
    if not llm_chat_instance:
        raise HTTPException(status_code=503, detail="Chat service (LLM) not initialized.")

    article_db = db.query(Article).filter(Article.id == query.article_id).first()
    if not article_db:
        raise HTTPException(status_code=404, detail="Article not found in database.")

    print(f"CHAT API: Request for Article ID: {article_db.id}, Question: '{query.question[:50]}...'")

    article_text_for_chat = article_db.scraped_content or ""
    error_detail_for_chat = None

    if not article_text_for_chat or article_text_for_chat.startswith("Error:") or article_text_for_chat.startswith("Content Error:"):
        print(f"CHAT API: Article {article_db.id} has no/error content ('{article_text_for_chat[:50]}...'). Attempting re-scrape.")
        scraped_docs = await scraper.scrape_urls([str(article_db.url)], [])
        if scraped_docs and scraped_docs[0]:
            doc_item = scraped_docs[0]
            if not doc_item.metadata.get("error") and doc_item.page_content and doc_item.page_content.strip():
                article_text_for_chat = doc_item.page_content
                article_db.scraped_content = article_text_for_chat
                db.add(article_db)
                db.commit()
                print(f"CHAT API: Successfully re-scraped article {article_db.id} for chat. Length: {len(article_text_for_chat)}")
            else:
                error_detail_for_chat = doc_item.metadata.get("error", "Re-scraped content empty/error.")
                article_text_for_chat = ""
        else:
            error_detail_for_chat = "Failed to re-scrape article for chat."
            article_text_for_chat = ""
        if error_detail_for_chat:
             print(f"CHAT API Error on re-scrape for Article {article_db.id}: {error_detail_for_chat}")

    answer = await summarizer.get_chat_response(
        llm_chat_instance,
        article_text_for_chat,
        query.question,
        query.chat_prompt
    )

    final_error_message_for_response = error_detail_for_chat
    if answer.startswith("Error getting answer from AI:") or answer == "AI returned an empty answer.":
        final_error_message_for_response = answer

    new_chat_item_db = None
    if not (answer.startswith("Error:") or answer == "AI returned an empty answer."):
        try:
            new_chat_item_db = ChatHistory(
                article_id=article_db.id,
                question=query.question,
                answer=answer,
                prompt_used=query.chat_prompt or app_config.DEFAULT_CHAT_PROMPT,
                model_used=app_config.DEFAULT_CHAT_MODEL_NAME
            )
            db.add(new_chat_item_db)
            db.commit()
            db.refresh(new_chat_item_db)
            print(f"CHAT API: Saved chat item ID {new_chat_item_db.id} for article {article_db.id}")
        except Exception as e:
            db.rollback()
            print(f"CHAT API: Error saving chat history to DB for article {article_db.id}: {e}")
            final_error_message_for_response = (final_error_message_for_response or "") + " (Failed to save chat history)"

    print(f"CHAT API: Sending response for article {article_db.id}. Answer starts: '{answer[:60]}...'. Error: {final_error_message_for_response}")
    return ChatResponse(
        article_id=article_db.id,
        question=query.question,
        answer=answer,
        new_chat_history_item=ChatHistoryItem.from_orm(new_chat_item_db) if new_chat_item_db else None,
        error_message=final_error_message_for_response
    )

@app.post("/api/feeds", response_model=FeedSourceResponse, status_code=201)
async def add_new_feed_source(feed_request: AddFeedRequest, db: SQLAlchemySession = Depends(get_db)):
    existing_feed = db.query(RSSFeedSource).filter(RSSFeedSource.url == str(feed_request.url)).first()
    if existing_feed:
        raise HTTPException(status_code=409, detail="Feed URL already exists in the database.")

    new_feed = RSSFeedSource(
        url=str(feed_request.url),
        name=feed_request.name or str(feed_request.url).split('/')[2].replace("www.","") if len(str(feed_request.url).split('/')) > 2 else str(feed_request.url),
        fetch_interval_minutes=feed_request.fetch_interval_minutes or app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES
    )
    db.add(new_feed)
    try:
        db.commit()
        db.refresh(new_feed)
        print(f"API: Added new feed source: {new_feed.url}")
        return new_feed
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Feed URL already exists (IntegrityError).")
    except Exception as e:
        db.rollback()
        print(f"API: Error adding feed {feed_request.url}: {e}")
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
    if feed_update.name is not None:
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
        print(f"API: Updated feed source ID {feed_id}. New interval: {feed_db.fetch_interval_minutes}, New name: '{feed_db.name}'")
    return feed_db

@app.delete("/api/feeds/{feed_id}", status_code=204)
async def delete_feed_source(feed_id: int, db: SQLAlchemySession = Depends(get_db)):
    feed_db = db.query(RSSFeedSource).filter(RSSFeedSource.id == feed_id).first()
    if not feed_db:
        raise HTTPException(status_code=404, detail="Feed source not found.")

    db.delete(feed_db)
    db.commit()
    print(f"API: Deleted feed source ID {feed_id} and its related data (articles, summaries, chat, tags via cascade).")
    return None

@app.post("/api/trigger-rss-refresh", status_code=202)
async def manual_trigger_rss_refresh(background_tasks: BackgroundTasks):
    print("API: Manual RSS refresh triggered via endpoint.")
    background_tasks.add_task(trigger_rss_update_all_feeds)
    return {"message": "RSS feed refresh process has been initiated in the background."}


# --- Static Files & Index ---
app.mount("/static", StaticFiles(directory="static_frontend"), name="static_frontend_files")
@app.get("/")
async def serve_index(): return FileResponse('static_frontend/index.html')
