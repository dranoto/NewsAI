# app/main_api.py
from fastapi import FastAPI, HTTPException, Query as FastAPIQuery, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict, Any 
import math
import asyncio 

from . import rss_client
from . import scraper
from . import summarizer
from . import config

app = FastAPI(title="News Summarizer API & Frontend (Dynamic Prompts)", version="1.3.1")

# --- Global Variables ---
llm_summary_instance: Optional[summarizer.GoogleGenerativeAI] = None
llm_chat_instance: Optional[summarizer.GoogleGenerativeAI] = None

all_rss_articles_cache: List[dict] = [] 
article_summary_cache: Dict[str, str] = {} 

@app.on_event("startup")
async def startup_event():
    global llm_summary_instance, llm_chat_instance
    print("Attempting to initialize LLM instances...")
    try:
        if not config.GEMINI_API_KEY:
            print("CRITICAL ERROR: GEMINI_API_KEY not found. LLM features will be disabled.")
            return 

        llm_summary_instance = summarizer.initialize_llm(
            api_key=config.GEMINI_API_KEY,
            model_name=config.DEFAULT_SUMMARY_MODEL_NAME,
            temperature=0.2, max_output_tokens=400 
        )
        if llm_summary_instance:
            print(f"Summarization LLM ({config.DEFAULT_SUMMARY_MODEL_NAME}) initialized.")
        else:
            print("CRITICAL ERROR: Summarization LLM failed to initialize.")


        llm_chat_instance = summarizer.initialize_llm(
            api_key=config.GEMINI_API_KEY,
            model_name=config.DEFAULT_CHAT_MODEL_NAME,
            temperature=0.5, max_output_tokens=1536
        )
        if llm_chat_instance:
            print(f"Chat LLM ({config.DEFAULT_CHAT_MODEL_NAME}) initialized.")
        else:
            print("CRITICAL ERROR: Chat LLM failed to initialize.")
            
    except Exception as e:
        print(f"CRITICAL ERROR: LLM Init Failed - {e}.")
        llm_summary_instance = None
        llm_chat_instance = None

# --- Pydantic Models ---
class InitialConfigResponse(BaseModel):
    default_rss_feeds: List[str]
    default_articles_per_page: int
    default_summary_prompt: str
    default_chat_prompt: str

class NewsPageQuery(BaseModel):
    page: int = 1
    page_size: int = config.DEFAULT_PAGE_SIZE
    rss_feed_urls: Optional[List[HttpUrl]] = []
    force_refresh_rss: bool = False
    summary_prompt: Optional[str] = None 

class ArticleResult(BaseModel):
    title: str | None = None; url: str | None = None; summary: str | None = None
    publisher: str | None = None; published_date: str | None = None
    source_feed_url: str | None = None 
    error_message: str | None = None

class PaginatedSummariesAPIResponse(BaseModel):
    search_source: str; requested_page: int; page_size: int
    total_articles_available: int; total_pages: int
    processed_articles_on_page: list[ArticleResult]

class ChatQuery(BaseModel):
    article_url: HttpUrl
    question: str
    chat_prompt: Optional[str] = None 

class ChatResponse(BaseModel):
    question: str; answer: str; article_url: HttpUrl; error_message: str | None = None

