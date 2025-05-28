# app/routers/article_routes.py
import logging
import math
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session as SQLAlchemySession, joinedload
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_ 
from typing import List, Dict, Any, Optional

from langchain_core.documents import Document as LangchainDocument
from langchain_google_genai import GoogleGenerativeAI 

from .. import database 
from .. import scraper 
from .. import summarizer 
from .. import config as app_config 
from ..schemas import ( 
    PaginatedSummariesAPIResponse,
    NewsPageQuery,
    ArticleResult,
    RegenerateSummaryRequest,
    ArticleTagResponse
)
from ..dependencies import get_llm_summary, get_llm_tag

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["articles"])

# Define a constant for what indicates a persistent scraping error message
SCRAPING_ERROR_PREFIX = "Scraping Error:"
CONTENT_ERROR_PREFIX = "Content Error:" # If you use this for other types of errors
TEXT_LENGTH_THRESHOLD = 100


async def _should_attempt_scrape(article_db_obj: database.Article) -> bool:
    """
    Determines if an article should be automatically scraped (or re-scraped).
    Skips if it previously had a definitive scraping error or successfully yielded very short content.
    """
    if article_db_obj.scraped_text_content and article_db_obj.scraped_text_content.startswith(SCRAPING_ERROR_PREFIX):
        logger.info(f"Article ID {article_db_obj.id} previously had a scraping error ('{article_db_obj.scraped_text_content[:50]}...'). Skipping automatic re-scrape.")
        return False

    # Check if it was a successful scrape but yielded short content and has HTML (indicating it's likely a non-text page)
    if article_db_obj.scraped_text_content and \
       not article_db_obj.scraped_text_content.startswith(SCRAPING_ERROR_PREFIX) and \
       len(article_db_obj.scraped_text_content) < TEXT_LENGTH_THRESHOLD and \
       article_db_obj.full_html_content is not None: # Check that full_html_content was also processed
        logger.info(f"Article ID {article_db_obj.id} has short text content from a previous successful scrape. Skipping automatic re-scrape.")
        return False
        
    # If text or HTML is missing, and it's not a known persistent failure, then yes, attempt scrape.
    if not article_db_obj.scraped_text_content or not article_db_obj.full_html_content:
        logger.info(f"Article ID {article_db_obj.id} needs scraping: text_content or full_html_content is missing/invalid and not a known failure.")
        return True
        
    return False # Default to not needing a re-scrape if content exists and isn't an error/short


