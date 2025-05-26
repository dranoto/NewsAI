# app/rss_client.py
import feedparser
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from typing import Any, Optional 

from . import config as app_config 
from .database import RSSFeedSource, Article 

async def _parse_feed_in_thread(feed_url: str):
    loop = asyncio.get_event_loop()
    try:
        parsed_data = await loop.run_in_executor(None, feedparser.parse, feed_url)
        return parsed_data
    except Exception as e:
        print(f"RSS_CLIENT: Exception during feedparser.parse for {feed_url}: {e}")
        return None

def _normalize_datetime(dt_input: Any) -> Optional[datetime]:
    if not dt_input:
        return None
    
    parsed_date = None
    if isinstance(dt_input, datetime): # If it's already a datetime object
        if dt_input.tzinfo is None: # If naive
            return dt_input.replace(tzinfo=timezone.utc) # Assume UTC
        return dt_input # Already aware

    if isinstance(dt_input, tuple): 
        try:
            dt_tuple_list = list(dt_input[:6]) 
            while len(dt_tuple_list) < 6:
                dt_tuple_list.append(0) 
            if not (1 <= dt_tuple_list[1] <= 12 and 1 <= dt_tuple_list[2] <= 31):
                 pass 
            parsed_date = datetime(*dt_tuple_list, tzinfo=timezone.utc) 
        except (TypeError, ValueError): 
            pass
            
    if not parsed_date and isinstance(dt_input, str):
        try:
            if dt_input.endswith('Z'):
                parsed_date = datetime.fromisoformat(dt_input[:-1] + '+00:00')
            else:
                parsed_date = datetime.fromisoformat(dt_input)
            
            if parsed_date.tzinfo is None: 
                parsed_date = parsed_date.replace(tzinfo=timezone.utc)
            return parsed_date
        except ValueError:
            pass 

    if not parsed_date:
        return None
    return parsed_date


async def fetch_and_store_articles_from_feed(db: Session, feed_source: RSSFeedSource):
    print(f"RSS_CLIENT: Fetching articles for: {feed_source.url} (Name: {feed_source.name})")
    feed_data = await _parse_feed_in_thread(feed_source.url)

    current_time_utc = datetime.now(timezone.utc) # For updating last_fetched_at

    if feed_data is None or not hasattr(feed_data, 'feed') or not hasattr(feed_data, 'entries'):
        print(f"RSS_CLIENT: Failed to parse or invalid feed structure for {feed_source.url}")
        feed_source.last_fetched_at = current_time_utc
        db.add(feed_source)
        return 0

    feed_title_from_rss = feed_data.feed.get('title', feed_source.url.split('/')[2] if len(feed_source.url.split('/')) > 2 else feed_source.url)
    if not feed_source.name and feed_title_from_rss: 
        feed_source.name = feed_title_from_rss
        db.add(feed_source)

    new_articles_count = 0
    processed_in_batch = 0

    for entry in feed_data.entries:
        if processed_in_batch >= app_config.MAX_ARTICLES_PER_INDIVIDUAL_FEED:
            break

        article_url = entry.get("link")
        if not article_url:
            continue
        
        processed_in_batch +=1

        existing_article = db.query(Article).filter(Article.url == article_url).first()
        if existing_article:
            continue 

        title = entry.get("title")
        
        published_date_raw = entry.get("published_parsed", entry.get("published", entry.get("updated")))
        published_date_dt = _normalize_datetime(published_date_raw)

        if not title or not published_date_dt:
            continue
            
        try:
            new_article = Article(
                feed_source_id=feed_source.id,
                url=article_url,
                title=title,
                publisher_name=feed_source.name or feed_title_from_rss, 
                published_date=published_date_dt, # Should be aware datetime
            )
            db.add(new_article)
            new_articles_count += 1
        except IntegrityError: 
            db.rollback()
            print(f"RSS_CLIENT: IntegrityError, likely duplicate URL not caught by pre-check: {article_url}")
        except Exception as e:
            db.rollback()
            print(f"RSS_CLIENT: Error adding article {article_url} to DB: {e}")

    feed_source.last_fetched_at = current_time_utc
    db.add(feed_source)
    print(f"RSS_CLIENT: Finished processing feed {feed_source.name}. Added {new_articles_count} new articles.")
    return new_articles_count


