# app/routers/article_routes.py
import logging
import math
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session as SQLAlchemySession, joinedload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_ # For OR conditions in SQLAlchemy queries
from typing import List, Dict, Any, Optional

# Langchain document type for creating Document objects
from langchain_core.documents import Document as LangchainDocument # Renamed for clarity
from langchain_google_genai import GoogleGenerativeAI # For type hinting LLM instances

# Relative imports for modules within the 'app' directory
from .. import database # For get_db, ORM models (Article, Summary, Tag, RSSFeedSource), and db_session_scope
from .. import scraper # For scrape_urls function
from .. import summarizer # For summarize_document_content, generate_tags_for_text
from .. import config as app_config # For application configurations
from ..schemas import ( # Pydantic models for request/response validation and serialization
    PaginatedSummariesAPIResponse,
    NewsPageQuery,
    ArticleResult,
    RegenerateSummaryRequest,
    ArticleTagResponse
)
# Import dependency functions for LLM instances
from ..dependencies import get_llm_summary, get_llm_tag

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Create an APIRouter instance for these article-related routes
router = APIRouter(
    prefix="/api",  # Common path prefix
    tags=["articles"]  # For grouping in OpenAPI documentation
)

async def _preload_summaries_and_tags_for_articles(
    article_data_to_preload: List[Dict[str, Any]],
    custom_summary_prompt: Optional[str], 
    custom_tag_prompt: Optional[str],     
    llm_summary_in: GoogleGenerativeAI,   
    llm_tag_in: GoogleGenerativeAI        
):
    """
    Background task to preload summaries and tags for a list of articles.
    This involves scraping content if missing (saving both text and HTML), 
    then generating summaries and tags from the text content.
    Uses its own database session scope.
    """
    if not article_data_to_preload:
        logger.info("BACKGROUND PRELOAD: No articles provided for preloading.")
        return
    if not llm_summary_in and not llm_tag_in:
        logger.warning("BACKGROUND PRELOAD: Neither Summarization nor Tag Generation LLM was provided. Skipping preload.")
        return

    logger.info(f"BACKGROUND PRELOAD: Starting for {len(article_data_to_preload)} articles (Summaries & Tags).")
    processed_count = 0
    successfully_summarized_count = 0
    successfully_tagged_count = 0

    with database.db_session_scope() as db:
        for i, article_data in enumerate(article_data_to_preload):
            article_id = article_data.get("id")
            article_url = article_data.get("url")

            logger.info(f"BACKGROUND PRELOAD: Processing item {i+1}/{len(article_data_to_preload)}: Article ID {article_id}, URL {str(article_url)[:60]}...")

            if not article_id or not article_url:
                logger.warning(f"BACKGROUND PRELOAD: Skipping item {i+1} due to missing ID or URL: {article_data}")
                continue

            try:
                article_db_obj = db.query(database.Article).options(joinedload(database.Article.tags)).filter(database.Article.id == article_id).first()
                if not article_db_obj:
                    logger.warning(f"BACKGROUND PRELOAD: Article ID {article_id} not found in DB. Skipping.")
                    continue

                # Check if scraping is needed based on scraped_text_content
                # Also consider scraping if full_html_content is missing, even if text is there (e.g. from older version)
                needs_scraping = (
                    not article_db_obj.scraped_text_content or 
                    article_db_obj.scraped_text_content.startswith("Error:") or 
                    article_db_obj.scraped_text_content.startswith("Content Error:") or
                    not article_db_obj.full_html_content # Added condition: also scrape if full HTML is missing
                )
                
                current_scraped_text_content = article_db_obj.scraped_text_content # Keep current text before potential re-scrape

                if needs_scraping:
                    logger.info(f"BACKGROUND PRELOAD: Scraping for Article ID {article_id} ({str(article_url)[:50]}...) as text or HTML content is missing/invalid.")
                    scraped_docs_list: List[LangchainDocument] = await scraper.scrape_urls(
                        [str(article_url)],
                        path_to_extension_folder=app_config.PATH_TO_EXTENSION,
                        use_headless_browser=app_config.USE_HEADLESS_BROWSER
                    )
                    
                    scraper_error_message = None
                    if scraped_docs_list and scraped_docs_list[0]:
                        sc_doc = scraped_docs_list[0]
                        if not sc_doc.metadata.get("error") and sc_doc.page_content and sc_doc.page_content.strip():
                            article_db_obj.scraped_text_content = sc_doc.page_content
                            article_db_obj.full_html_content = sc_doc.metadata.get('full_html_content')
                            current_scraped_text_content = article_db_obj.scraped_text_content # Update for summarization
                            logger.info(f"BACKGROUND PRELOAD: Successfully scraped Article ID {article_id}. Text length: {len(article_db_obj.scraped_text_content or '')}, HTML present: {'Yes' if article_db_obj.full_html_content else 'No'}")
                        else:
                            scraper_error_message = sc_doc.metadata.get("error", "Unknown scraping error during preload")
                            article_db_obj.scraped_text_content = f"Scraping Error: {scraper_error_message}"
                            article_db_obj.full_html_content = None # Clear HTML on error
                            current_scraped_text_content = article_db_obj.scraped_text_content # Update for summarization
                    else:
                        scraper_error_message = "Scraping Error: No document returned by scraper."
                        article_db_obj.scraped_text_content = scraper_error_message
                        article_db_obj.full_html_content = None
                        current_scraped_text_content = article_db_obj.scraped_text_content
                    
                    db.add(article_db_obj)
                    try: db.commit(); db.refresh(article_db_obj)
                    except Exception as e_commit_scrape: db.rollback(); logger.error(f"BACKGROUND PRELOAD: Error committing scraped content for Article ID {article_id}: {e_commit_scrape}", exc_info=True); continue
                    
                    if scraper_error_message: logger.warning(f"BACKGROUND PRELOAD: Scraping failed for Article ID {article_id}. Error: {scraper_error_message}. Skipping summarization & tagging."); continue
                
                # Use current_scraped_text_content which is either original or newly scraped (and valid)
                if llm_summary_in and current_scraped_text_content and not current_scraped_text_content.startswith("Error:") and not current_scraped_text_content.startswith("Content Error:"):
                    existing_summary = db.query(database.Summary).filter(database.Summary.article_id == article_id).order_by(database.Summary.created_at.desc()).first()
                    needs_summary = not existing_summary or not existing_summary.summary_text or existing_summary.summary_text.startswith("Error:") or existing_summary.summary_text.lower().startswith("content empty") or existing_summary.summary_text.lower().startswith("content too short")
                    
                    if needs_summary:
                        logger.info(f"BACKGROUND PRELOAD: Summarizing Article ID {article_id} using text content.")
                        lc_doc_for_summary = LangchainDocument(page_content=current_scraped_text_content, metadata={"source": str(article_url), "id": article_id})
                        summary_text = await summarizer.summarize_document_content(lc_doc_for_summary, llm_summary_in, custom_summary_prompt)
                        
                        db.query(database.Summary).filter(database.Summary.article_id == article_id).delete(synchronize_session=False)
                        new_summary_db = database.Summary(
                            article_id=article_id, summary_text=summary_text,
                            prompt_used=custom_summary_prompt or app_config.DEFAULT_SUMMARY_PROMPT,
                            model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME
                        )
                        db.add(new_summary_db)
                        try: db.commit(); logger.info(f"BACKGROUND PRELOAD: Saved summary for Article ID {article_id}."); successfully_summarized_count +=1
                        except Exception as e_commit_sum: db.rollback(); logger.error(f"BACKGROUND PRELOAD: Error committing summary for Article ID {article_id}: {e_commit_sum}", exc_info=True)

                db.refresh(article_db_obj) 
                if llm_tag_in and current_scraped_text_content and not current_scraped_text_content.startswith("Error:") and not current_scraped_text_content.startswith("Content Error:"):
                    if not article_db_obj.tags: 
                        logger.info(f"BACKGROUND PRELOAD: Generating tags for Article ID {article_id} using text content.")
                        tag_names = await summarizer.generate_tags_for_text(current_scraped_text_content, llm_tag_in, custom_tag_prompt)
                        
                        if tag_names:
                            for tag_name in tag_names:
                                tag_name_cleaned = tag_name.strip().lower(); 
                                if not tag_name_cleaned: continue
                                tag_db = db.query(database.Tag).filter(database.Tag.name == tag_name_cleaned).first()
                                if not tag_db:
                                    tag_db = database.Tag(name=tag_name_cleaned); db.add(tag_db)
                                    try: db.flush() 
                                    except IntegrityError: db.rollback(); tag_db = db.query(database.Tag).filter(database.Tag.name == tag_name_cleaned).first()
                                    except Exception as e_flush_tag: db.rollback(); logger.error(f"BACKGROUND PRELOAD: Error flushing new tag '{tag_name_cleaned}' for Article ID {article_id}: {e_flush_tag}", exc_info=True); continue 
                                if tag_db and tag_db not in article_db_obj.tags: article_db_obj.tags.append(tag_db)
                            try: db.commit(); logger.info(f"BACKGROUND PRELOAD: Saved tags for Article ID {article_id}: {tag_names}"); successfully_tagged_count += 1
                            except Exception as e_commit_tags: db.rollback(); logger.error(f"BACKGROUND PRELOAD: Error committing tags for Article ID {article_id}: {e_commit_tags}", exc_info=True)
                
                elif not current_scraped_text_content or current_scraped_text_content.startswith("Error:") or current_scraped_text_content.startswith("Content Error:"):
                     logger.warning(f"BACKGROUND PRELOAD: Skipping summary & tags for Article ID {article_id} due to missing/error text content ('{str(current_scraped_text_content)[:50]}...').")
            except Exception as e_article_preload: logger.error(f"BACKGROUND PRELOAD: UNHANDLED EXCEPTION while processing Article ID {article_id} (URL: {article_url}): {e_article_preload}", exc_info=True); db.rollback() 
            finally: processed_count += 1
    logger.info(f"BACKGROUND PRELOAD: Finished processing batch. Attempted: {processed_count}/{len(article_data_to_preload)}. Summarized: {successfully_summarized_count}. Tagged: {successfully_tagged_count}.")


