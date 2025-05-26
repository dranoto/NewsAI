# app/config.py
import os
from dotenv import load_dotenv
import json

load_dotenv() # Load environment variables from .env file if it exists

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --- LLM Model Configurations ---
DEFAULT_SUMMARY_MODEL_NAME = os.environ.get("DEFAULT_SUMMARY_MODEL_NAME", "gemini-1.5-flash-latest")
DEFAULT_CHAT_MODEL_NAME = os.environ.get("DEFAULT_CHAT_MODEL_NAME", "gemini-1.5-pro-latest")


# --- Application Behavior Defaults ---
DEFAULT_PAGE_SIZE = int(os.environ.get("DEFAULT_PAGE_SIZE", 6)) # Articles per page
MAX_ARTICLES_PER_INDIVIDUAL_FEED = int(os.environ.get("MAX_ARTICLES_PER_INDIVIDUAL_FEED", 15)) # Max to initially fetch from a single feed

# --- RSS Feed Configuration ---
# This list serves as a default if the frontend does not provide any RSS feed URLs.
# The frontend will primarily manage the list of feeds to be processed.
rss_feeds_env_str = os.environ.get("RSS_FEED_URLS", "") # Loaded from .env or Docker env
if rss_feeds_env_str.startswith("[") and rss_feeds_env_str.endswith("]"):
    try:
        RSS_FEED_URLS = json.loads(rss_feeds_env_str)
    except json.JSONDecodeError:
        print("Warning: RSS_FEED_URLS in .env is not valid JSON. Falling back to empty list.")
        RSS_FEED_URLS = []
elif rss_feeds_env_str:
    RSS_FEED_URLS = [url.strip() for url in rss_feeds_env_str.split(',')]
else:
    RSS_FEED_URLS = [ # Default feeds if not set in .env and frontend sends empty
        # "https://morss.it/https://www.lemonde.fr/en/rss/une.xml",
        # "https://feedx.net/rss/ap.xml",
    ]

print(f"Default RSS Feeds loaded from server config: {RSS_FEED_URLS}")
print(f"Default page size from server config: {DEFAULT_PAGE_SIZE}")
