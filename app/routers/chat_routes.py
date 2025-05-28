# app/routers/chat_routes.py
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as SQLAlchemySession
from typing import List

# Relative imports for modules within the 'app' directory
from .. import database 
from .. import scraper 
from .. import summarizer 
from .. import config as app_config 
from ..schemas import ( 
    ChatHistoryItem,
    ChatQuery,
    ChatResponse
)
# Import dependency function for LLM instance
from ..dependencies import get_llm_chat
from langchain_google_genai import GoogleGenerativeAI # For type hinting LLM instances


# Initialize logger for this module
logger = logging.getLogger(__name__)

# Create an APIRouter instance for these chat-related routes
router = APIRouter(
    prefix="/api",  # Common path prefix
    tags=["chat"]  # For grouping in OpenAPI documentation
)

@router.get("/article/{article_id}/chat-history", response_model=List[ChatHistoryItem])
async def get_article_chat_history(
    article_id: int,
    db: SQLAlchemySession = Depends(database.get_db)
):
    logger.info(f"API Call: Fetching chat history for Article ID: {article_id}")
    db_history_items = db.query(database.ChatHistory)\
        .filter(database.ChatHistory.article_id == article_id)\
        .order_by(database.ChatHistory.timestamp.asc())\
        .all()
    if not db_history_items:
        logger.info(f"No chat history found for Article ID: {article_id}")
        return []
    formatted_history: List[ChatHistoryItem] = []
    for item in db_history_items:
        formatted_history.append(ChatHistoryItem(role="user", content=item.question))
        if item.answer:
            formatted_history.append(ChatHistoryItem(role="ai", content=item.answer))
    logger.info(f"Successfully retrieved {len(formatted_history)} items for chat history of Article ID: {article_id}")
    return formatted_history

@router.post("/chat-with-article", response_model=ChatResponse)
async def chat_with_article_endpoint(
    query: ChatQuery,
    db: SQLAlchemySession = Depends(database.get_db),
    llm_chat: GoogleGenerativeAI = Depends(get_llm_chat) # Injected
):
    if not llm_chat: # Check injected instance
        logger.error("API Error: Chat LLM not available via DI in chat_with_article_endpoint.")
        raise HTTPException(status_code=503, detail="Chat service (LLM) not initialized.")

    logger.info(f"API Call: Chat with Article ID: {query.article_id}. Question: '{query.question[:50]}...'")
    article_db = db.query(database.Article).filter(database.Article.id == query.article_id).first()
    if not article_db:
        logger.warning(f"API Warning: Article ID {query.article_id} not found for chat.")
        raise HTTPException(status_code=404, detail="Article not found in database.")
    if query.chat_history: logger.debug(f"Received chat history with {len(query.chat_history)} turns for Article ID: {query.article_id}")

    article_text_for_chat = article_db.scraped_content or ""
    error_detail_for_chat: str | None = None
    if not article_text_for_chat or article_text_for_chat.startswith("Error:") or article_text_for_chat.startswith("Content Error:"):
        logger.info(f"CHAT API: Article {article_db.id} content ('{article_text_for_chat[:50]}...') requires re-scraping for chat.")
        scraped_docs = await scraper.scrape_urls([str(article_db.url)], app_config.PATH_TO_EXTENSION, app_config.USE_HEADLESS_BROWSER)
        if scraped_docs and scraped_docs[0]:
            doc_item = scraped_docs[0]
            if not doc_item.metadata.get("error") and doc_item.page_content and doc_item.page_content.strip():
                article_text_for_chat = doc_item.page_content; article_db.scraped_content = article_text_for_chat; db.add(article_db)
                try: db.commit(); logger.info(f"CHAT API: Successfully re-scraped and saved content for article {article_db.id}. Length: {len(article_text_for_chat)}")
                except Exception as e_commit: db.rollback(); logger.error(f"CHAT API: Error committing re-scraped content for article {article_db.id}: {e_commit}", exc_info=True); error_detail_for_chat = "Failed to save re-scraped content."; article_text_for_chat = ""
            else: error_detail_for_chat = doc_item.metadata.get("error", "Re-scraped content was empty or had an error."); article_text_for_chat = ""
        else: error_detail_for_chat = "Failed to re-scrape article for chat (no document returned)."; article_text_for_chat = ""
        if error_detail_for_chat: logger.warning(f"CHAT API: Error on re-scrape for Article {article_db.id}: {error_detail_for_chat}")

    answer = await summarizer.get_chat_response(
        llm_instance=llm_chat, # Use injected llm_chat
        article_text=article_text_for_chat,
        question=query.question,
        chat_history=query.chat_history,
        custom_chat_prompt_str=query.chat_prompt
    )
    logger.debug(f"CHAT API: LLM Answer for article {article_db.id} (first 100 chars): '{answer[:100]}'") # ADDED LOGGING

    final_error_message_for_response = error_detail_for_chat
    is_llm_error = answer.startswith("Error getting answer from AI:") or answer == "AI returned an empty answer."
    logger.debug(f"CHAT API: Determined is_llm_error: {is_llm_error} for article {article_db.id}") # ADDED LOGGING

    if is_llm_error:
        current_llm_error = answer
        if final_error_message_for_response: final_error_message_for_response = f"{final_error_message_for_response} | LLM: {current_llm_error}"
        else: final_error_message_for_response = f"LLM: {current_llm_error}"
    
    if not is_llm_error:
        logger.info(f"CHAT API: Attempting to save chat turn for article {article_db.id} as no LLM error detected.") # ADDED LOGGING
        try:
            new_chat_item_db = database.ChatHistory(
                article_id=article_db.id,
                question=query.question,
                answer=answer, # Store the actual answer from AI
                prompt_used=query.chat_prompt or app_config.DEFAULT_CHAT_PROMPT,
                model_used=app_config.DEFAULT_CHAT_MODEL_NAME
            )
            db.add(new_chat_item_db)
            logger.debug(f"CHAT API: ChatHistory object created for article {article_db.id}, attempting commit.") # ADDED LOGGING
            db.commit()
            db.refresh(new_chat_item_db) # Refresh to get DB-generated values like ID and timestamp
            logger.info(f"CHAT API: Successfully saved new chat turn (ID {new_chat_item_db.id}, Timestamp: {new_chat_item_db.timestamp}) for article {article_db.id}") # MODIFIED LOGGING
        except Exception as e_save_chat:
            db.rollback()
            logger.error(f"CHAT API: Error saving new chat turn to DB for article {article_db.id}: {e_save_chat}", exc_info=True)
            db_save_error = "Failed to save chat turn to database."
            if final_error_message_for_response: final_error_message_for_response = f"{final_error_message_for_response} | DB: {db_save_error}"
            else: final_error_message_for_response = f"DB: {db_save_error}"
    else:
        logger.warning(f"CHAT API: Skipping save of chat turn for article {article_db.id} due to is_llm_error being True.") # ADDED LOGGING
    
    logger.info(f"CHAT API: Sending response for article {article_db.id}. Answer starts: '{answer[:60]}...'. Error: {final_error_message_for_response}")
    return ChatResponse(article_id=article_db.id, question=query.question, answer=answer, error_message=final_error_message_for_response)
