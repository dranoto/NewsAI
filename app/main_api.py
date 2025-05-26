# app/main_api.py
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, Field 
from typing import List, Optional, Dict, Any 
import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session as SQLAlchemySession 
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from . import rss_client, scraper, summarizer, config as app_config, database 
from .database import Article, Summary, ChatHistory, RSSFeedSource, get_db, db_session_scope, create_db_and_tables

app = FastAPI(title="News Summarizer API & Frontend (DB & Scheduler)", version="1.4.4") # Version increment

# --- Global Variables & Scheduler ---
llm_summary_instance: Optional[summarizer.GoogleGenerativeAI] = None
llm_chat_instance: Optional[summarizer.GoogleGenerativeAI] = None
scheduler = AsyncIOScheduler(timezone="UTC")


@app.on_event("startup")
async def startup_event():
    global llm_summary_instance, llm_chat_instance, scheduler
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
    except Exception as e:
        print(f"MAIN_API: CRITICAL ERROR during LLM Init: {e}.")
        llm_summary_instance = None
        llm_chat_instance = None

    if not scheduler.running:
        scheduler.add_job(
            trigger_rss_update_all_feeds, 
            trigger=IntervalTrigger(minutes=app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES),
            id="update_all_feeds_job", 
            name="Periodic RSS Feed Update",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) 
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
    print("SCHEDULER_JOB: Triggering update_all_subscribed_feeds...")
    with db_session_scope() as db: 
        await rss_client.update_all_subscribed_feeds(db)
    print("SCHEDULER_JOB: update_all_subscribed_feeds task finished.")


# --- Pydantic Models ---
class InitialConfigResponse(BaseModel):
    default_rss_feeds: List[str] 
    all_db_feed_sources: List[Dict[str, Any]] 
    default_articles_per_page: int
    default_summary_prompt: str
    default_chat_prompt: str
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
    summary_prompt: Optional[str] = None 

class ArticleResult(BaseModel):
    id: int 
    title: str | None = None
    url: str
    summary: str | None = None
    publisher: str | None = None 
    published_date: Optional[datetime] = None 
    source_feed_url: str | None = None 
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


