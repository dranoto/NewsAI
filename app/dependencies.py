# app/dependencies.py
import logging
from fastapi import Request, HTTPException
from langchain_google_genai import GoogleGenerativeAI # For type hinting

logger = logging.getLogger(__name__)

def get_llm_summary(request: Request) -> GoogleGenerativeAI:
    """
    Dependency function to get the initialized summarization LLM instance
    from the application state (request.app.state).
    Raises HTTPException 503 if the LLM instance is not available.
    """
    if not hasattr(request.app.state, 'llm_summary_instance') or request.app.state.llm_summary_instance is None:
        logger.error("Dependency Error: Summarization LLM (llm_summary_instance) not found in app.state.")
        raise HTTPException(status_code=503, detail="Summarization LLM has not been initialized.")
    return request.app.state.llm_summary_instance

def get_llm_chat(request: Request) -> GoogleGenerativeAI:
    """
    Dependency function to get the initialized chat LLM instance
    from the application state (request.app.state).
    Raises HTTPException 503 if the LLM instance is not available.
    """
    if not hasattr(request.app.state, 'llm_chat_instance') or request.app.state.llm_chat_instance is None:
        logger.error("Dependency Error: Chat LLM (llm_chat_instance) not found in app.state.")
        raise HTTPException(status_code=503, detail="Chat LLM has not been initialized.")
    return request.app.state.llm_chat_instance

def get_llm_tag(request: Request) -> GoogleGenerativeAI:
    """
    Dependency function to get the initialized tag generation LLM instance
    from the application state (request.app.state).
    Raises HTTPException 503 if the LLM instance is not available.
    """
    if not hasattr(request.app.state, 'llm_tag_instance') or request.app.state.llm_tag_instance is None:
        logger.error("Dependency Error: Tag Generation LLM (llm_tag_instance) not found in app.state.")
        raise HTTPException(status_code=503, detail="Tag Generation LLM has not been initialized.")
    return request.app.state.llm_tag_instance
