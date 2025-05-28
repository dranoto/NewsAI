# app/routers/admin_routes.py
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as SQLAlchemySession
from datetime import datetime, timezone, timedelta

# Relative imports for modules within the 'app' directory
from .. import database # For get_db and ORM models (Article)

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Create an APIRouter instance for these admin-related routes
router = APIRouter(
    prefix="/api/admin",  # Common path prefix for admin routes
    tags=["administration"]  # For grouping in OpenAPI documentation
)

@router.delete("/cleanup-old-data", status_code=200)
async def cleanup_old_data_endpoint(
    days_old: int = Query(30, ge=1, description="Minimum age in days for articles to be deleted."),
    db: SQLAlchemySession = Depends(database.get_db)
):
    """
    Deletes articles (and their related summaries, chat history, and tag associations
    via database cascade rules) that were published more than a specified number of days ago.
    """
    if days_old <= 0:
        logger.error(f"Validation Error: days_old parameter must be positive, received {days_old}.")
        # Although Query(ge=1) should handle this, an explicit check is good practice.
        raise HTTPException(status_code=400, detail="days_old parameter must be a positive integer.")

    # Calculate the cutoff date for deletion. Articles published before this date will be deleted.
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)
    logger.info(f"API Call: Admin request to delete data older than {days_old} days (i.e., published before {cutoff_date.strftime('%Y-%m-%d %H:%M:%S %Z')}).")

    # Find articles that meet the deletion criteria
    # We only need their IDs for targeted deletion if we weren't relying on cascade,
    # but for counting and logging, fetching them (or just their count) is useful.
    articles_to_delete_query = db.query(database.Article).filter(database.Article.published_date < cutoff_date)
    
    # Get a list of IDs for logging or more complex scenarios (not strictly needed if just deleting)
    # For large datasets, directly counting and then deleting without fetching all objects is more efficient.
    # article_ids_to_delete = [article.id for article in articles_to_delete_query.all()]
    # article_deleted_count = len(article_ids_to_delete)

    # More efficient way to count before deleting for large datasets:
    article_deleted_count = articles_to_delete_query.count()

    if article_deleted_count > 0:
        logger.info(f"Found {article_deleted_count} articles to delete.")
        # Perform the deletion.
        # The `delete(synchronize_session=False)` is generally efficient.
        # SQLAlchemy's ORM relationships with `cascade="all, delete-orphan"` on the Article model
        # will handle the deletion of related Summary, ChatHistory, and article_tag_association records.
        articles_to_delete_query.delete(synchronize_session=False)
        
        try:
            db.commit()
            logger.info(f"Successfully deleted {article_deleted_count} old article records and their related data (via cascade).")
        except Exception as e:
            db.rollback()
            logger.error(f"Error during commit after deleting old articles: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to commit deletions: {str(e)}")
    else:
        logger.info("No old articles found to delete based on the specified criteria.")

    return {"message": f"Cleanup process completed. Deleted {article_deleted_count} articles (and related data) older than {days_old} days."}