# --- Helper for Preloading ---
async def _preload_summaries_for_urls(
    urls_to_preload: List[str], 
    custom_summary_prompt: Optional[str] = None 
):
    if not urls_to_preload or not llm_summary_instance: 
        if not llm_summary_instance: print("BACKGROUND PRELOAD: Summarization LLM not available.")
        return
    
    print(f"BACKGROUND PRELOAD: Starting for {len(urls_to_preload)} URLs.")
    
    actually_need_processing = [
        url for url in urls_to_preload
        if str(url) not in article_summary_cache or \
           article_summary_cache[str(url)].startswith("Error:") or \
           article_summary_cache[str(url)].lower().startswith("content empty") or \
           article_summary_cache[str(url)].lower().startswith("content too short")
    ]

    if not actually_need_processing:
        print("BACKGROUND PRELOAD: All URLs already have valid summaries in cache.")
        return

    print(f"BACKGROUND PRELOAD: Actually pre-processing {len(actually_need_processing)} URLs.")
    scraped_docs_list = await scraper.scrape_urls([str(url) for url in actually_need_processing], [])
    
    for doc in scraped_docs_list:
        doc_url_str = str(doc.metadata.get('source'))
        if not doc_url_str: continue

        if doc_url_str in article_summary_cache and \
           not (article_summary_cache[doc_url_str].startswith("Error:") or \
                article_summary_cache[doc_url_str].lower().startswith("content empty") or \
                article_summary_cache[doc_url_str].lower().startswith("content too short")):
            continue

        if doc and not doc.metadata.get("error") and doc.page_content and doc.page_content.strip():
            if llm_summary_instance: 
                print(f"BACKGROUND PRELOAD: Summarizing {doc_url_str}")
                summary = await summarizer.summarize_document_content(doc, llm_summary_instance, custom_summary_prompt)
                article_summary_cache[doc_url_str] = summary
                print(f"BACKGROUND PRELOAD: Cached summary for {doc_url_str}. Length: {len(summary)}. Starts with: '{summary[:50]}...'")
            else:
                article_summary_cache[doc_url_str] = "Error: Summarization service unavailable during preload."
        elif doc and doc.metadata.get("error"):
            article_summary_cache[doc_url_str] = f"Scraping Error: {doc.metadata.get('error')}"
        else:
            article_summary_cache[doc_url_str] = f"Content Error: Failed to scrape/process content for preload: {doc_url_str}"
    print(f"BACKGROUND PRELOAD: Finished processing {len(actually_need_processing)} URLs.")

# --- API Endpoints ---
@app.get("/api/initial-config", response_model=InitialConfigResponse)
async def get_initial_config_endpoint():
    return InitialConfigResponse(
        default_rss_feeds=config.RSS_FEED_URLS,
        default_articles_per_page=config.DEFAULT_PAGE_SIZE,
        default_summary_prompt=config.DEFAULT_SUMMARY_PROMPT,
        default_chat_prompt=config.DEFAULT_CHAT_PROMPT
    )

async def refresh_rss_cache_if_needed(force_refresh: bool, requested_rss_urls: Optional[List[HttpUrl]]):
    # ... (No changes needed in this helper function regarding prompts) ...
    global all_rss_articles_cache, article_summary_cache
    feeds_to_fetch_str: List[str] = []
    if requested_rss_urls:
        feeds_to_fetch_str = [str(url) for url in requested_rss_urls]
    
    final_feeds_to_target = feeds_to_fetch_str if feeds_to_fetch_str else config.RSS_FEED_URLS

    if not final_feeds_to_target: 
        if force_refresh: 
            all_rss_articles_cache = []
            # article_summary_cache.clear() # Decided against clearing globally
            print("RSS cache cleared (no target feeds). Summary cache NOT globally cleared.")
        return

    if force_refresh or not all_rss_articles_cache:
        print(f"Refreshing RSS. Force refresh: {force_refresh}. Cache empty: {not all_rss_articles_cache}. Fetching from: {final_feeds_to_target if final_feeds_to_target else 'all configured default feeds'}")
        all_rss_articles_cache = await rss_client.fetch_all_articles_from_configured_feeds(final_feeds_to_target)
        print(f"RSS Refreshed. Fetched {len(all_rss_articles_cache)} articles. Summary cache NOT globally cleared.")
    else:
        print(f"Using cached RSS articles ({len(all_rss_articles_cache)} items).")


