# app/config.py
import os
from dotenv import load_dotenv
import json 

load_dotenv() # Load environment variables from .env file

# --- Database Configuration ---
SQLITE_DB_SUBDIR = "data"  # Ensures the database is in a subdirectory
SQLITE_DB_FILE = "newsai.db" # Name of the SQLite database file
# This constructs the path like ./data/newsai.db relative to the app's CWD
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///./{SQLITE_DB_SUBDIR}/{SQLITE_DB_FILE}")

# --- LLM Configuration ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_SUMMARY_MODEL_NAME = os.getenv("DEFAULT_SUMMARY_MODEL_NAME", "gemini-1.5-flash-latest")
DEFAULT_CHAT_MODEL_NAME = os.getenv("DEFAULT_CHAT_MODEL_NAME", "gemini-1.5-flash-latest") 

# --- RSS Feed Configuration ---
rss_feeds_env_str = os.getenv("RSS_FEED_URLS", "")  
if rss_feeds_env_str.strip().startswith("[") and rss_feeds_env_str.strip().endswith("]"):
    try:
        RSS_FEED_URLS = json.loads(rss_feeds_env_str)
        if not isinstance(RSS_FEED_URLS, list): 
            print("Warning: RSS_FEED_URLS from .env (JSON) did not parse as a list. Falling back.")
            RSS_FEED_URLS = []
    except json.JSONDecodeError:
        print(f"Warning: RSS_FEED_URLS in .env ('{rss_feeds_env_str}') is not valid JSON. Falling back to empty list.")
        RSS_FEED_URLS = []
elif rss_feeds_env_str: 
    RSS_FEED_URLS = [url.strip() for url in rss_feeds_env_str.split(',') if url.strip()]
else: 
    RSS_FEED_URLS = []

# --- Application Behavior Defaults ---
try:
    DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", 6)) 
except ValueError:
    print("Warning: Invalid DEFAULT_PAGE_SIZE in .env. Using default 6.")
    DEFAULT_PAGE_SIZE = 6

try:
    MAX_ARTICLES_PER_INDIVIDUAL_FEED = int(os.getenv("MAX_ARTICLES_PER_INDIVIDUAL_FEED", 15))
except ValueError:
    print("Warning: Invalid MAX_ARTICLES_PER_INDIVIDUAL_FEED in .env. Using default 15.")
    MAX_ARTICLES_PER_INDIVIDUAL_FEED = 15

try:
    DEFAULT_RSS_FETCH_INTERVAL_MINUTES = int(os.getenv("DEFAULT_RSS_FETCH_INTERVAL_MINUTES", 60)) 
except ValueError:
    print("Warning: Invalid DEFAULT_RSS_FETCH_INTERVAL_MINUTES in .env. Using default 60.")
    DEFAULT_RSS_FETCH_INTERVAL_MINUTES = 60


# Scraper Configuration
SITES_REQUIRING_PLAYWRIGHT: list[str] = ["wsj.com", "ft.com"] 
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
REQUEST_TIMEOUT = 10  

# Default AI Prompts
DEFAULT_SUMMARY_PROMPT = os.getenv("DEFAULT_SUMMARY_PROMPT", """Please provide a concise summary of the following article.
Focus on the key information and main points.
The summary should be a single, coherent paragraph of about 3-5 sentences.
If the article is very short, trivial, or an error page, indicate that clearly.

Article:
{text}

Summary:""")

DEFAULT_CHAT_PROMPT = os.getenv("DEFAULT_CHAT_PROMPT", """You are a helpful AI assistant. Based on the article text provided below, answer the user's question.
The answer should be concise and directly address the question based on the article's content.
If the question is unrelated to the article, politely state that you can only answer questions about the provided text.
If the article text is empty or seems to be an error/boilerplate, indicate that you cannot answer based on it.

Article:
{article_text}

Question: {question}

Answer:""")

CHAT_NO_ARTICLE_PROMPT = os.getenv("CHAT_NO_ARTICLE_PROMPT", """You are a helpful AI assistant. The user is asking a question, but unfortunately, the content of the article could not be loaded.
Politely inform the user that you cannot answer their question without the article content.

User's Question: {question}

Response:""")


# Playwright specific settings
PLAYWRIGHT_TIMEOUT = 30000  

if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY environment variable is not set. LLM features will be impaired.")

print(f"CONFIG LOADED: DATABASE_URL: {DATABASE_URL}") # Crucial log
print(f"CONFIG LOADED: GEMINI_API_KEY Set: {'Yes' if GEMINI_API_KEY else 'NO'}")
print(f"CONFIG LOADED: DEFAULT_SUMMARY_MODEL_NAME: {DEFAULT_SUMMARY_MODEL_NAME}")
print(f"CONFIG LOADED: DEFAULT_CHAT_MODEL_NAME: {DEFAULT_CHAT_MODEL_NAME}")
print(f"CONFIG LOADED: RSS_FEED_URLS from ENV: {RSS_FEED_URLS}")
print(f"CONFIG LOADED: DEFAULT_PAGE_SIZE: {DEFAULT_PAGE_SIZE}")
print(f"CONFIG LOADED: MAX_ARTICLES_PER_INDIVIDUAL_FEED: {MAX_ARTICLES_PER_INDIVIDUAL_FEED}")
print(f"CONFIG LOADED: DEFAULT_RSS_FETCH_INTERVAL_MINUTES: {DEFAULT_RSS_FETCH_INTERVAL_MINUTES}")