@router.post("/get-news-summaries", response_model=PaginatedSummariesAPIResponse)
async def get_news_summaries_endpoint(
    query: NewsPageQuery,
    background_tasks: BackgroundTasks,
    db: SQLAlchemySession = Depends(database.get_db),
    llm_summary: GoogleGenerativeAI = Depends(get_llm_summary), 
    llm_tag: GoogleGenerativeAI = Depends(get_llm_tag)           
):
    if not llm_summary and not llm_tag: 
        logger.error("API Error: Summarization or Tagging LLM not available via DI in get_news_summaries_endpoint.")
        raise HTTPException(status_code=503, detail="Core AI services (Summarization/Tagging LLM) unavailable via DI.")

    logger.info(f"API Call: Get news summaries. Query: {query.model_dump_json(indent=2)}")
    db_query = db.query(database.Article)
    search_source_display_parts = []
    if query.feed_source_ids:
        db_query = db_query.filter(database.Article.feed_source_id.in_(query.feed_source_ids))
        source_names_result = db.query(database.RSSFeedSource.name).filter(database.RSSFeedSource.id.in_(query.feed_source_ids)).all()
        source_names = [name_tuple[0] for name_tuple in source_names_result if name_tuple[0]]
        search_source_display_parts.append(f"Feeds: {', '.join(source_names) or 'Selected Feeds'}")
    if query.tag_ids:
        for tag_id in query.tag_ids: db_query = db_query.filter(database.Article.tags.any(database.Tag.id == tag_id))
        tag_names_result = db.query(database.Tag.name).filter(database.Tag.id.in_(query.tag_ids)).all()
        tag_names = [name_tuple[0] for name_tuple in tag_names_result if name_tuple[0]]
        search_source_display_parts.append(f"Tags: {', '.join(tag_names) or 'Selected Tags'}")
    if query.keyword:
        keyword_like = f"%{query.keyword}%"
        # Search in title and scraped_text_content
        db_query = db_query.filter(or_(database.Article.title.ilike(keyword_like), database.Article.scraped_text_content.ilike(keyword_like)))
        search_source_display_parts.append(f"Keyword: '{query.keyword}'")
    search_source_display = " & ".join(search_source_display_parts) if search_source_display_parts else "All Articles"
    db_query = db_query.options(joinedload(database.Article.tags), joinedload(database.Article.feed_source)).order_by(database.Article.published_date.desc().nullslast(), database.Article.id.desc())
    total_articles_available = db_query.count()
    total_pages = math.ceil(total_articles_available / query.page_size) if query.page_size > 0 else 0
    current_page_for_slice = max(1, query.page); 
    if total_pages > 0: current_page_for_slice = min(current_page_for_slice, total_pages)
    offset = (current_page_for_slice - 1) * query.page_size
    articles_from_db = db_query.limit(query.page_size).offset(offset).all()
    results_on_page: List[ArticleResult] = []
    articles_needing_processing_db_objects: List[database.Article] = []
    for article_db_obj in articles_from_db:
        article_result_data = {"id": article_db_obj.id, "title": article_db_obj.title, "url": article_db_obj.url, "publisher": article_db_obj.feed_source.name if article_db_obj.feed_source else article_db_obj.publisher_name, "published_date": article_db_obj.published_date, "source_feed_url": article_db_obj.feed_source.url if article_db_obj.feed_source else None, "summary": None, "tags": [ArticleTagResponse.from_orm(tag) for tag in article_db_obj.tags], "error_message": None}
        latest_summary_obj = db.query(database.Summary).filter(database.Summary.article_id == article_db_obj.id).order_by(database.Summary.created_at.desc()).first()
        needs_processing = False; current_error_parts = []
        # Check based on scraped_text_content and full_html_content
        if not article_db_obj.scraped_text_content or article_db_obj.scraped_text_content.startswith("Error:") or not article_db_obj.full_html_content: 
            needs_processing = True; current_error_parts.append("Content needs scraping (text or HTML missing/invalid).")
        if not latest_summary_obj or latest_summary_obj.summary_text.startswith("Error:"): needs_processing = True; current_error_parts.append(latest_summary_obj.summary_text if latest_summary_obj and latest_summary_obj.summary_text.startswith("Error:") else "Summary needs generation.")
        elif latest_summary_obj: article_result_data["summary"] = latest_summary_obj.summary_text
        if not article_db_obj.tags: needs_processing = True; current_error_parts.append("Tags need generation.")
        if current_error_parts: article_result_data["error_message"] = " | ".join(current_error_parts)
        if needs_processing: articles_needing_processing_db_objects.append(article_db_obj)
        results_on_page.append(ArticleResult(**article_result_data))

    if articles_needing_processing_db_objects:
        logger.info(f"MAIN API: Found {len(articles_needing_processing_db_objects)} articles needing on-demand processing for current page.")
        for art_db_obj_to_process in articles_needing_processing_db_objects:
            db.refresh(art_db_obj_to_process); 
            if art_db_obj_to_process.feed_source: db.refresh(art_db_obj_to_process.feed_source)
            
            # On-demand scraping if text or HTML is missing/invalid
            current_text_content_for_ai = art_db_obj_to_process.scraped_text_content
            if not current_text_content_for_ai or current_text_content_for_ai.startswith("Error:") or not art_db_obj_to_process.full_html_content:
                logger.info(f"MAIN API: On-demand scraping for {art_db_obj_to_process.url[:70]}...")
                scraped_docs_list_ondemand: List[LangchainDocument] = await scraper.scrape_urls([str(art_db_obj_to_process.url)], app_config.PATH_TO_EXTENSION, app_config.USE_HEADLESS_BROWSER)
                scraper_error_msg_ondemand = None
                if scraped_docs_list_ondemand and scraped_docs_list_ondemand[0]:
                    sc_doc_ondemand = scraped_docs_list_ondemand[0]
                    if not sc_doc_ondemand.metadata.get("error") and sc_doc_ondemand.page_content:
                        art_db_obj_to_process.scraped_text_content = sc_doc_ondemand.page_content
                        art_db_obj_to_process.full_html_content = sc_doc_ondemand.metadata.get('full_html_content')
                        current_text_content_for_ai = art_db_obj_to_process.scraped_text_content # Update for AI
                    else: 
                        scraper_error_msg_ondemand = sc_doc_ondemand.metadata.get("error", "Unknown on-demand scraping error")
                        art_db_obj_to_process.scraped_text_content = f"Scraping Error: {scraper_error_msg_ondemand}"
                        art_db_obj_to_process.full_html_content = None
                        current_text_content_for_ai = art_db_obj_to_process.scraped_text_content
                else:
                    scraper_error_msg_ondemand = "On-demand scraping failed: No document returned."
                    art_db_obj_to_process.scraped_text_content = scraper_error_msg_ondemand
                    art_db_obj_to_process.full_html_content = None
                    current_text_content_for_ai = art_db_obj_to_process.scraped_text_content
                
                db.add(art_db_obj_to_process); 
                try: db.commit(); db.refresh(art_db_obj_to_process)
                except Exception as e: db.rollback(); logger.error(f"Error committing on-demand scrape for article {art_db_obj_to_process.id}: {e}", exc_info=True)
            
            # Use current_text_content_for_ai for summarization and tagging
            if llm_summary and current_text_content_for_ai and not current_text_content_for_ai.startswith("Error:"):
                latest_summary_obj_check = db.query(database.Summary).filter(database.Summary.article_id == art_db_obj_to_process.id).order_by(database.Summary.created_at.desc()).first()
                if not latest_summary_obj_check or latest_summary_obj_check.summary_text.startswith("Error:"):
                    logger.info(f"MAIN API: On-demand summarizing {art_db_obj_to_process.url[:70]}...")
                    lc_doc_sum = LangchainDocument(page_content=current_text_content_for_ai, metadata={"source": str(art_db_obj_to_process.url), "id": art_db_obj_to_process.id})
                    summary_text = await summarizer.summarize_document_content(lc_doc_sum, llm_summary, query.summary_prompt)
                    db.query(database.Summary).filter(database.Summary.article_id == art_db_obj_to_process.id).delete(synchronize_session=False)
                    new_sum_db = database.Summary(article_id=art_db_obj_to_process.id, summary_text=summary_text, prompt_used=query.summary_prompt or app_config.DEFAULT_SUMMARY_PROMPT, model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME)
                    db.add(new_sum_db); 
                    try: db.commit(); db.refresh(new_sum_db)
                    except Exception as e: db.rollback(); logger.error(f"Error committing on-demand summary for article {art_db_obj_to_process.id}: {e}", exc_info=True); summary_text = f"Error saving summary: {e}"
                    for res_art in results_on_page: 
                        if res_art.id == art_db_obj_to_process.id: res_art.summary = summary_text if not summary_text.startswith("Error:") else None
            
            db.refresh(art_db_obj_to_process)
            if llm_tag and current_text_content_for_ai and not current_text_content_for_ai.startswith("Error:") and not art_db_obj_to_process.tags:
                logger.info(f"MAIN API: On-demand generating tags for {art_db_obj_to_process.url[:70]}...")
                tag_names_gen = await summarizer.generate_tags_for_text(current_text_content_for_ai, llm_tag, query.tag_generation_prompt)
                if tag_names_gen:
                    art_db_obj_to_process.tags.clear(); db.flush()
                    for t_name in tag_names_gen:
                        t_name_clean = t_name.strip().lower(); 
                        if not t_name_clean: continue
                        tag_db_o = db.query(database.Tag).filter(database.Tag.name == t_name_clean).first()
                        if not tag_db_o: tag_db_o = database.Tag(name=t_name_clean); db.add(tag_db_o); 
                        try: db.flush()
                        except IntegrityError: db.rollback(); tag_db_o = db.query(database.Tag).filter(database.Tag.name == t_name_clean).first()
                        if tag_db_o and tag_db_o not in art_db_obj_to_process.tags : art_db_obj_to_process.tags.append(tag_db_o)
                    try: db.commit(); db.refresh(art_db_obj_to_process)
                    except Exception as e: db.rollback(); logger.error(f"Error committing on-demand tags for article {art_db_obj_to_process.id}: {e}", exc_info=True)

            for res_art in results_on_page: 
                if res_art.id == art_db_obj_to_process.id:
                    final_error_parts = []
                    if art_db_obj_to_process.scraped_text_content and art_db_obj_to_process.scraped_text_content.startswith("Error:"): final_error_parts.append(art_db_obj_to_process.scraped_text_content)
                    if not art_db_obj_to_process.full_html_content and not (art_db_obj_to_process.scraped_text_content and art_db_obj_to_process.scraped_text_content.startswith("Error:")): final_error_parts.append("Full HTML content missing.")
                    
                    summary_final_check = db.query(database.Summary).filter(database.Summary.article_id == art_db_obj_to_process.id).order_by(database.Summary.created_at.desc()).first()
                    if summary_final_check:
                        if summary_final_check.summary_text.startswith("Error:"): final_error_parts.append(summary_final_check.summary_text)
                        res_art.summary = summary_final_check.summary_text if not summary_final_check.summary_text.startswith("Error:") else None
                    elif not (art_db_obj_to_process.scraped_text_content and art_db_obj_to_process.scraped_text_content.startswith("Error:")): final_error_parts.append("Summary still pending or failed.")
                    
                    db.refresh(art_db_obj_to_process); res_art.tags = [ArticleTagResponse.from_orm(t) for t in art_db_obj_to_process.tags] 
                    if not art_db_obj_to_process.tags and not (art_db_obj_to_process.scraped_text_content and art_db_obj_to_process.scraped_text_content.startswith("Error:")): final_error_parts.append("Tags still pending or failed.")
                    res_art.error_message = " | ".join(final_error_parts) if final_error_parts else None

    logger.info(f"MAIN API: Preparing to send {len(results_on_page)} articles to frontend for page {current_page_for_slice}.")
    if current_page_for_slice < total_pages:
        next_page_offset = current_page_for_slice * query.page_size
        preload_db_query_ids_urls = db.query(database.Article.id, database.Article.url)
        if query.feed_source_ids: preload_db_query_ids_urls = preload_db_query_ids_urls.filter(database.Article.feed_source_id.in_(query.feed_source_ids))
        if query.tag_ids:
            for tag_id in query.tag_ids: preload_db_query_ids_urls = preload_db_query_ids_urls.filter(database.Article.tags.any(database.Tag.id == tag_id))
        if query.keyword:
            keyword_like_preload = f"%{query.keyword}%"
            preload_db_query_ids_urls = preload_db_query_ids_urls.filter(or_(database.Article.title.ilike(keyword_like_preload), database.Article.scraped_text_content.ilike(keyword_like_preload)))
        next_page_articles_for_preload_tuples = preload_db_query_ids_urls.order_by(database.Article.published_date.desc().nullslast(), database.Article.id.desc()).limit(query.page_size).offset(next_page_offset).all()
        article_data_for_preload_list = [{"id": art_id, "url": art_url} for art_id, art_url in next_page_articles_for_preload_tuples]
        if article_data_for_preload_list:
            logger.info(f"MAIN API: Scheduling background preload for {len(article_data_for_preload_list)} articles for next page.")
            background_tasks.add_task(_preload_summaries_and_tags_for_articles, article_data_for_preload_list, query.summary_prompt, query.tag_generation_prompt, llm_summary, llm_tag)

    return PaginatedSummariesAPIResponse(search_source=search_source_display, requested_page=current_page_for_slice, page_size=query.page_size, total_articles_available=total_articles_available, total_pages=total_pages, processed_articles_on_page=results_on_page)

