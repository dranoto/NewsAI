# app/main_api.py
from fastapi import FastAPI, HTTPException, Query as FastAPIQuery, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from typing import List, Optional, Dict 
import math
import asyncio # For creating background tasks

from . import rss_client
from . import scraper
from . import summarizer
from . import config
from langchain.chains.summarize import load_summarize_chain

app = FastAPI(title="News Summarizer API & Frontend (Preloading)", version="1.1.0")

# --- Global Variables ---
llm_summary_instance = None
llm_chat_instance = None
global_summarization_chain = None

all_rss_articles_cache: List[dict] = [] 
article_summary_cache: Dict[str, str] = {}
# cache_last_updated: Optional[float] = None 


@app.on_event("startup")
async def startup_event():
    global llm_summary_instance, llm_chat_instance, global_summarization_chain
    print("Attempting to initialize LLM instances and summarization chain...")
    try:
        if not config.GEMINI_API_KEY:
            print("CRITICAL ERROR: GEMINI_API_KEY not found. LLM features will be disabled.")
            return 

        llm_summary_instance = summarizer.initialize_llm(
            api_key=config.GEMINI_API_KEY,
            model_name=config.DEFAULT_SUMMARY_MODEL_NAME,
            temperature=0.2, max_output_tokens=300
        )
        print(f"Summarization LLM ({config.DEFAULT_SUMMARY_MODEL_NAME}) initialized.")

        llm_chat_instance = summarizer.initialize_llm(
            api_key=config.GEMINI_API_KEY,
            model_name=config.DEFAULT_CHAT_MODEL_NAME,
            temperature=0.5, max_output_tokens=1536
        )
        print(f"Chat LLM ({config.DEFAULT_CHAT_MODEL_NAME}) initialized.")

        if llm_summary_instance:
            summarization_prompt_template = summarizer.get_summarization_prompt()
            global_summarization_chain = load_summarize_chain(
                llm_summary_instance, chain_type="stuff", prompt=summarization_prompt_template
            )
            print("Summarization chain initialized successfully.")
        else:
            print("CRITICAL ERROR: Summarization LLM failed to initialize.")

    except Exception as e:
        print(f"CRITICAL ERROR: LLM Init Failed - {e}.")
        llm_summary_instance = None; llm_chat_instance = None; global_summarization_chain = None

# --- Pydantic Models ---
class InitialConfigResponse(BaseModel):
    default_rss_feeds: List[str]
    default_articles_per_page: int

class NewsPageQuery(BaseModel):
    page: int = 1
    page_size: int = config.DEFAULT_PAGE_SIZE
    rss_feed_urls: List[HttpUrl] = []
    prioritized_sites: List[str] = []
    force_refresh_rss: bool = False

class ArticleResult(BaseModel):
    title: str | None = None; url: str | None = None; summary: str | None = None
    publisher: str | None = None; published_date: str | None = None
    error_message: str | None = None

class PaginatedSummariesAPIResponse(BaseModel):
    search_source: str; requested_page: int; page_size: int
    total_articles_available: int; total_pages: int
    processed_articles_on_page: list[ArticleResult]

class ChatQuery(BaseModel):
    article_url: HttpUrl; question: str

class ChatResponse(BaseModel):
    question: str; answer: str; article_url: HttpUrl; error_message: str | None = None

# --- Helper for Preloading ---
async def _preload_summaries_for_urls(urls_to_preload: List[str], prioritized_sites_for_scraper: List[str]):
    if not urls_to_preload:
        return
    
    print(f"BACKGROUND: Preloading summaries for {len(urls_to_preload)} URLs.")
    
    actually_need_processing = [
        url for url in urls_to_preload
        if str(url) not in article_summary_cache or \
           article_summary_cache[str(url)].startswith("Error:") or \
           article_summary_cache[str(url)].lower().startswith("content empty")
    ]

    if not actually_need_processing:
        print("BACKGROUND: All preload URLs already have valid summaries in cache.")
        return

    print(f"BACKGROUND: Actually pre-processing {len(actually_need_processing)} URLs.")
    # Ensure urls passed to scraper are strings
    scraped_docs_list = await scraper.scrape_urls([str(url) for url in actually_need_processing], prioritized_sites_for_scraper)
    
    for doc in scraped_docs_list:
        doc_url_str = str(doc.metadata.get('source'))
        if not doc_url_str: continue

        if doc_url_str in article_summary_cache and \
           not (article_summary_cache[doc_url_str].startswith("Error:") or \
                article_summary_cache[doc_url_str].lower().startswith("content empty")):
            continue

        if doc and not doc.metadata.get("error") and doc.page_content and doc.page_content.strip():
            if global_summarization_chain: 
                summary = await summarizer.summarize_document_content(doc, global_summarization_chain)
                article_summary_cache[doc_url_str] = summary
                print(f"BACKGROUND: Cached summary for preloaded URL: {doc_url_str}")
            else:
                print(f"BACKGROUND: Summarization chain not available, cannot preload summary for {doc_url_str}")
                article_summary_cache[doc_url_str] = "Error: Summarization service unavailable during preload."
        elif doc and doc.metadata.get("error"):
            article_summary_cache[doc_url_str] = f"Scraping: {doc.metadata.get('error')}"
        else:
            article_summary_cache[doc_url_str] = f"Failed to scrape/process content for preload: {doc_url_str}"


