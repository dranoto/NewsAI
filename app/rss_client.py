# app/rss_client.py
import feedparser
import asyncio
from datetime import datetime, timezone
from . import config # To get MAX_ARTICLES_PER_INDIVIDUAL_FEED

async def _parse_feed_in_thread(feed_url: str):
    """Helper to run blocking feedparser.parse in a thread for asyncio compatibility."""
    loop = asyncio.get_event_loop()
    try:
        print(f"Attempting to parse feed (in thread): {feed_url}")
        # feedparser.parse is a blocking (synchronous) I/O operation
        parsed_data = await loop.run_in_executor(None, feedparser.parse, feed_url)
        print(f"Finished parsing feed (in thread): {feed_url}")
        return parsed_data
    except Exception as e:
        print(f"Exception during feedparser.parse for {feed_url}: {e}")
        return None

async def fetch_all_articles_from_configured_feeds(feed_urls: list[str]) -> list[dict]:
    """
    Fetches all available articles (up to MAX_ARTICLES_PER_INDIVIDUAL_FEED from each)
    from a list of configured RSS feed URLs.
    Returns a list of article metadata dictionaries, sorted by published date if possible.
    """
    all_articles_metadata = []
    if not feed_urls:
        print("No RSS feed URLs provided to fetch_all_articles_from_configured_feeds.")
        return []

    print(f"Fetching initial article pool from {len(feed_urls)} provided RSS feed(s)...")

    feed_parse_tasks = [_parse_feed_in_thread(url) for url in feed_urls]
    parsed_feeds_results = await asyncio.gather(*feed_parse_tasks, return_exceptions=True)

    for i, feed_data_or_exc in enumerate(parsed_feeds_results):
        current_feed_url = feed_urls[i]
        if isinstance(feed_data_or_exc, Exception):
            print(f"Error fetching/parsing feed {current_feed_url}: {feed_data_or_exc}")
            continue
        
        feed_data = feed_data_or_exc
        if feed_data is None:
            print(f"Parsing returned None for feed {current_feed_url}.")
            continue
        
        if not hasattr(feed_data, 'feed') or not hasattr(feed_data, 'entries'):
            print(f"Parsed data for {current_feed_url} is not a valid feed structure.")
            continue

        feed_title = feed_data.feed.get('title', current_feed_url.split('/')[2])
        print(f"Processing feed: '{feed_title}' ({len(feed_data.entries)} entries found)")
        
        articles_from_this_feed_count = 0
        for entry in feed_data.entries:
            # We fetch up to MAX_ARTICLES_PER_INDIVIDUAL_FEED to build a large cache.
            # The actual number of articles per page is handled by main_api.py.
            if articles_from_this_feed_count >= config.MAX_ARTICLES_PER_INDIVIDUAL_FEED:
                break 

            title = entry.get("title")
            link_to_full_article = entry.get("link")
            published_date_str = None
            if entry.get("published_parsed"):
                try:
                    dt_obj = datetime(*entry.published_parsed[:6]).replace(tzinfo=timezone.utc)
                    published_date_str = dt_obj.isoformat()
                except Exception:
                    published_date_str = entry.get("published", entry.get("updated"))
            else:
                published_date_str = entry.get("published", entry.get("updated"))
            
            if title and link_to_full_article:
                all_articles_metadata.append({
                    "title": title,
                    "url": link_to_full_article,
                    "publisher": feed_title, 
                    "published date": published_date_str,
                })
                articles_from_this_feed_count += 1
    
    # Sort all collected articles by date (most recent first)
    # This requires consistent and parsable dates. Add error handling if dates are messy.
    def get_sort_key(article_dict):
        date_str = article_dict.get('published date')
        if not date_str:
            return datetime.min.replace(tzinfo=timezone.utc) # Oldest possible date for items without date
        try:
            # Handle 'Z' for UTC explicitly if fromisoformat has issues with it directly
            if date_str.endswith('Z'):
                date_str = date_str[:-1] + '+00:00'
            return datetime.fromisoformat(date_str)
        except ValueError:
            print(f"Warning: Could not parse date '{date_str}' for sorting. Using fallback date.")
            return datetime.min.replace(tzinfo=timezone.utc) # Fallback for unparseable dates

    all_articles_metadata.sort(key=get_sort_key, reverse=True)

    print(f"Fetched a total pool of {len(all_articles_metadata)} article metadata entries from all RSS feeds.")
    return all_articles_metadata