async def _preload_summaries_and_tags_for_articles(
    article_data_to_preload: List[Dict[str, Any]],
    custom_summary_prompt: Optional[str], 
    custom_tag_prompt: Optional[str],     
    llm_summary_in: GoogleGenerativeAI,   
    llm_tag_in: GoogleGenerativeAI        
):
    if not article_data_to_preload: return
    if not llm_summary_in and not llm_tag_in: logger.warning("BACKGROUND PRELOAD: LLMs not provided. Skipping."); return

    logger.info(f"BACKGROUND PRELOAD: Starting for {len(article_data_to_preload)} articles.")
    successfully_summarized_count = 0 # Initialize counts
    successfully_tagged_count = 0     # Initialize counts

    with database.db_session_scope() as db:
        for i, article_data in enumerate(article_data_to_preload):
            article_id = article_data.get("id"); article_url = article_data.get("url")
            if not article_id or not article_url: logger.warning(f"BG PRELOAD: Skip item {i+1}, missing ID/URL."); continue

            logger.info(f"BG PRELOAD: Item {i+1}/{len(article_data_to_preload)}: Article ID {article_id}, URL {str(article_url)[:60]}...")
            try:
                article_db_obj = db.query(database.Article).options(joinedload(database.Article.tags)).filter(database.Article.id == article_id).first()
                if not article_db_obj: logger.warning(f"BG PRELOAD: Article ID {article_id} not found. Skipping."); continue

                needs_scraping_check = await _should_attempt_scrape(article_db_obj)
                current_scraped_text_content = article_db_obj.scraped_text_content

                if needs_scraping_check:
                    logger.info(f"BG PRELOAD: Scraping Article ID {article_id}...")
                    scraped_docs_list: List[LangchainDocument] = await scraper.scrape_urls([str(article_url)])
                    
                    scraper_error_message = None
                    if scraped_docs_list and scraped_docs_list[0]:
                        sc_doc = scraped_docs_list[0]
                        scraper_error_message = sc_doc.metadata.get("error") 
                        if not scraper_error_message and sc_doc.page_content:
                            article_db_obj.scraped_text_content = sc_doc.page_content
                            article_db_obj.full_html_content = sc_doc.metadata.get('full_html_content')
                            current_scraped_text_content = article_db_obj.scraped_text_content
                            logger.info(f"BG PRELOAD: Scraped Article ID {article_id}. Text: {len(current_scraped_text_content or '')}, HTML: {'Yes' if article_db_obj.full_html_content else 'No'}")
                            if len(current_scraped_text_content or '') < TEXT_LENGTH_THRESHOLD:
                                logger.warning(f"BG PRELOAD: Scrape for Article ID {article_id} yielded short text (length {len(current_scraped_text_content or '')}). Content might be non-ideal for processing.")
                        else: 
                            scraper_error_message = scraper_error_message or "Scraper returned no page_content."
                            article_db_obj.scraped_text_content = f"{SCRAPING_ERROR_PREFIX} {scraper_error_message}"
                            article_db_obj.full_html_content = None
                            current_scraped_text_content = article_db_obj.scraped_text_content
                    else: 
                        scraper_error_message = "No document returned by scraper."
                        article_db_obj.scraped_text_content = f"{SCRAPING_ERROR_PREFIX} {scraper_error_message}"
                        article_db_obj.full_html_content = None
                        current_scraped_text_content = article_db_obj.scraped_text_content
                    
                    db.add(article_db_obj); db.commit(); db.refresh(article_db_obj)
                    if scraper_error_message: logger.warning(f"BG PRELOAD: Scraping for Article ID {article_id} failed: {scraper_error_message}. Skipping further AI processing."); continue
                
                can_process_ai = current_scraped_text_content and not current_scraped_text_content.startswith(SCRAPING_ERROR_PREFIX) and len(current_scraped_text_content) >= TEXT_LENGTH_THRESHOLD
                
                if llm_summary_in and can_process_ai:
                    existing_summary = db.query(database.Summary).filter(database.Summary.article_id == article_id).order_by(database.Summary.created_at.desc()).first()
                    needs_summary = not existing_summary or existing_summary.summary_text.startswith("Error:") 
                    if needs_summary:
                        logger.info(f"BG PRELOAD: Summarizing Article ID {article_id} using text content.")
                        lc_doc_for_summary = LangchainDocument(page_content=current_scraped_text_content, metadata={"source": str(article_url), "id": article_id})
                        summary_text = await summarizer.summarize_document_content(lc_doc_for_summary, llm_summary_in, custom_summary_prompt)
                        db.query(database.Summary).filter(database.Summary.article_id == article_id).delete(synchronize_session=False)
                        new_summary_db = database.Summary(article_id=article_id, summary_text=summary_text, prompt_used=custom_summary_prompt or app_config.DEFAULT_SUMMARY_PROMPT, model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME)
                        db.add(new_summary_db); db.commit(); 
                        successfully_summarized_count +=1 

                db.refresh(article_db_obj) 
                if llm_tag_in and can_process_ai and not article_db_obj.tags:
                    logger.info(f"BG PRELOAD: Generating tags for Article ID {article_id} using text content.")
                    tag_names = await summarizer.generate_tags_for_text(current_scraped_text_content, llm_tag_in, custom_tag_prompt)
                    if tag_names: # Correctly indented block starts here
                        for tag_name in tag_names:
                            tag_name_cleaned = tag_name.strip().lower()
                            if not tag_name_cleaned: continue
                            tag_db = db.query(database.Tag).filter(database.Tag.name == tag_name_cleaned).first()
                            if not tag_db:
                                tag_db = database.Tag(name=tag_name_cleaned)
                                db.add(tag_db)
                                try:
                                    db.flush() 
                                except IntegrityError: 
                                    db.rollback()
                                    tag_db = db.query(database.Tag).filter(database.Tag.name == tag_name_cleaned).first()
                                except Exception as e_flush_tag: 
                                    db.rollback()
                                    logger.error(f"BACKGROUND PRELOAD: Error flushing new tag '{tag_name_cleaned}' for Article ID {article_id}: {e_flush_tag}", exc_info=True)
                                    continue 
                            if tag_db and tag_db not in article_db_obj.tags: 
                                article_db_obj.tags.append(tag_db)
                        try: 
                            db.commit()
                            logger.info(f"BACKGROUND PRELOAD: Saved tags for Article ID {article_id}: {tag_names}")
                            successfully_tagged_count += 1
                        except Exception as e_commit_tags: 
                            db.rollback()
                            logger.error(f"BACKGROUND PRELOAD: Error committing tags for Article ID {article_id}: {e_commit_tags}", exc_info=True)
                
                # This 'if' block is now at the correct indentation level
                if not can_process_ai:
                     logger.warning(f"BG PRELOAD: Skipping AI processing for Article ID {article_id} due to missing, error, or short text content ('{str(current_scraped_text_content)[:50]}...').")
            
            except Exception as e_article_preload: 
                logger.error(f"BG PRELOAD: UNHANDLED EXCEPTION for Article ID {article_id}: {e_article_preload}", exc_info=True)
                db.rollback()

    logger.info(f"BACKGROUND PRELOAD: Finished processing batch. Summarized: {successfully_summarized_count}, Tagged: {successfully_tagged_count}.")