# --- API Endpoints ---
@app.get("/api/initial-config", response_model=InitialConfigResponse)
async def get_initial_config():
    return InitialConfigResponse(
        default_rss_feeds=config.RSS_FEED_URLS,
        default_articles_per_page=config.DEFAULT_PAGE_SIZE
    )

async def refresh_rss_cache_if_needed(force_refresh: bool, requested_rss_urls: List[HttpUrl]):
    global all_rss_articles_cache, article_summary_cache
    feeds_to_use_str = [str(url) for url in requested_rss_urls]
    final_feeds_to_fetch = feeds_to_use_str if feeds_to_use_str else config.RSS_FEED_URLS
    if not final_feeds_to_fetch:
        all_rss_articles_cache = []; article_summary_cache.clear(); return
    if force_refresh or not all_rss_articles_cache:
        all_rss_articles_cache = await rss_client.fetch_all_articles_from_configured_feeds(final_feeds_to_fetch)
        article_summary_cache.clear(); print("Article summary cache cleared due to RSS refresh.")
    else: print(f"Using cached RSS articles ({len(all_rss_articles_cache)} items).")

@app.post("/api/get-news-summaries", response_model=PaginatedSummariesAPIResponse)
async def get_news_summaries_endpoint(query: NewsPageQuery, background_tasks: BackgroundTasks):
    if not global_summarization_chain or not llm_summary_instance:
        raise HTTPException(status_code=503, detail="Summarization service unavailable.")

    await refresh_rss_cache_if_needed(query.force_refresh_rss, query.rss_feed_urls)
    if not all_rss_articles_cache:
        return PaginatedSummariesAPIResponse(search_source="User-defined RSS Feeds", requested_page=query.page, page_size=query.page_size, total_articles_available=0, total_pages=0, processed_articles_on_page=[])

    total_articles_available = len(all_rss_articles_cache)
    total_pages = math.ceil(total_articles_available / query.page_size) if query.page_size > 0 else 0
    current_page_for_slice = query.page
    if current_page_for_slice < 1: current_page_for_slice = 1
    if current_page_for_slice > total_pages and total_pages > 0 : current_page_for_slice = total_pages
    
    start_index = (current_page_for_slice - 1) * query.page_size
    end_index = start_index + query.page_size
    articles_for_this_page_metadata = all_rss_articles_cache[start_index:end_index]

    if not articles_for_this_page_metadata and total_articles_available > 0:
        return PaginatedSummariesAPIResponse(search_source="User-defined RSS Feeds", requested_page=query.page, page_size=query.page_size, total_articles_available=total_articles_available, total_pages=total_pages, processed_articles_on_page=[])

    urls_to_scrape_this_page = [article['url'] for article in articles_for_this_page_metadata if article.get('url')]
    scraped_docs_map = {}
    if urls_to_scrape_this_page:
        urls_needing_processing_current_page = [
            url for url in urls_to_scrape_this_page 
            if str(url) not in article_summary_cache or article_summary_cache[str(url)].startswith("Error:") or article_summary_cache[str(url)].lower().startswith("content empty")
        ]
        if urls_needing_processing_current_page:
            # Ensure urls passed to scraper are strings
            scraped_docs_list = await scraper.scrape_urls([str(url) for url in urls_needing_processing_current_page], query.prioritized_sites)
            for doc in scraped_docs_list:
                if doc.metadata.get('source'): scraped_docs_map[doc.metadata.get('source')] = doc
    
    results_on_page = []
    for meta_item in articles_for_this_page_metadata:
        article_url_str = str(meta_item.get('url')); title = meta_item.get('title')
        publisher = meta_item.get('publisher'); published_date = meta_item.get('published date')
        current_summary = None; error_msg = None
        if not article_url_str: error_msg = "Article URL missing."
        elif article_url_str in article_summary_cache and not (article_summary_cache[article_url_str].startswith("Error:") or article_summary_cache[article_url_str].lower().startswith("content empty")):
            current_summary = article_summary_cache[article_url_str]
        else:
            doc_content_obj = scraped_docs_map.get(article_url_str)
            if doc_content_obj and not doc_content_obj.metadata.get("error") and doc_content_obj.page_content and doc_content_obj.page_content.strip():
                current_summary = await summarizer.summarize_document_content(doc_content_obj, global_summarization_chain)
                article_summary_cache[article_url_str] = current_summary
                if current_summary.startswith("Error:") or current_summary.lower().startswith("content empty"): 
                    error_msg = current_summary; current_summary = None
            elif doc_content_obj and doc_content_obj.metadata.get("error"): 
                error_msg = f"Scraping: {doc_content_obj.metadata.get('error')}"
                article_summary_cache[article_url_str] = error_msg
            else: 
                error_msg = f"Failed to scrape/process: {article_url_str}"
                # Corrected Indentation Below
                if article_url_str not in article_summary_cache: 
                    article_summary_cache[article_url_str] = error_msg
                elif article_summary_cache[article_url_str].startswith("Error:") or \
                     article_summary_cache[article_url_str].lower().startswith("content empty"):
                    error_msg = article_summary_cache[article_url_str] # Use existing error if it was a known failure
        results_on_page.append(ArticleResult(title=title, url=article_url_str, summary=current_summary, publisher=publisher, published_date=published_date, error_message=error_msg))
    
    # --- Preload next page ---
    if current_page_for_slice < total_pages:
        next_page_start_index = current_page_for_slice * query.page_size
        next_page_end_index = next_page_start_index + query.page_size
        articles_for_next_page_metadata = all_rss_articles_cache[next_page_start_index:next_page_end_index]
        # Ensure urls passed for preloading are strings
        urls_to_preload_str = [str(article['url']) for article in articles_for_next_page_metadata if article.get('url')]
        if urls_to_preload_str:
            background_tasks.add_task(_preload_summaries_for_urls, urls_to_preload_str, query.prioritized_sites)
            print(f"Added task to preload {len(urls_to_preload_str)} summaries for page {current_page_for_slice + 1}.")

    return PaginatedSummariesAPIResponse(search_source="User-defined RSS Feeds", requested_page=current_page_for_slice, page_size=query.page_size, total_articles_available=total_articles_available, total_pages=total_pages, processed_articles_on_page=results_on_page)

