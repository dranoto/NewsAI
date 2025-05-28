# app/main_api.py
import logging
import asyncio 
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Langchain and LLM related imports
from langchain_google_genai import GoogleGenerativeAI 

# APScheduler imports
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Relative imports for application modules
from . import database 
from . import config as app_config 
from . import summarizer 
from . import rss_client 
from . import tasks 

# Import router modules
from .routers import (
    config_routes,
    feed_routes,
    article_routes,
    chat_routes,
    admin_routes,
    content_routes # Added import for the new content router
)

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Global Variables ---
llm_summary_instance_global: GoogleGenerativeAI | None = None
llm_chat_instance_global: GoogleGenerativeAI | None = None
llm_tag_instance_global: GoogleGenerativeAI | None = None

# APScheduler instance
scheduler = AsyncIOScheduler(timezone="UTC")

# FastAPI application instance
app = FastAPI(
    title="News Summarizer API & Frontend (Refactored)",
    version="2.1.0", # Updated version for new feature
    description="API for fetching, summarizing, tagging, chatting with, and viewing full content of news articles."
)

# --- Application Lifecycle Events (Startup & Shutdown) ---
@app.on_event("startup")
async def startup_event():
    global llm_summary_instance_global, llm_chat_instance_global, llm_tag_instance_global, scheduler
    logger.info("MAIN_API: Application startup sequence initiated...")

    # 1. Initialize Database
    logger.info("MAIN_API: Initializing database tables...")
    try:
        database.create_db_and_tables()
        logger.info("MAIN_API: Database tables checked/created successfully.")
    except Exception as e:
        logger.critical(f"MAIN_API: CRITICAL ERROR during database initialization: {e}", exc_info=True)

    # 2. Add Initial RSS Feeds to DB
    if app_config.RSS_FEED_URLS:
        logger.info(f"MAIN_API: Ensuring initial RSS feeds are in DB from config: {app_config.RSS_FEED_URLS}")
        try:
            with database.db_session_scope() as db:
                 rss_client.add_initial_feeds_to_db(db, app_config.RSS_FEED_URLS)
            logger.info("MAIN_API: Initial RSS feeds processed.")
        except Exception as e:
            logger.error(f"MAIN_API: Error processing initial RSS feeds: {e}", exc_info=True)
    else:
        logger.info("MAIN_API: No initial RSS_FEED_URLS configured in app_config to add to DB.")

    # 3. Initialize LLM Instances and store in app.state
    logger.info("MAIN_API: Attempting to initialize LLM instances...")
    if not app_config.GEMINI_API_KEY:
        logger.critical("MAIN_API: CRITICAL ERROR - GEMINI_API_KEY not found. LLM features will be disabled.")
    else:
        try:
            llm_summary_instance_global = summarizer.initialize_llm(
                api_key=app_config.GEMINI_API_KEY,
                model_name=app_config.DEFAULT_SUMMARY_MODEL_NAME,
                temperature=0.2, max_output_tokens=app_config.SUMMARY_MAX_OUTPUT_TOKENS
            )
            if llm_summary_instance_global:
                app.state.llm_summary_instance = llm_summary_instance_global
                logger.info(f"MAIN_API: Summarization LLM ({app_config.DEFAULT_SUMMARY_MODEL_NAME}) initialized and added to app.state.")
            else: logger.error("MAIN_API: Summarization LLM failed to initialize.")

            llm_chat_instance_global = summarizer.initialize_llm(
                api_key=app_config.GEMINI_API_KEY,
                model_name=app_config.DEFAULT_CHAT_MODEL_NAME,
                temperature=0.5, max_output_tokens=app_config.CHAT_MAX_OUTPUT_TOKENS
            )
            if llm_chat_instance_global:
                app.state.llm_chat_instance = llm_chat_instance_global
                logger.info(f"MAIN_API: Chat LLM ({app_config.DEFAULT_CHAT_MODEL_NAME}) initialized and added to app.state.")
            else: logger.error("MAIN_API: Chat LLM failed to initialize.")

            llm_tag_instance_global = summarizer.initialize_llm(
                api_key=app_config.GEMINI_API_KEY,
                model_name=app_config.DEFAULT_TAG_MODEL_NAME,
                temperature=0.1, max_output_tokens=app_config.TAG_MAX_OUTPUT_TOKENS
            )
            if llm_tag_instance_global:
                app.state.llm_tag_instance = llm_tag_instance_global
                logger.info(f"MAIN_API: Tag Generation LLM ({app_config.DEFAULT_TAG_MODEL_NAME}) initialized and added to app.state.")
            else: logger.error("MAIN_API: Tag Generation LLM failed to initialize.")

        except Exception as e:
            logger.critical(f"MAIN_API: CRITICAL ERROR during LLM Initialization: {e}.", exc_info=True)
            llm_summary_instance_global = None
            llm_chat_instance_global = None
            llm_tag_instance_global = None
            app.state.llm_summary_instance = None
            app.state.llm_chat_instance = None
            app.state.llm_tag_instance = None


    # 4. Start APScheduler for RSS Feed Updates
    if not scheduler.running:
        logger.info(f"MAIN_API: Configuring APScheduler to run RSS feed updates every {app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES} minutes.")
        scheduler.add_job(
            tasks.trigger_rss_update_all_feeds,
            trigger=IntervalTrigger(minutes=app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES),
            id="update_all_feeds_job",
            name="Periodic RSS Feed Update",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=15),
            max_instances=1,
            coalesce=True
        )
        try:
            scheduler.start()
            logger.info("MAIN_API: APScheduler started successfully.")
        except Exception as e:
            logger.error(f"MAIN_API: Failed to start APScheduler: {e}", exc_info=True)
    else:
        logger.info("MAIN_API: APScheduler is already running.")

    logger.info("MAIN_API: Application startup sequence complete.")

@app.on_event("shutdown")
def shutdown_event():
    global scheduler 
    logger.info("MAIN_API: Application shutdown sequence initiated...")
    if scheduler.running:
        logger.info("MAIN_API: Shutting down APScheduler...")
        try:
            scheduler.shutdown()
            logger.info("MAIN_API: APScheduler shut down successfully.")
        except Exception as e:
            logger.error(f"MAIN_API: Error shutting down APScheduler: {e}", exc_info=True)
    logger.info("MAIN_API: Application shutdown sequence complete.")

# --- Include Routers ---
logger.info("MAIN_API: Including API routers...")
app.include_router(config_routes.router)
app.include_router(feed_routes.router)
app.include_router(article_routes.router)
app.include_router(chat_routes.router)
app.include_router(admin_routes.router)
app.include_router(content_routes.router) # Added the new content_routes router
logger.info("MAIN_API: All API routers included.")

# --- Static Files & Root Endpoint ---
try:
    app.mount("/static", StaticFiles(directory="static_frontend"), name="static_frontend_files")
    logger.info("MAIN_API: Static files mounted from 'static_frontend' directory at '/static'.")
except RuntimeError as e:
    logger.error(f"MAIN_API: Error mounting static files. Ensure 'static_frontend' directory exists at the project root. Details: {e}", exc_info=True)

@app.get("/", response_class=FileResponse, include_in_schema=False)
async def serve_index_html():
    index_html_path = "static_frontend/index.html"
    import os
    if not os.path.exists(index_html_path):
        logger.error(f"MAIN_API: index.html not found at '{index_html_path}'. Ensure it exists.")
    return FileResponse(index_html_path)

logger.info("MAIN_API: FastAPI application initialized and configured.")
