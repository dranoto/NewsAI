# app/routers/config_routes.py
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as SQLAlchemySession
from typing import List, Dict, Any # For type hinting

# Relative imports for modules within the 'app' directory
from .. import database # To access get_db and ORM models like RSSFeedSource
from .. import config as app_config # To access application-level configurations
from ..schemas import InitialConfigResponse # To use the Pydantic model for the response

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Create an APIRouter instance for these configuration-related routes
# - prefix: a common path prefix for all routes defined in this router
# - tags: used for grouping routes in the OpenAPI documentation (Swagger UI)
router = APIRouter(
    prefix="/api",
    tags=["configuration"]
)

@router.get("/initial-config", response_model=InitialConfigResponse)
async def get_initial_config_endpoint(db: SQLAlchemySession = Depends(database.get_db)):
    """
    Endpoint to fetch the initial configuration for the frontend.
    This includes default RSS feeds, all feed sources from the database,
    default application settings like articles per page, prompts, and
    details about the browser extension and headless mode.
    """
    logger.info("API Call: Fetching initial configuration.")

    # Query the database for all RSSFeedSource records, ordered by name
    db_feeds = db.query(database.RSSFeedSource).order_by(database.RSSFeedSource.name).all()

    # Format the database feed sources into the structure expected by the frontend/Pydantic model
    db_feed_sources_response: List[Dict[str, Any]] = [
        {"id": feed.id, "url": feed.url, "name": feed.name, "fetch_interval_minutes": feed.fetch_interval_minutes}
        for feed in db_feeds
    ]
    logger.debug(f"Found {len(db_feed_sources_response)} feed sources in the database.")

    # Construct and return the InitialConfigResponse object
    # This uses values from the application's configuration (app_config)
    # and the data retrieved from the database.
    response_data = InitialConfigResponse(
        default_rss_feeds=app_config.RSS_FEED_URLS,
        all_db_feed_sources=db_feed_sources_response,
        default_articles_per_page=app_config.DEFAULT_PAGE_SIZE,
        default_summary_prompt=app_config.DEFAULT_SUMMARY_PROMPT,
        default_chat_prompt=app_config.DEFAULT_CHAT_PROMPT,
        default_tag_generation_prompt=app_config.DEFAULT_TAG_GENERATION_PROMPT,
        default_rss_fetch_interval_minutes=app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES,
        path_to_extension=app_config.PATH_TO_EXTENSION,
        use_headless_browser=app_config.USE_HEADLESS_BROWSER
    )
    logger.info("Successfully prepared initial configuration response.")
    return response_data
