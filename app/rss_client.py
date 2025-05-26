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

        feed_title = feed_data.feed.get('title', current_feed_url.split('/')[2]) # Use domain as fallback for publisher
        print(f"Processing feed: '{feed_title}' ({len(feed_data.entries)} entries found) from URL: {current_feed_url}")
        
        articles_from_this_feed_count = 0
        for entry in feed_data.entries:
            # We fetch up to MAX_ARTICLES_PER_INDIVIDUAL_FEED to build a large cache.
            # The actual number of articles per page is handled by main_api.py.
            if articles_from_this_feed_count >= config.MAX_ARTICLES_PER_INDIVIDUAL_FEED:
                print(f"Reached MAX_ARTICLES_PER_INDIVIDUAL_FEED ({config.MAX_ARTICLES_PER_INDIVIDUAL_FEED}) for {feed_title}. Moving to next feed.")
                break 

            title = entry.get("title")
            link_to_full_article = entry.get("link")
            published_date_str = None
            if entry.get("published_parsed"):
                try:
                    # Ensure all 6 elements for datetime are present, otherwise pad with 0 (e.g. for seconds if missing)
                    # struct_time can have 9 elements, we only need the first 6 for datetime constructor
                    dt_tuple = entry.published_parsed[:6]
                    # Ensure we have all 6 components (year, month, day, hour, minute, second)
                    # Some feeds might not provide all, especially seconds.
                    if len(dt_tuple) < 6:
                         # Pad with 0 for missing time components (e.g., seconds)
                        dt_tuple = list(dt_tuple) + [0] * (6 - len(dt_tuple))
                    dt_obj = datetime(*dt_tuple).replace(tzinfo=timezone.utc) # type: ignore
                    published_date_str = dt_obj.isoformat()
                except Exception as e:
                    print(f"Warning: Could not parse 'published_parsed' for entry in {feed_title}. Fallback. Error: {e}. Data: {entry.published_parsed}")
                    published_date_str = entry.get("published", entry.get("updated")) # Fallback to raw string
            else:
                published_date_str = entry.get("published", entry.get("updated")) # Fallback to raw string
            
            if title and link_to_full_article:
                all_articles_metadata.append({
                    "title": title,
                    "url": link_to_full_article,
                    "publisher": feed_title, # This is the feed's title (e.g., "New York Times")
                    "published date": published_date_str,
                    "source_feed_url": current_feed_url # Store the actual URL of the feed
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
            # Also handle cases where timezone might be +0000 or other offsets
            # A more robust parser might be needed for very diverse feed date formats
            if date_str.endswith('Z'):
                parsed_date = datetime.fromisoformat(date_str[:-1] + '+00:00')
            elif '+' in date_str or (date_str.count('-') >= 2 and 'T' in date_str and date_str.count(':') >=2 ): # Attempt ISO format
                 parsed_date = datetime.fromisoformat(date_str)
                 if parsed_date.tzinfo is None: # If no timezone, assume UTC as per original logic
                     parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            else: # Fallback for less standard formats, try feedparser's own parsing if available or a default
                # This part is tricky as feedparser already tried. If it's not ISO, it's likely problematic.
                # For simplicity, if not ISO, we might treat it as less reliable for sorting or use a very old date.
                # However, the previous logic already tried to make it ISO.
                # If it's still not parseable by fromisoformat, it's likely a malformed string.
                print(f"Warning: Date '{date_str}' is not in a recognized ISO format for sorting. Using fallback.")
                return datetime.min.replace(tzinfo=timezone.utc)

            return parsed_date
        except ValueError as ve:
            print(f"Warning: Could not parse date '{date_str}' for sorting. Error: {ve}. Using fallback date.")
            # Try to parse with common non-ISO formats if really needed, or stick to fallback
            # Example: datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %Z') - but this is risky
            return datetime.min.replace(tzinfo=timezone.utc) # Fallback for unparseable dates

    all_articles_metadata.sort(key=get_sort_key, reverse=True)

    print(f"Fetched a total pool of {len(all_articles_metadata)} article metadata entries from all RSS feeds, sorted by date.")
    return all_articles_metadata
