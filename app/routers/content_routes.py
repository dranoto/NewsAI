# app/routers/content_routes.py
import logging
import bleach # For HTML sanitization
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session as SQLAlchemySession

# Relative imports for modules within the 'app' directory
from .. import database # For get_db and ORM models (Article)
from ..schemas import SanitizedArticleContentResponse # Pydantic model for the response

# Initialize logger for this module
logger = logging.getLogger(__name__)

# Create an APIRouter instance for these content-related routes
router = APIRouter(
    prefix="/api/articles",  # Common path prefix, similar to other article-related actions
    tags=["article content"]  # For grouping in OpenAPI documentation
)

# --- Bleach Configuration ---
ALLOWED_TAGS = [
    'p', 'br', 'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'del',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'dd', 'dt',
    'a', 
    'img', 
    'blockquote', 'code', 'pre',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'figure', 'figcaption',
    # Consider 'span', 'div' carefully if needed for structure from Readability output
]

ALLOWED_ATTRIBUTES = {
    # Allow class, id, style on any allowed tag.
    # Be cautious with 'style' as bleach won't validate individual CSS properties within it.
    # If you want to be stricter, remove 'style' here or from specific tags.
    '*': ['class', 'id', 'style'], 
    'a': ['href', 'title', 'target', 'rel'], # Added 'rel' for common use (e.g., "noopener noreferrer")
    'img': ['src', 'alt', 'title', 'width', 'height', 'style'],
    'table': ['summary'],
    'td': ['colspan', 'rowspan', 'align', 'valign'],
    'th': ['colspan', 'rowspan', 'align', 'valign', 'scope'],
}

# This list becomes unused with modern bleach.clean() not taking a 'styles' argument.
# If you need to validate individual CSS properties within a style attribute,
# you would need a custom filter or a different approach.
# ALLOWED_STYLES = [
#     'color', 'background-color', 'font-weight', 'font-style', 
#     'text-decoration', 'text-align', 'float', 'margin', 'padding',
#     'width', 'height', 'max-width', 'list-style-type',
# ]

def sanitize_html_content(html_content: str) -> str:
    """
    Sanitizes HTML content using bleach to prevent XSS and remove unwanted tags/attributes.
    """
    if not html_content:
        return ""

    safe_protocols = ['http', 'https', 'mailto', 'ftp'] 

    # REMOVED 'styles=ALLOWED_STYLES' argument as it's not supported in newer bleach versions.
    # Inline styles are now controlled by whether the 'style' attribute is in ALLOWED_ATTRIBUTES.
    cleaned_html = bleach.clean(
        html_content,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        # styles=ALLOWED_STYLES, # This line was removed
        protocols=safe_protocols, 
        strip=True, 
        strip_comments=True
    )
    
    logger.debug(f"Sanitized HTML. Original length: {len(html_content)}, Cleaned length: {len(cleaned_html)}")
    return cleaned_html


@router.get("/{article_id}/content", response_model=SanitizedArticleContentResponse)
async def get_sanitized_article_content(
    article_id: int = Path(..., title="The ID of the article to retrieve content for", ge=1),
    db: SQLAlchemySession = Depends(database.get_db)
):
    """
    Retrieves the full HTML content of an article by its ID,
    sanitizes it using bleach, and returns the sanitized HTML.
    """
    logger.info(f"API Call: Get sanitized content for Article ID: {article_id}")
    article_db = db.query(database.Article).filter(database.Article.id == article_id).first()

    if not article_db:
        logger.warning(f"API Warning: Article ID {article_id} not found when trying to get content.")
        raise HTTPException(status_code=404, detail="Article not found.")

    if not article_db.full_html_content:
        logger.info(f"API Info: Article ID {article_id} has no full_html_content stored.")
        return SanitizedArticleContentResponse(
            article_id=article_db.id,
            original_url=article_db.url,
            title=article_db.title,
            sanitized_html_content=None, 
            error_message="Full HTML content not found for this article in the database."
        )

    try:
        sanitized_content = sanitize_html_content(article_db.full_html_content)
    except Exception as e:
        logger.error(f"API Error: Failed to sanitize HTML content for Article ID {article_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process article content: {str(e)}")

    return SanitizedArticleContentResponse(
        article_id=article_db.id,
        original_url=article_db.url,
        title=article_db.title,
        sanitized_html_content=sanitized_content
    )