# --- Helper for Preloading (Modified for DB interaction & robust iteration) ---
async def _preload_summaries_for_urls(
    article_data_to_preload: List[Dict[str, Any]], 
    custom_summary_prompt: Optional[str] = None 
):
    if not article_data_to_preload or not llm_summary_instance: 
        if not llm_summary_instance: print("BACKGROUND PRELOAD (DB): Summarization LLM not available. Preload aborted.")
        else: print("BACKGROUND PRELOAD (DB): No articles provided for preloading.")
        return
    
    print(f"BACKGROUND PRELOAD (DB): Starting for {len(article_data_to_preload)} articles.")
    processed_count = 0
    successfully_summarized_count = 0

    with db_session_scope() as db: 
        for i, article_data in enumerate(article_data_to_preload):
            article_id = article_data.get("id")
            article_url = article_data.get("url")
            
            print(f"BACKGROUND PRELOAD (DB): Processing item {i+1}/{len(article_data_to_preload)}: Article ID {article_id}, URL {article_url[:60]}...")

            if not article_id or not article_url:
                print(f"BACKGROUND PRELOAD (DB): Skipping item {i+1} due to missing ID or URL: {article_data}")
                continue
            
            try: # Outer try-except for each article in the preload batch
                article_db_obj = db.query(Article).filter(Article.id == article_id).first()
                if not article_db_obj:
                    print(f"BACKGROUND PRELOAD (DB): Article ID {article_id} not found in DB. Skipping.")
                    continue

                # Check if a recent, valid summary already exists
                existing_summary = db.query(Summary)\
                                     .filter(Summary.article_id == article_id)\
                                     .order_by(Summary.created_at.desc())\
                                     .first()
                if existing_summary and existing_summary.summary_text and \
                   not existing_summary.summary_text.startswith("Error:") and \
                   not existing_summary.summary_text.lower().startswith("content empty") and \
                   not existing_summary.summary_text.lower().startswith("content too short"):
                    print(f"BACKGROUND PRELOAD (DB): Article ID {article_id} ({article_url[:50]}...) already has a valid summary. Skipping.")
                    continue # Skip to the next article in the preload list
                
                scraped_content = article_db_obj.scraped_content
                
                if not scraped_content or scraped_content.startswith("Error:") or scraped_content.startswith("Content Error:"):
                    print(f"BACKGROUND PRELOAD (DB): Scraping for Article ID {article_id} ({article_url[:50]}...)")
                    scraped_docs = await scraper.scrape_urls([article_url], []) # Scrape one at a time for preload
                    current_scraped_content_error = None
                    if scraped_docs and scraped_docs[0]:
                        sc_doc = scraped_docs[0]
                        if not sc_doc.metadata.get("error") and sc_doc.page_content and sc_doc.page_content.strip():
                            scraped_content = sc_doc.page_content
                            article_db_obj.scraped_content = scraped_content 
                            print(f"BACKGROUND PRELOAD (DB): Successfully scraped Article ID {article_id}. Length: {len(scraped_content)}")
                        else:
                            error_val = sc_doc.metadata.get("error", "Unknown scraping error during preload")
                            article_db_obj.scraped_content = f"Scraping Error: {error_val}"
                            current_scraped_content_error = article_db_obj.scraped_content
                    else: 
                        article_db_obj.scraped_content = "Scraping Error: No document returned by scraper."
                        current_scraped_content_error = article_db_obj.scraped_content
                    
                    db.add(article_db_obj) # Add to session for potential commit
                    try:
                        db.commit() 
                        db.refresh(article_db_obj) # Ensure we have the latest state
                    except Exception as e_commit_scrape:
                        db.rollback()
                        print(f"BACKGROUND PRELOAD (DB): Error committing scraped content for Article ID {article_id}: {e_commit_scrape}")
                        continue # Skip to next article if commit fails
                    
                    if current_scraped_content_error: # If scraping resulted in an error, don't try to summarize
                        print(f"BACKGROUND PRELOAD (DB): Scraping failed for Article ID {article_id}. Error: {current_scraped_content_error}. Skipping summarization.")
                        continue


                if scraped_content and not scraped_content.startswith("Error:") and not scraped_content.startswith("Content Error:"):
                    print(f"BACKGROUND PRELOAD (DB): Summarizing Article ID {article_id} ({article_url[:50]}...)")
                    lc_doc = scraper.Document(page_content=scraped_content, metadata={"source": article_url, "id": article_id})
                    summary_text = await summarizer.summarize_document_content(lc_doc, llm_summary_instance, custom_summary_prompt) # type: ignore
                    
                    new_summary_db = Summary(
                        article_id=article_id,
                        summary_text=summary_text,
                        prompt_used=custom_summary_prompt or app_config.DEFAULT_SUMMARY_PROMPT,
                        model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME
                    )
                    db.add(new_summary_db)
                    try:
                        db.commit() 
                        print(f"BACKGROUND PRELOAD (DB): Saved summary for Article ID {article_id}. Length: {len(summary_text)}")
                        successfully_summarized_count +=1
                    except Exception as e_commit_sum:
                        db.rollback()
                        print(f"BACKGROUND PRELOAD (DB): Error committing summary for Article ID {article_id}: {e_commit_sum}")
                else:
                    print(f"BACKGROUND PRELOAD (DB): Skipping summary for Article ID {article_id} due to missing/error content ('{str(scraped_content)[:50]}...').")
            
            except Exception as e_article_preload:
                print(f"BACKGROUND PRELOAD (DB): UNHANDLED EXCEPTION while processing Article ID {article_id} (URL: {article_url}): {e_article_preload}")
                # This specific article failed, but the loop will continue for others.
                # The session scope will handle overall rollback if this error propagates out,
                # but individual commits for other articles might have already happened.
            finally:
                processed_count += 1
        
    print(f"BACKGROUND PRELOAD (DB): Finished processing batch. Attempted: {processed_count}/{len(article_data_to_preload)}. Successfully summarized: {successfully_summarized_count}.")


# --- API Endpoints ---
@app.get("/api/initial-config", response_model=InitialConfigResponse)
async def get_initial_config_endpoint(db: SQLAlchemySession = Depends(get_db)):
    # ... (endpoint remains the same) ...
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
        default_rss_fetch_interval_minutes=app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES
    )