@app.post("/api/get-news-summaries", response_model=PaginatedSummariesAPIResponse)
async def get_news_summaries_endpoint(query: NewsPageQuery, background_tasks: BackgroundTasks):
    if not llm_summary_instance: 
        raise HTTPException(status_code=503, detail="Summarization service (LLM) unavailable.")

    await refresh_rss_cache_if_needed(query.force_refresh_rss, query.rss_feed_urls if query.force_refresh_rss else None)
    
    if not all_rss_articles_cache:
        return PaginatedSummariesAPIResponse( search_source="No feeds configured or no articles found.", requested_page=query.page, page_size=query.page_size, total_articles_available=0, total_pages=0, processed_articles_on_page=[])

    target_articles_for_display = all_rss_articles_cache
    search_source_display = "All Available RSS Feeds" 

    if query.rss_feed_urls and not query.force_refresh_rss:
        requested_source_urls_str = {str(url) for url in query.rss_feed_urls}
        target_articles_for_display = [ article for article in all_rss_articles_cache if article.get('source_feed_url') in requested_source_urls_str ]
        search_source_display = f"Filtered: {', '.join(s[:30]+'...' if len(s)>30 else s for s in requested_source_urls_str)}" if requested_source_urls_str else "All Feeds (cache)"
    elif not query.rss_feed_urls and query.force_refresh_rss:
        search_source_display = "Default RSS Feeds (Refreshed)"
    elif not query.rss_feed_urls and not query.force_refresh_rss:
        search_source_display = "All Cached RSS Feeds"
    elif query.rss_feed_urls and query.force_refresh_rss:
        search_source_display = f"Refreshed & Filtered: {', '.join(str(f)[:30]+'...' if len(str(f))>30 else str(f) for f in query.rss_feed_urls)}"

    total_articles_available = len(target_articles_for_display)
    total_pages = math.ceil(total_articles_available / query.page_size) if query.page_size > 0 else 0
    current_page_for_slice = query.page
    if current_page_for_slice < 1: current_page_for_slice = 1
    if current_page_for_slice > total_pages and total_pages > 0 : current_page_for_slice = total_pages
    
    start_index = (current_page_for_slice - 1) * query.page_size
    end_index = start_index + query.page_size
    articles_for_this_page_metadata = target_articles_for_display[start_index:end_index]

    if not articles_for_this_page_metadata and total_articles_available > 0:
        return PaginatedSummariesAPIResponse(search_source=search_source_display, requested_page=query.page, page_size=query.page_size, total_articles_available=total_articles_available, total_pages=total_pages, processed_articles_on_page=[])

    urls_to_scrape_this_page = [article['url'] for article in articles_for_this_page_metadata if article.get('url')]
    scraped_docs_map: Dict[str, Any] = {} 
    if urls_to_scrape_this_page:
        urls_needing_processing_current_page = [
            url for url in urls_to_scrape_this_page 
            if str(url) not in article_summary_cache or \
               article_summary_cache[str(url)].startswith("Error:") or \
               article_summary_cache[str(url)].lower().startswith("content empty") or \
               article_summary_cache[str(url)].lower().startswith("content too short") 
        ]
        if urls_needing_processing_current_page:
            print(f"MAIN API: Need to scrape/process {len(urls_needing_processing_current_page)} URLs for current page.")
            scraped_docs_list = await scraper.scrape_urls([str(url) for url in urls_needing_processing_current_page], [])
            for doc_item in scraped_docs_list: # Renamed doc to doc_item to avoid conflict with function name
                if doc_item.metadata.get('source'): # Use doc_item here
                    scraped_docs_map[doc_item.metadata.get('source')] = doc_item # And here
        else:
            print("MAIN API: All articles for this page have cached summaries (or known errors).")
    
    results_on_page = []
    for meta_item in articles_for_this_page_metadata:
        article_url_str = str(meta_item.get('url')); title = meta_item.get('title')
        publisher = meta_item.get('publisher'); published_date = meta_item.get('published date')
        source_feed_url = meta_item.get('source_feed_url') 
        current_summary = None; error_msg = None

        if not article_url_str: 
            error_msg = "Article URL missing."
        elif article_url_str in article_summary_cache and not (
            article_summary_cache[article_url_str].startswith("Error:") or 
            article_summary_cache[article_url_str].lower().startswith("content empty") or
            article_summary_cache[article_url_str].lower().startswith("content too short") 
        ):
            current_summary = article_summary_cache[article_url_str]
            print(f"MAIN API: Using cached summary for {article_url_str[:50]}...")
        else: 
            doc_content_obj = scraped_docs_map.get(article_url_str)
            if doc_content_obj and not doc_content_obj.metadata.get("error") and doc_content_obj.page_content and doc_content_obj.page_content.strip():
                print(f"MAIN API: Summarizing {article_url_str[:70]}... using prompt: '{query.summary_prompt[:50] if query.summary_prompt else 'Default Prompt'}...'")
                current_summary = await summarizer.summarize_document_content(
                    doc_content_obj, 
                    llm_summary_instance, # type: ignore 
                    query.summary_prompt 
                )
                article_summary_cache[article_url_str] = current_summary 
                print(f"MAIN API: Generated summary for {article_url_str[:50]}... Length: {len(current_summary)}. Starts: '{current_summary[:60]}...'")
                if current_summary.startswith("Error:") or current_summary.lower().startswith("content empty") or current_summary.lower().startswith("content too short"): 
                    error_msg = current_summary # Keep the error message from summary
                    current_summary = None # No valid summary to display
            elif doc_content_obj and doc_content_obj.metadata.get("error"): 
                error_msg = f"Scraping Error: {doc_content_obj.metadata.get('error')}"
                article_summary_cache[article_url_str] = error_msg 
            else: 
                if article_url_str in article_summary_cache:
                    error_msg = article_summary_cache[article_url_str] 
                    print(f"MAIN API: Using existing error from cache for {article_url_str[:50]}...: {error_msg}") # Corrected line
                else:
                    error_msg = f"Content Error: Failed to scrape/process content for: {article_url_str}"
                    article_summary_cache[article_url_str] = error_msg
                
        results_on_page.append(ArticleResult(
            title=title, url=article_url_str, summary=current_summary, 
            publisher=publisher, published_date=published_date, 
            source_feed_url=source_feed_url, error_message=error_msg
        ))
    
    if current_page_for_slice < total_pages:
        next_page_start_index = current_page_for_slice * query.page_size
        next_page_end_index = next_page_start_index + query.page_size
        articles_for_next_page_metadata = target_articles_for_display[next_page_start_index:next_page_end_index]
        urls_to_preload_str = [str(article['url']) for article in articles_for_next_page_metadata if article.get('url')]
        if urls_to_preload_str:
            background_tasks.add_task(
                _preload_summaries_for_urls, 
                urls_to_preload_str, 
                query.summary_prompt 
            )

    return PaginatedSummariesAPIResponse(
        search_source=search_source_display, requested_page=current_page_for_slice, 
        page_size=query.page_size, total_articles_available=total_articles_available, 
        total_pages=total_pages, processed_articles_on_page=results_on_page
    )