async def update_all_subscribed_feeds(db: Session):
    print("RSS_CLIENT_SCHEDULER: Starting update for all subscribed feeds...")
    now_aware = datetime.now(timezone.utc) # Ensure 'now' is offset-aware
    
    feeds_to_update = []
    all_feeds = db.query(RSSFeedSource).all()
    for feed in all_feeds:
        should_fetch = False
        if feed.last_fetched_at is None:
            should_fetch = True
            print(f"RSS_CLIENT_SCHEDULER: Feed '{feed.name}' (ID: {feed.id}) never fetched. Adding to update queue.")
        else:
            # Ensure feed.last_fetched_at is offset-aware before comparison
            last_fetched_aware = feed.last_fetched_at
            if last_fetched_aware.tzinfo is None:
                # This case should ideally not happen if timezone=True is working correctly for DateTime column
                # and all writes use timezone-aware datetimes.
                print(f"RSS_CLIENT_SCHEDULER: Warning - Feed '{feed.name}' (ID: {feed.id}) has an offset-naive last_fetched_at. Assuming UTC.")
                last_fetched_aware = last_fetched_aware.replace(tzinfo=timezone.utc)
            
            fetch_time_cutoff = now_aware - timedelta(minutes=feed.fetch_interval_minutes)
            if last_fetched_aware < fetch_time_cutoff:
                should_fetch = True
                print(f"RSS_CLIENT_SCHEDULER: Feed '{feed.name}' (ID: {feed.id}) due for update. Last fetched: {last_fetched_aware}, Cutoff: {fetch_time_cutoff}. Adding to queue.")
        
        if should_fetch:
            feeds_to_update.append(feed)

    if not feeds_to_update:
        print("RSS_CLIENT_SCHEDULER: No feeds currently due for update.")
        return

    print(f"RSS_CLIENT_SCHEDULER: Found {len(feeds_to_update)} feeds to update.")
    total_new_articles = 0
    for feed_source in feeds_to_update:
        try:
            count = await fetch_and_store_articles_from_feed(db, feed_source)
            total_new_articles += count
        except Exception as e:
            print(f"RSS_CLIENT_SCHEDULER: Error processing feed {feed_source.url}: {e}")
            # Ensure last_fetched_at is updated even on error to prevent immediate retry loop for this feed
            try:
                feed_source_to_update_on_error = db.query(RSSFeedSource).filter(RSSFeedSource.id == feed_source.id).first()
                if feed_source_to_update_on_error:
                    feed_source_to_update_on_error.last_fetched_at = datetime.now(timezone.utc) 
                    db.add(feed_source_to_update_on_error)
                    # The overall commit is handled by the session scope in the calling function (trigger_rss_update_all_feeds)
            except Exception as e_update_ts:
                 print(f"RSS_CLIENT_SCHEDULER: Critical error updating timestamp for errored feed {feed_source.url}: {e_update_ts}")


    print(f"RSS_CLIENT_SCHEDULER: Finished feed update cycle. Added {total_new_articles} new articles in total.")

def add_initial_feeds_to_db(db: Session, feed_urls: list[str]):
    # ... (This function remains the same, ensure it sets fetch_interval_minutes) ...
    print(f"RSS_CLIENT: Attempting to add/verify initial feeds: {feed_urls}")
    added_count = 0
    for url in feed_urls:
        existing_feed = db.query(RSSFeedSource).filter(RSSFeedSource.url == url).first()
        if not existing_feed:
            try:
                feed_name_guess = url.split('/')[2].replace("www.", "") if len(url.split('/')) > 2 else url
                
                new_feed = RSSFeedSource(
                    url=url, 
                    name=feed_name_guess, 
                    fetch_interval_minutes=app_config.DEFAULT_RSS_FETCH_INTERVAL_MINUTES # Ensure this is set
                )
                db.add(new_feed)
                added_count += 1
                print(f"RSS_CLIENT: Added new feed source to DB: {url}")
            except IntegrityError:
                db.rollback()
                print(f"RSS_CLIENT: Feed already exists (IntegrityError on add): {url}")
            except Exception as e:
                db.rollback()
                print(f"RSS_CLIENT: Error adding feed {url} to DB: {e}")
    if added_count > 0:
        print(f"RSS_CLIENT: Added {added_count} new feed sources to the database.")
    else:
        print("RSS_CLIENT: No new feed sources added (all provided URLs likely exist or list was empty).")