@router.post("/articles/{article_id}/regenerate-summary", response_model=ArticleResult)
async def regenerate_article_summary(
    article_id: int,
    request_body: RegenerateSummaryRequest, 
    db: SQLAlchemySession = Depends(database.get_db),
    llm_summary: GoogleGenerativeAI = Depends(get_llm_summary), 
    llm_tag: GoogleGenerativeAI = Depends(get_llm_tag)           
):
    if not llm_summary: 
        logger.error("API Error: Summarization LLM not available via DI in regenerate_article_summary.")
        raise HTTPException(status_code=503, detail="Summarization LLM not available.")

    article_db = db.query(database.Article).options(joinedload(database.Article.tags), joinedload(database.Article.feed_source)).filter(database.Article.id == article_id).first()
    if not article_db: logger.warning(f"API Warning: Article ID {article_id} not found for summary regeneration."); raise HTTPException(status_code=404, detail="Article not found.")
    logger.info(f"API Call: Regenerate summary for Article ID {article_id}. Custom prompt: {'Yes' if request_body.custom_prompt else 'No'}. Regenerate tags: {request_body.regenerate_tags}")
    
    current_text_content = article_db.scraped_text_content
    # Re-scrape if text or HTML content is missing/invalid
    if not current_text_content or current_text_content.startswith("Error:") or not article_db.full_html_content:
        logger.info(f"API: Content for Article ID {article_id} needs re-scraping before summary regeneration.")
        scraped_docs_list_regen: List[LangchainDocument] = await scraper.scrape_urls([str(article_db.url)], app_config.PATH_TO_EXTENSION, app_config.USE_HEADLESS_BROWSER)
        scraper_error_msg_regen = None
        if scraped_docs_list_regen and scraped_docs_list_regen[0]:
            sc_doc_regen = scraped_docs_list_regen[0]
            if not sc_doc_regen.metadata.get("error") and sc_doc_regen.page_content:
                article_db.scraped_text_content = sc_doc_regen.page_content
                article_db.full_html_content = sc_doc_regen.metadata.get('full_html_content')
                current_text_content = article_db.scraped_text_content # Update for use
                db.add(article_db); db.commit(); db.refresh(article_db)
                logger.info(f"API: Successfully re-scraped content for Article ID {article_id} for regeneration.")
            else:
                scraper_error_msg_regen = sc_doc_regen.metadata.get("error", "Failed to re-scrape content (regen)")
                article_db.scraped_text_content = f"Scraping Error: {scraper_error_msg_regen}"; article_db.full_html_content = None;
                current_text_content = article_db.scraped_text_content
                db.add(article_db); db.commit()
                logger.error(f"API: Failed to re-scrape content for Article ID {article_id}: {scraper_error_msg_regen}"); raise HTTPException(status_code=500, detail=f"Failed to get content for summarization: {scraper_error_msg_regen}")
        else:
            scraper_error_msg_regen = "Failed to re-scrape: No document returned."
            article_db.scraped_text_content = f"Scraping Error: {scraper_error_msg_regen}"; article_db.full_html_content = None;
            current_text_content = article_db.scraped_text_content
            db.add(article_db); db.commit()
            logger.error(f"API: Failed to re-scrape content for Article ID {article_id}: {scraper_error_msg_regen}"); raise HTTPException(status_code=500, detail=f"Failed to get content for summarization: {scraper_error_msg_regen}")

    if not current_text_content or current_text_content.startswith("Error:"): 
        logger.error(f"API: Article text content for ID {article_id} is still invalid after re-scrape attempt during regeneration.")
        raise HTTPException(status_code=500, detail="Article text content is still invalid after attempting re-scrape.")
    
    lc_doc_for_summary_regen = LangchainDocument(page_content=current_text_content, metadata={"source": str(article_db.url), "id": article_db.id})
    prompt_to_use = request_body.custom_prompt if request_body.custom_prompt and request_body.custom_prompt.strip() else app_config.DEFAULT_SUMMARY_PROMPT
    new_summary_text = await summarizer.summarize_document_content(lc_doc_for_summary_regen, llm_summary, prompt_to_use)
    db.query(database.Summary).filter(database.Summary.article_id == article_id).delete(synchronize_session=False)
    new_summary_db_obj = database.Summary(article_id=article_id, summary_text=new_summary_text, prompt_used=prompt_to_use, model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME)
    db.add(new_summary_db_obj)
    try: db.commit(); db.refresh(new_summary_db_obj); logger.info(f"API: Regenerated and saved new summary for Article ID {article_id}")
    except Exception as e: db.rollback(); logger.error(f"API: Error saving regenerated summary for Article ID {article_id}: {e}", exc_info=True); new_summary_text = f"Error saving summary: {e}"

    if request_body.regenerate_tags and llm_tag and current_text_content and not current_text_content.startswith("Error:"):
        logger.info(f"API: Regenerating tags for Article ID {article_id}.")
        if article_db.tags: article_db.tags.clear(); 
        try: db.commit(); db.refresh(article_db)
        except Exception as e_clear: db.rollback(); logger.error(f"API: Error clearing tags for Article ID {article_id}: {e_clear}", exc_info=True)
        tag_names_generated = await summarizer.generate_tags_for_text(current_text_content, llm_tag, None)
        if tag_names_generated:
            for tag_name in tag_names_generated:
                tag_name_cleaned = tag_name.strip().lower()
                if not tag_name_cleaned: continue
                tag_db_obj = db.query(database.Tag).filter(database.Tag.name == tag_name_cleaned).first()
                if not tag_db_obj:
                    tag_db_obj = database.Tag(name=tag_name_cleaned); db.add(tag_db_obj)
                    try: db.flush()
                    except IntegrityError: db.rollback(); tag_db_obj = db.query(database.Tag).filter(database.Tag.name == tag_name_cleaned).first()
                if tag_db_obj and tag_db_obj not in article_db.tags: article_db.tags.append(tag_db_obj)
            try: db.commit(); db.refresh(article_db); logger.info(f"API: Regenerated and saved tags for Article ID {article_id}: {tag_names_generated}")
            except Exception as e_commit_tags: db.rollback(); logger.error(f"API: Error saving regenerated tags for Article ID {article_id}: {e_commit_tags}", exc_info=True)
    
    db.refresh(article_db)
    return ArticleResult(id=article_db.id, title=article_db.title, url=article_db.url, summary=new_summary_text, publisher=article_db.feed_source.name if article_db.feed_source else article_db.publisher_name, published_date=article_db.published_date, source_feed_url=article_db.feed_source.url if article_db.feed_source else None, tags=[ArticleTagResponse.from_orm(tag) for tag in article_db.tags], error_message=None if not new_summary_text.startswith("Error:") else new_summary_text)
