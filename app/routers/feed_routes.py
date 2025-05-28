# app/routers/feed_routes.py
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy.exc import IntegrityError
from typing import List

# Relative imports for modules within the 'app' directory
from .. import database # To access get_db and ORM models like RSSFeedSource
from .. import config as app_config # To access application-level configurations
from ..schemas import FeedSourceResponse, AddFeedRequest, UpdateFeedRequest # Pydantic models
# Assuming trigger_rss_update_all_feeds will be moved to a tasks.py or similar
# For now, we'll prepare for its import. If it's directly from main_api, adjustments might be needed.
from .. import tasks # Placeholder for where trigger_rss_update_all_feeds might live

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Create an APIRouter instance for these feed-related routes
router = APIRouter(
    prefix="/api",  # Common path prefix
    tags=["feeds"]  # For grouping in OpenAPI documentation
)

@router.post("/feeds", response_model=FeedSourceResponse, status_code=201)
async def add_new_feed_source(
    feed_request: AddFeedRequest,
    db: SQLAlchemySession = Depends(database.get_db)
):
    """
    Adds a new RSS feed source to the database.
    Validates that the feed URL does not already exist.
    """
    logger.info(f"API Call: Attempting to add new feed source with URL: {feed_request.url}")
    # Check if feed URL already exists
    existing_feed = db.query(database.RSSFeedSource).filter(database.RSSFeedSource.url == str(feed_request.url)).first()
    if existing_feed:
        logger.warning(f"Conflict: Feed URL {feed_request.url} already exists in the database.")
        raise HTTPException(status_code=409, detail="Feed URL already exists in the database.")

    # Determine the name for the feed if not provided
    feed_name = feed_request.name
    if not feed_name:
        try:
            # Attempt to derive a name from the URL (e.g., domain name)
            feed_name = str(feed_request.url).split('/')[2].replace("www.","")
        except IndexError:
            # Fallback if URL parsing fails (should be rare with HttpUrl validation)
            feed_name = str(feed_request.url)
    
    # Create new RSSFeedSource ORM object
    new_feed = database.RSSFeedSource(
        url=str(feed_request.url),  # Convert HttpUrl to string for DB
        name=feed_name,
        fetch_interval_minutes=feed_request.fetch_interval_minutes or app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES
    )
    db.add(new_feed)
    try:
        db.commit()
        db.refresh(new_feed)
        logger.info(f"Successfully added new feed source: ID {new_feed.id}, URL {new_feed.url}")
        return new_feed
    except IntegrityError:  # Should be caught by the check above, but as a safeguard
        db.rollback()
        logger.error(f"Database IntegrityError while adding feed {feed_request.url}. This might indicate a race condition.")
        raise HTTPException(status_code=409, detail="Feed URL already exists (IntegrityError).")
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error adding feed {feed_request.url}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not add feed: {str(e)}")

@router.get("/feeds", response_model=List[FeedSourceResponse])
async def get_all_feed_sources(db: SQLAlchemySession = Depends(database.get_db)):
    """
    Retrieves all RSS feed sources from the database, ordered by name.
    """
    logger.info("API Call: Fetching all feed sources.")
    feeds = db.query(database.RSSFeedSource).order_by(database.RSSFeedSource.name).all()
    logger.debug(f"Retrieved {len(feeds)} feed sources from the database.")
    return feeds

@router.put("/feeds/{feed_id}", response_model=FeedSourceResponse)
async def update_feed_source_settings(
    feed_id: int,
    feed_update: UpdateFeedRequest,
    db: SQLAlchemySession = Depends(database.get_db)
):
    """
    Updates the settings (name and/or fetch interval) for an existing RSS feed source.
    """
    logger.info(f"API Call: Attempting to update feed source ID: {feed_id}")
    feed_db = db.query(database.RSSFeedSource).filter(database.RSSFeedSource.id == feed_id).first()
    if not feed_db:
        logger.warning(f"Not Found: Feed source with ID {feed_id} not found for update.")
        raise HTTPException(status_code=404, detail="Feed source not found.")

    updated_fields = False
    if feed_update.name is not None:
        feed_db.name = feed_update.name
        updated_fields = True
        logger.debug(f"Updating name for feed ID {feed_id} to '{feed_update.name}'")
    if feed_update.fetch_interval_minutes is not None:
        if feed_update.fetch_interval_minutes > 0:
            feed_db.fetch_interval_minutes = feed_update.fetch_interval_minutes
            updated_fields = True
            logger.debug(f"Updating fetch interval for feed ID {feed_id} to {feed_update.fetch_interval_minutes} minutes")
        else:
            logger.error(f"Validation Error: Fetch interval for feed ID {feed_id} must be positive, received {feed_update.fetch_interval_minutes}.")
            raise HTTPException(status_code=400, detail="Fetch interval must be positive.")

    if updated_fields:
        try:
            db.add(feed_db) # Add to session, though it's already tracked
            db.commit()
            db.refresh(feed_db)
            logger.info(f"Successfully updated feed source ID {feed_id}.")
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating feed source ID {feed_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Could not update feed settings: {str(e)}")
    else:
        logger.info(f"No changes requested for feed source ID {feed_id}.")
        
    return feed_db

@router.delete("/feeds/{feed_id}", status_code=204)
async def delete_feed_source(feed_id: int, db: SQLAlchemySession = Depends(database.get_db)):
    """
    Deletes an RSS feed source and its related data (articles, summaries, etc.)
    due to database cascade rules.
    """
    logger.info(f"API Call: Attempting to delete feed source ID: {feed_id}")
    feed_db = db.query(database.RSSFeedSource).filter(database.RSSFeedSource.id == feed_id).first()
    if not feed_db:
        logger.warning(f"Not Found: Feed source with ID {feed_id} not found for deletion.")
        raise HTTPException(status_code=404, detail="Feed source not found.")

    try:
        db.delete(feed_db)
        db.commit()
        logger.info(f"Successfully deleted feed source ID {feed_id} and its related data (via cascade).")
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting feed source ID {feed_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not delete feed source: {str(e)}")
    
    return None # For 204 No Content response

@router.post("/trigger-rss-refresh", status_code=202)
async def manual_trigger_rss_refresh(background_tasks: BackgroundTasks):
    """
    Manually triggers the background task to refresh all subscribed RSS feeds.
    """
    logger.info("API Call: Manual RSS refresh triggered via endpoint.")
    # The `trigger_rss_update_all_feeds` task (including lock management and DB operations)
    # is assumed to be defined in `app.tasks` and imported.
    try:
        background_tasks.add_task(tasks.trigger_rss_update_all_feeds)
        logger.info("RSS feed refresh process has been successfully scheduled in the background.")
        return {"message": "RSS feed refresh process has been initiated in the background."}
    except AttributeError:
        logger.critical("Configuration Error: 'tasks.trigger_rss_update_all_feeds' not found. Ensure it's defined in app/tasks.py and imported correctly.")
        raise HTTPException(status_code=500, detail="RSS refresh task is not configured correctly on the server.")
    except Exception as e:
        logger.error(f"Error scheduling manual RSS refresh: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not schedule RSS refresh: {str(e)}")