@app.post("/api/get-news-summaries", response_model=PaginatedSummariesAPIResponse)
async def get_news_summaries_endpoint(query: NewsPageQuery, background_tasks: BackgroundTasks, db: SQLAlchemySession = Depends(get_db)):
    # ... (main logic for fetching, scraping, summarizing for current page remains largely the same) ...
    if not llm_summary_instance: 
        raise HTTPException(status_code=503, detail="Summarization service (LLM) unavailable.")

    db_query = db.query(Article)
    search_source_display = "All Articles"

    if query.feed_source_ids:
        db_query = db_query.filter(Article.feed_source_id.in_(query.feed_source_ids))
        source_names = db.query(RSSFeedSource.name).filter(RSSFeedSource.id.in_(query.feed_source_ids)).all()
        search_source_display = f"Filtered by: {', '.join([name[0] for name in source_names if name[0]]) or 'Selected Feeds'}"
    
    db_query = db_query.order_by(Article.published_date.desc().nullslast(), Article.id.desc()) 

    total_articles_available = db_query.count()
    total_pages = math.ceil(total_articles_available / query.page_size) if query.page_size > 0 else 0
    
    current_page_for_slice = query.page
    if current_page_for_slice < 1: current_page_for_slice = 1
    if current_page_for_slice > total_pages and total_pages > 0 : current_page_for_slice = total_pages
    
    offset = (current_page_for_slice - 1) * query.page_size
    articles_from_db = db_query.limit(query.page_size).offset(offset).all()

    results_on_page = []
    articles_needing_summaries_or_scraping_db_objects = [] 

    for article_db_obj in articles_from_db:
        article_result_data = {
            "id": article_db_obj.id,
            "title": article_db_obj.title,
            "url": article_db_obj.url,
            "publisher": article_db_obj.feed_source.name if article_db_obj.feed_source else article_db_obj.publisher_name,
            "published_date": article_db_obj.published_date,
            "source_feed_url": article_db_obj.feed_source.url if article_db_obj.feed_source else None,
            "summary": None,
            "error_message": None
        }

        latest_summary_obj = db.query(Summary).filter(Summary.article_id == article_db_obj.id).order_by(Summary.created_at.desc()).first()

        if latest_summary_obj:
            if latest_summary_obj.summary_text and not latest_summary_obj.summary_text.startswith("Error:"):
                article_result_data["summary"] = latest_summary_obj.summary_text
            else: 
                article_result_data["error_message"] = latest_summary_obj.summary_text
                articles_needing_summaries_or_scraping_db_objects.append(article_db_obj)
        else: 
            articles_needing_summaries_or_scraping_db_objects.append(article_db_obj)
        
        results_on_page.append(ArticleResult(**article_result_data))

    if articles_needing_summaries_or_scraping_db_objects:
        print(f"MAIN API: Found {len(articles_needing_summaries_or_scraping_db_objects)} articles needing summary/scraping for current page.")
        
        docs_to_process_for_summarization = [] 
        
        urls_to_actually_scrape_map = {} 
        for art_db in articles_needing_summaries_or_scraping_db_objects:
            if not art_db.scraped_content or art_db.scraped_content.startswith("Error:") or art_db.scraped_content.startswith("Content Error:"):
                urls_to_actually_scrape_map[art_db.url] = art_db
        
        if urls_to_actually_scrape_map:
            print(f"MAIN API: Scraping {len(urls_to_actually_scrape_map)} URLs.")
            scraped_content_results = await scraper.scrape_urls(list(urls_to_actually_scrape_map.keys()), [])
            
            for sc_doc in scraped_content_results:
                original_article_db_obj = urls_to_actually_scrape_map.get(str(sc_doc.metadata.get("source")))
                if not original_article_db_obj: continue

                if not sc_doc.metadata.get("error") and sc_doc.page_content:
                    original_article_db_obj.scraped_content = sc_doc.page_content
                else:
                    error_val = sc_doc.metadata.get("error", "Unknown scraping error")
                    original_article_db_obj.scraped_content = f"Scraping Error: {error_val}"
                db.add(original_article_db_obj)
            db.commit() 

        for art_db in articles_needing_summaries_or_scraping_db_objects:
            db.refresh(art_db) 
            if art_db.scraped_content and not art_db.scraped_content.startswith("Error:") and not art_db.scraped_content.startswith("Content Error:"):
                docs_to_process_for_summarization.append(
                    scraper.Document(page_content=art_db.scraped_content, metadata={"source": art_db.url, "id": art_db.id, "title": art_db.title})
                )
            else: 
                for res_art in results_on_page:
                    if res_art.id == art_db.id:
                        res_art.error_message = art_db.scraped_content 
                        break

        for lc_doc_to_summarize in docs_to_process_for_summarization:
            article_db_id = lc_doc_to_summarize.metadata["id"]
            print(f"MAIN API: Summarizing {lc_doc_to_summarize.metadata['source'][:70]}... (Prompt: '{query.summary_prompt[:30] if query.summary_prompt else 'Default'}')")
            summary_text = await summarizer.summarize_document_content(
                lc_doc_to_summarize, llm_summary_instance, query.summary_prompt # type: ignore
            )
            new_summary_db = Summary(
                article_id=article_db_id, 
                summary_text=summary_text,
                prompt_used=query.summary_prompt or app_config.DEFAULT_SUMMARY_PROMPT,
                model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME
            )
            db.add(new_summary_db)
            
            for res_art in results_on_page:
                if res_art.id == article_db_id:
                    if summary_text.startswith("Error:"):
                        res_art.error_message = summary_text
                        res_art.summary = None
                    else:
                        res_art.summary = summary_text
                        res_art.error_message = None 
                    break
            print(f"MAIN API: Generated summary for {lc_doc_to_summarize.metadata['source'][:50]}... Length: {len(summary_text)}. Starts: '{summary_text[:60]}...'")
        db.commit() 

    print(f"MAIN API: Preparing to send {len(results_on_page)} articles to frontend.")
    for i, res_art in enumerate(results_on_page):
        print(f"  Article {i+1} Title: {res_art.title[:60] if res_art.title else 'N/A'}")
        print(f"    Summary: {res_art.summary[:70] if res_art.summary else 'N/A - Error or Empty'}")
        if res_art.error_message:
            print(f"    Error Msg: {res_art.error_message}")

    if current_page_for_slice < total_pages:
        next_page_offset = current_page_for_slice * query.page_size 
        next_page_articles_db_objects = db_query.limit(query.page_size).offset(next_page_offset).all()
        
        article_data_for_preload = []
        for article_obj in next_page_articles_db_objects:
            article_data_for_preload.append({
                "id": article_obj.id,
                "url": article_obj.url,
            })

        if article_data_for_preload:
            print(f"MAIN API: Scheduling preload for {len(article_data_for_preload)} articles for next page.")
            background_tasks.add_task(
                _preload_summaries_for_urls,
                article_data_for_preload, 
                query.summary_prompt
            )

    return PaginatedSummariesAPIResponse(
        search_source=search_source_display, requested_page=current_page_for_slice, 
        page_size=query.page_size, total_articles_available=total_articles_available, 
        total_pages=total_pages, processed_articles_on_page=results_on_page
    )

# ... (rest of the API endpoints: /api/article/{article_id}/chat-history, /api/chat-with-article, /api/feeds, etc. remain the same) ...
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
        llm_chat_instance, # type: ignore
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
                prompt_used=query.chat_prompt or app_config.DEFAULT_SUMMARY_PROMPT, # Corrected to use DEFAULT_CHAT_PROMPT
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
    print(f"API: Deleted feed source ID {feed_id} and its related data.")
    return None 

@app.post("/api/trigger-rss-refresh", status_code=202) 
async def manual_trigger_rss_refresh(background_tasks: BackgroundTasks):
    print("API: Manual RSS refresh triggered via endpoint.")
    background_tasks.add_task(trigger_rss_update_all_feeds) 
    return {"message": "RSS feed refresh process has been initiated in the background."}


app.mount("/static", StaticFiles(directory="static_frontend"), name="static_frontend_files")
@app.get("/")
async def serve_index(): return FileResponse('static_frontend/index.html')