@app.post("/api/chat-with-article", response_model=ChatResponse)
async def chat_with_article_endpoint(query: ChatQuery):
    if not llm_chat_instance: 
        raise HTTPException(status_code=503, detail="Chat service (LLM) not initialized.")
    
    print(f"CHAT API: Received request for URL: {query.article_url}, Question: '{query.question[:50]}...'")
    scraped_docs = await scraper.scrape_urls([str(query.article_url)], []) 
    article_text_for_chat = "" 
    error_detail_for_chat = None 

    if scraped_docs and scraped_docs[0]:
        doc_item = scraped_docs[0] # Renamed doc to doc_item
        if not doc_item.metadata.get("error") and doc_item.page_content and doc_item.page_content.strip(): # Use doc_item
            article_text_for_chat = doc_item.page_content # Use doc_item
            print(f"CHAT API: Successfully got article content for chat. Length: {len(article_text_for_chat)}")
        else:
            error_detail_for_chat = doc_item.metadata.get("error", "Scraped content empty/error on re-scrape.") # Use doc_item
            print(f"CHAT API Error: Could not get article content for {query.article_url}. Reason: {error_detail_for_chat}")
    else:
        error_detail_for_chat = "Failed to re-scrape article for chat (no document returned)."
        print(f"CHAT API Error: Scraper returned no document for {query.article_url}")

    answer = await summarizer.get_chat_response(
        llm_chat_instance, # type: ignore
        article_text_for_chat, 
        query.question,
        query.chat_prompt 
    )
    
    final_error_message_for_response = error_detail_for_chat
    if answer.startswith("Error getting answer from AI:") or answer == "AI returned an empty answer.":
        final_error_message_for_response = answer 
    
    print(f"CHAT API: Sending response. Answer starts: '{answer[:60]}...'. Error msg: {final_error_message_for_response}")
    return ChatResponse(
        question=query.question, 
        answer=answer, 
        article_url=query.article_url, 
        error_message=final_error_message_for_response
    )

app.mount("/static", StaticFiles(directory="static_frontend"), name="static_frontend_files")
@app.get("/")
async def serve_index(): return FileResponse('static_frontend/index.html')