@router.post("/get-news-summaries", response_model=PaginatedSummariesAPIResponse)
async def get_news_summaries_endpoint(
    query: NewsPageQuery, background_tasks: BackgroundTasks, db: SQLAlchemySession = Depends(database.get_db),
    llm_summary: GoogleGenerativeAI = Depends(get_llm_summary), llm_tag: GoogleGenerativeAI = Depends(get_llm_tag)           
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
    articles_needing_ondemand_scrape: List[database.Article] = [] 
    for article_db_obj in articles_from_db:
        article_result_data = {"id": article_db_obj.id, "title": article_db_obj.title, "url": article_db_obj.url, "publisher": article_db_obj.feed_source.name if article_db_obj.feed_source else article_db_obj.publisher_name, "published_date": article_db_obj.published_date, "source_feed_url": article_db_obj.feed_source.url if article_db_obj.feed_source else None, "summary": None, "tags": [ArticleTagResponse.from_orm(tag) for tag in article_db_obj.tags], "error_message": None}
        latest_summary_obj = db.query(database.Summary).filter(database.Summary.article_id == article_db_obj.id).order_by(database.Summary.created_at.desc()).first()
        if latest_summary_obj and not latest_summary_obj.summary_text.startswith("Error:"):
             article_result_data["summary"] = latest_summary_obj.summary_text
        
        needs_on_demand_scrape = await _should_attempt_scrape(article_db_obj)
        current_text_content = article_db_obj.scraped_text_content
        error_parts_for_display = []
        if needs_on_demand_scrape:
            articles_needing_ondemand_scrape.append(article_db_obj)
            error_parts_for_display.append("Content pending fresh scrape.")
        elif current_text_content and current_text_content.startswith(SCRAPING_ERROR_PREFIX):
            error_parts_for_display.append(current_text_content) 
        elif current_text_content and len(current_text_content) < TEXT_LENGTH_THRESHOLD and article_db_obj.full_html_content is not None:
            error_parts_for_display.append("Content previously scraped but found to be very short.")

        if not article_result_data["summary"] and (not current_text_content or not current_text_content.startswith(SCRAPING_ERROR_PREFIX)):
             if not latest_summary_obj or latest_summary_obj.summary_text.startswith("Error:"):
                error_parts_for_display.append("Summary needs generation.")
        
        if not article_db_obj.tags and (not current_text_content or not current_text_content.startswith(SCRAPING_ERROR_PREFIX)):
             error_parts_for_display.append("Tags need generation.")

        if error_parts_for_display:
            article_result_data["error_message"] = " | ".join(list(set(error_parts_for_display))) 

        results_on_page.append(ArticleResult(**article_result_data))

    if articles_needing_ondemand_scrape:
        logger.info(f"API: Found {len(articles_needing_ondemand_scrape)} articles for on-demand scraping on current page.")
        for art_db_obj_to_process in articles_needing_ondemand_scrape:
            logger.info(f"API: On-demand scraping for {art_db_obj_to_process.url[:70]}...")
            scraped_docs_list_od: List[LangchainDocument] = await scraper.scrape_urls([str(art_db_obj_to_process.url)])
            temp_text_content = art_db_obj_to_process.scraped_text_content 
            
            scraper_error_msg_od = None
            if scraped_docs_list_od and scraped_docs_list_od[0]:
                sc_doc_od = scraped_docs_list_od[0]
                scraper_error_msg_od = sc_doc_od.metadata.get("error")
                if not scraper_error_msg_od and sc_doc_od.page_content:
                    art_db_obj_to_process.scraped_text_content = sc_doc_od.page_content
                    art_db_obj_to_process.full_html_content = sc_doc_od.metadata.get('full_html_content')
                    temp_text_content = art_db_obj_to_process.scraped_text_content 
                    if len(temp_text_content or '') < TEXT_LENGTH_THRESHOLD:
                         logger.warning(f"API On-demand: Scrape for Article ID {art_db_obj_to_process.id} yielded short text (length {len(temp_text_content or '')}).")
                else:
                    scraper_error_msg_od = scraper_error_msg_od or "On-demand scraper returned no page_content."
                    art_db_obj_to_process.scraped_text_content = f"{SCRAPING_ERROR_PREFIX} {scraper_error_msg_od}"
                    art_db_obj_to_process.full_html_content = None
                    temp_text_content = art_db_obj_to_process.scraped_text_content
            else:
                scraper_error_msg_od = "On-demand scraping: No document returned."
                art_db_obj_to_process.scraped_text_content = f"{SCRAPING_ERROR_PREFIX} {scraper_error_msg_od}"
                art_db_obj_to_process.full_html_content = None
                temp_text_content = art_db_obj_to_process.scraped_text_content
            
            db.add(art_db_obj_to_process); 
            try: db.commit(); db.refresh(art_db_obj_to_process)
            except Exception as e: db.rollback(); logger.error(f"Error committing on-demand scrape for article {art_db_obj_to_process.id}: {e}", exc_info=True)

            for res_art in results_on_page:
                if res_art.id == art_db_obj_to_process.id:
                    current_error_parts_after_od_scrape = []
                    if art_db_obj_to_process.scraped_text_content and art_db_obj_to_process.scraped_text_content.startswith(SCRAPING_ERROR_PREFIX):
                        current_error_parts_after_od_scrape.append(art_db_obj_to_process.scraped_text_content)
                    elif art_db_obj_to_process.scraped_text_content and len(art_db_obj_to_process.scraped_text_content) < TEXT_LENGTH_THRESHOLD and art_db_obj_to_process.full_html_content is not None:
                        current_error_parts_after_od_scrape.append("Content scraped but found to be very short.")
                    
                    if not res_art.summary and (not temp_text_content or not temp_text_content.startswith(SCRAPING_ERROR_PREFIX)):
                         latest_s = db.query(database.Summary).filter(database.Summary.article_id == res_art.id).order_by(database.Summary.created_at.desc()).first()
                         if not latest_s or latest_s.summary_text.startswith("Error:"): current_error_parts_after_od_scrape.append("Summary needs generation.")
                    
                    if not art_db_obj_to_process.tags and (not temp_text_content or not temp_text_content.startswith(SCRAPING_ERROR_PREFIX)):
                         current_error_parts_after_od_scrape.append("Tags need generation.")
                    
                    res_art.error_message = " | ".join(list(set(current_error_parts_after_od_scrape))) if current_error_parts_after_od_scrape else None
                    can_process_ai_od = temp_text_content and not temp_text_content.startswith(SCRAPING_ERROR_PREFIX) and len(temp_text_content) >= TEXT_LENGTH_THRESHOLD
                    
                    # On-demand AI processing after successful on-demand scrape
                    if llm_summary and can_process_ai_od and ("Summary needs generation." in (res_art.error_message or "")):
                        logger.info(f"API On-demand: Summarizing Article ID {res_art.id} after successful scrape.")
                        lc_doc_for_summary_od = LangchainDocument(page_content=temp_text_content, metadata={"source": art_db_obj_to_process.url, "id": res_art.id})
                        summary_text_od = await summarizer.summarize_document_content(lc_doc_for_summary_od, llm_summary, query.summary_prompt)
                        db.query(database.Summary).filter(database.Summary.article_id == res_art.id).delete(synchronize_session=False)
                        new_summary_db_od = database.Summary(article_id=res_art.id, summary_text=summary_text_od, prompt_used=query.summary_prompt or app_config.DEFAULT_SUMMARY_PROMPT, model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME)
                        db.add(new_summary_db_od); db.commit(); db.refresh(new_summary_db_od)
                        res_art.summary = summary_text_od if not summary_text_od.startswith("Error:") else None
                        if res_art.error_message: res_art.error_message = res_art.error_message.replace("Summary needs generation.", "").replace(" | "," ").strip()
                        if not res_art.error_message: res_art.error_message = None

                    if llm_tag and can_process_ai_od and ("Tags need generation." in (res_art.error_message or "")):
                        logger.info(f"API On-demand: Tagging Article ID {res_art.id} after successful scrape.")
                        tag_names_od = await summarizer.generate_tags_for_text(temp_text_content, llm_tag, query.tag_generation_prompt)
                        if tag_names_od:
                            art_db_obj_to_process.tags.clear(); db.flush() # Use the main DB object for tags
                            for t_name_od in tag_names_od:
                                t_name_clean_od = t_name_od.strip().lower()
                                if not t_name_clean_od: continue
                                tag_db_o_od = db.query(database.Tag).filter(database.Tag.name == t_name_clean_od).first()
                                if not tag_db_o_od: tag_db_o_od = database.Tag(name=t_name_clean_od); db.add(tag_db_o_od); 
                                try: db.flush()
                                except IntegrityError: db.rollback(); tag_db_o_od = db.query(database.Tag).filter(database.Tag.name == t_name_clean_od).first()
                                if tag_db_o_od and tag_db_o_od not in art_db_obj_to_process.tags: art_db_obj_to_process.tags.append(tag_db_o_od)
                            db.commit(); db.refresh(art_db_obj_to_process)
                            res_art.tags = [ArticleTagResponse.from_orm(t) for t in art_db_obj_to_process.tags]
                            if res_art.error_message: res_art.error_message = res_art.error_message.replace("Tags need generation.", "").replace(" | "," ").strip()
                            if not res_art.error_message: res_art.error_message = None
                    break 

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

    return PaginatedSummariesAPIResponse(
        search_source=search_source_display, requested_page=current_page_for_slice,
        page_size=query.page_size, total_articles_available=total_articles_available,
        total_pages=total_pages, processed_articles_on_page=results_on_page
    )

@router.post("/articles/{article_id}/regenerate-summary", response_model=ArticleResult)
async def regenerate_article_summary(
    article_id: int, request_body: RegenerateSummaryRequest, db: SQLAlchemySession = Depends(database.get_db),
    llm_summary: GoogleGenerativeAI = Depends(get_llm_summary), llm_tag: GoogleGenerativeAI = Depends(get_llm_tag)           
):
    if not llm_summary: raise HTTPException(status_code=503, detail="Summarization LLM not available.")
    article_db = db.query(database.Article).options(joinedload(database.Article.tags), joinedload(database.Article.feed_source)).filter(database.Article.id == article_id).first()
    if not article_db: raise HTTPException(status_code=404, detail="Article not found.")
    
    logger.info(f"API Call: Regenerate summary for Article ID {article_id}. Force re-scrape if content is missing/error/short.")
    
    current_text_content = article_db.scraped_text_content
    force_scrape_needed = (
        not current_text_content or 
        current_text_content.startswith(SCRAPING_ERROR_PREFIX) or 
        current_text_content.startswith(CONTENT_ERROR_PREFIX) or 
        (len(current_text_content) < TEXT_LENGTH_THRESHOLD and article_db.full_html_content is not None) or 
        not article_db.full_html_content 
    )

    if force_scrape_needed:
        logger.info(f"API Regenerate: Content for Article ID {article_id} requires re-scraping for regeneration.")
        scraped_docs_list_regen: List[LangchainDocument] = await scraper.scrape_urls([str(article_db.url)])
        scraper_error_msg_regen = None
        if scraped_docs_list_regen and scraped_docs_list_regen[0]:
            sc_doc_regen = scraped_docs_list_regen[0]
            scraper_error_msg_regen = sc_doc_regen.metadata.get("error")
            if not scraper_error_msg_regen and sc_doc_regen.page_content:
                article_db.scraped_text_content = sc_doc_regen.page_content
                article_db.full_html_content = sc_doc_regen.metadata.get('full_html_content')
                current_text_content = article_db.scraped_text_content 
                db.add(article_db); db.commit(); db.refresh(article_db)
                logger.info(f"API Regenerate: Successfully re-scraped content for Article ID {article_id}.")
            else:
                scraper_error_msg_regen = scraper_error_msg_regen or "Failed to re-scrape content (regen)"
                article_db.scraped_text_content = f"{SCRAPING_ERROR_PREFIX} {scraper_error_msg_regen}"; article_db.full_html_content = None;
                current_text_content = article_db.scraped_text_content
                db.add(article_db); db.commit(); db.refresh(article_db) 
                logger.error(f"API Regenerate: Failed to re-scrape for Article ID {article_id}: {scraper_error_msg_regen}")
                raise HTTPException(status_code=500, detail=f"Failed to get valid content for regeneration: {scraper_error_msg_regen}")
        else: # No document returned from scraper
            scraper_error_msg_regen = "Failed to re-scrape: No document returned."
            article_db.scraped_text_content = f"{SCRAPING_ERROR_PREFIX} {scraper_error_msg_regen}"; article_db.full_html_content = None;
            current_text_content = article_db.scraped_text_content
            db.add(article_db); db.commit(); db.refresh(article_db)
            logger.error(f"API Regenerate: Failed to re-scrape for Article ID {article_id}: {scraper_error_msg_regen}")
            raise HTTPException(status_code=500, detail=f"Failed to get valid content for regeneration: {scraper_error_msg_regen}")


    if not current_text_content or current_text_content.startswith(SCRAPING_ERROR_PREFIX) or len(current_text_content) < TEXT_LENGTH_THRESHOLD: 
        logger.error(f"API Regenerate: Article text content for ID {article_id} is still invalid or too short ('{current_text_content[:100]}...') after potential re-scrape attempt.")
        existing_summary_obj = db.query(database.Summary).filter(database.Summary.article_id == article_db.id).order_by(database.Summary.created_at.desc()).first()
        summary_to_return = existing_summary_obj.summary_text if existing_summary_obj else None
        error_msg_response = f"Cannot regenerate summary: article content is invalid or too short ('{current_text_content[:100]}...')."
        return ArticleResult(id=article_db.id, title=article_db.title, url=article_db.url, summary=summary_to_return, publisher=article_db.feed_source.name if article_db.feed_source else article_db.publisher_name, published_date=article_db.published_date, source_feed_url=article_db.feed_source.url if article_db.feed_source else None, tags=[ArticleTagResponse.from_orm(tag) for tag in article_db.tags], error_message=error_msg_response)

    lc_doc_for_summary_regen = LangchainDocument(page_content=current_text_content, metadata={"source": str(article_db.url), "id": article_db.id})
    prompt_to_use = request_body.custom_prompt if request_body.custom_prompt and request_body.custom_prompt.strip() else app_config.DEFAULT_SUMMARY_PROMPT
    new_summary_text = await summarizer.summarize_document_content(lc_doc_for_summary_regen, llm_summary, prompt_to_use)
    db.query(database.Summary).filter(database.Summary.article_id == article_id).delete(synchronize_session=False)
    new_summary_db_obj = database.Summary(article_id=article_id, summary_text=new_summary_text, prompt_used=prompt_to_use, model_used=app_config.DEFAULT_SUMMARY_MODEL_NAME)
    db.add(new_summary_db_obj); db.commit(); db.refresh(new_summary_db_obj) 

    if request_body.regenerate_tags and llm_tag and current_text_content and not current_text_content.startswith(SCRAPING_ERROR_PREFIX) and len(current_text_content) >= TEXT_LENGTH_THRESHOLD :
        logger.info(f"API Regenerate: Regenerating tags for Article ID {article_id}.")
        if article_db.tags: article_db.tags.clear(); db.commit(); db.refresh(article_db)
        
        tag_names_generated = await summarizer.generate_tags_for_text(current_text_content, llm_tag, None) # Using default tag prompt
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
            try: db.commit(); db.refresh(article_db); logger.info(f"API Regenerate: Saved tags for Article ID {article_id}: {tag_names_generated}")
            except Exception as e_commit_tags: db.rollback(); logger.error(f"API Regenerate: Error saving regenerated tags for Article ID {article_id}: {e_commit_tags}", exc_info=True)
    
    db.refresh(article_db)
    return ArticleResult(id=article_db.id, title=article_db.title, url=article_db.url, summary=new_summary_text, publisher=article_db.feed_source.name if article_db.feed_source else article_db.publisher_name, published_date=article_db.published_date, source_feed_url=article_db.feed_source.url if article_db.feed_source else None, tags=[ArticleTagResponse.from_orm(tag) for tag in article_db.tags], error_message=None if not new_summary_text.startswith("Error:") else new_summary_text)