@app.post("/api/chat-with-article", response_model=ChatResponse)
async def chat_with_article_endpoint(query: ChatQuery):
    global llm_chat_instance 
    if not llm_chat_instance: raise HTTPException(status_code=503, detail="Chat LLM not initialized.")
    # Ensure URL passed to scraper is a string
    scraped_docs = await scraper.scrape_urls([str(query.article_url)], []) 
    article_text_for_chat = None; error_detail_for_chat = "Failed to re-scrape article for chat."
    if scraped_docs and scraped_docs[0]:
        doc = scraped_docs[0]
        if not doc.metadata.get("error") and doc.page_content and doc.page_content.strip(): article_text_for_chat = doc.page_content
        else: error_detail_for_chat = doc.metadata.get("error", "Scraped content empty/error on re-scrape.")
    if article_text_for_chat is None: print(f"Chatting without specific article content for {query.article_url} due to: {error_detail_for_chat}")
    answer = await summarizer.get_chat_response(llm_chat_instance, article_text_for_chat or "", query.question)
    final_error_message_for_response = error_detail_for_chat if article_text_for_chat is None else None
    if answer.startswith("Error getting answer from AI:"): final_error_message_for_response = answer
    return ChatResponse(question=query.question, answer=answer, article_url=str(query.article_url), error_message=final_error_message_for_response)

app.mount("/static", StaticFiles(directory="static_frontend"), name="static_frontend_files")
@app.get("/")
async def serve_index(): return FileResponse('static_frontend/index.html')
