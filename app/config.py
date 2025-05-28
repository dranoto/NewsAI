# app/config.py
import os
from dotenv import load_dotenv
import json

load_dotenv() # Load environment variables from .env file

# --- Database Configuration ---
SQLITE_DB_SUBDIR = "data"
SQLITE_DB_FILE = "newsai.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///./{SQLITE_DB_SUBDIR}/{SQLITE_DB_FILE}")

# --- LLM Configuration ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DEFAULT_SUMMARY_MODEL_NAME = os.getenv("DEFAULT_SUMMARY_MODEL_NAME", "gemini-1.5-flash-latest")
DEFAULT_CHAT_MODEL_NAME = os.getenv("DEFAULT_CHAT_MODEL_NAME", "gemini-1.5-flash-latest")
DEFAULT_TAG_MODEL_NAME = os.getenv("DEFAULT_TAG_MODEL_NAME", "gemini-1.5-flash-latest")

# Max output tokens for different LLM tasks
SUMMARY_MAX_OUTPUT_TOKENS = int(os.getenv("SUMMARY_MAX_OUTPUT_TOKENS", 1024))
CHAT_MAX_OUTPUT_TOKENS = int(os.getenv("CHAT_MAX_OUTPUT_TOKENS", 4096))
TAG_MAX_OUTPUT_TOKENS = int(os.getenv("TAG_MAX_OUTPUT_TOKENS", 100))

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


# --- Scraper Configuration ---
SITES_REQUIRING_PLAYWRIGHT: list[str] = ["wsj.com", "ft.com"] # This might be less relevant if all scraping uses Playwright
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
REQUEST_TIMEOUT = 10 # For non-Playwright requests, if any remain

# --- Playwright specific settings ---
PLAYWRIGHT_TIMEOUT = 60000 # Increased from 20000 to match Colab's page.goto timeout

# Path to the browser extension directory (relative to the app's root in Docker, e.g., /app/scraper_assistant)
PATH_TO_EXTENSION = os.getenv("PATH_TO_EXTENSION", "/app/scraper_assistant")
# Whether to run the Playwright browser in headless mode
USE_HEADLESS_BROWSER = os.getenv("USE_HEADLESS_BROWSER", "True").lower() in ('true', '1', 't')


# --- Default AI Prompts ---
DEFAULT_SUMMARY_PROMPT = os.getenv("DEFAULT_SUMMARY_PROMPT", """Task:Generate a concise, narrative summary of the following article. The output must be Markdown-formatted and meticulously optimized for scannability, readability, and minimal cognitive load. (Note: The article title will be provided separately).
Format & Content:

Key Takeaways (1-3 Labeled Bullets):
Present the most critical facts using * bullets.
Prefix each bullet with a bold semantic label (choose from: Who:, What:, Where:, When:, Why:, How:, Impact:, Context:, Next: - use the most relevant 1-3 labels).
Keep the bullet text concise (max 10-15 words).
Use bold Markdown on the most crucial 1-3 words within the bullet text itself.
Example: * **Impact:** This **challenges existing models**.
Narrative Context (3-5 Sentences):
Follow with a single, coherent paragraph.
The first sentence must immediately set the scene or state the primary significance.
This paragraph must connect the key takeaways, providing narrative flow, context, or deeper meaning.
It must build upon, not just repeat, the bullets by explaining how events unfolded or why they matter.
Use italics sparingly for emphasis if needed.
Style & Principles:

Clarity: Use active voice, strong verbs, and simple, direct language. Avoid or explain jargon.
Structure: Ensure short sentences and the defined format enhance scannability.
Markdown: Use **bold** and *italics* strategically to guide the eye, not overwhelm it.
Storytelling: Weave a clear, engaging narrative within the paragraph.
Tone: Maintain an objective, professional, yet compelling tone.
Edge Case Handling:

If the article is very short, trivial, an error page, or lacks substantive information, respond only with: *Article content insufficient for summary.*
Article:{text}
Summary:""")

DEFAULT_CHAT_PROMPT = os.getenv("DEFAULT_CHAT_PROMPT", """Persona & Goal:You are an insightful AI analyst and conversational partner. Your purpose is to help the user explore the provided article's content in greater depth, moving beyond the initial summary. Aim to provide rich, multi-faceted answers that synthesize information, offer context, and encourage further thought.
Context:The user has likely seen a concise V5 summary and is now asking a specific question ({question}) about the article ({article_text}). They are looking for more than just a surface-level answer.
Instructions for Answering:
Ground in the Article: Base your core answer firmly on the provided {article_text}. Reference or quote specific points where it adds clarity. If the article doesn't cover the question, state so explicitly.
Synthesize & Enrich: Go beyond simple extraction. Connect ideas within the article and enrich the answer with relevant general knowledge.
Integrate Perspectives (Where Appropriate): Add significant value by briefly incorporating insights or analytical lenses from fields such as:Psychology/Behavior: (e.g., Why might people react this way? What biases could be at play?)
Neurology/Cognition: (e.g., How might this information be processed? Are there cognitive implications?)
Systems Thinking: (e.g., How does this fit into a larger system? What are the feedback loops?)
Leadership/Strategy: (e.g., What are the strategic implications or leadership lessons?)
(Use these lenses judiciously, only when they genuinely add relevant depth to the specific question asked).
Structure for Clarity: Present your answer clearly. Use Markdown (like **bolding** for key terms or * bullet points for lists) to enhance readability and minimize cognitive load.
Maintain Tone: Respond in a professional, objective, yet supportive and conversational tone.
Encourage Dialogue: Crucially, end your response by inviting further interaction. Ask a follow-up question, suggest a related area to explore, or check if your answer fully addressed their need. (e.g., "Does that help clarify the issue, or would you be interested in how this compares to X?" or "What are your thoughts on that particular aspect?")
Input:Article:{article_text}
Question: {question}
Answer:""")

CHAT_NO_ARTICLE_PROMPT = os.getenv("CHAT_NO_ARTICLE_PROMPT", """You are a helpful AI assistant. The user is asking a question, but unfortunately, the content of the article could not be loaded.
Politely inform the user that you cannot answer their question without the article content.

User's Question: {question}

Response:""")

DEFAULT_TAG_GENERATION_PROMPT = os.getenv("DEFAULT_TAG_GENERATION_PROMPT", """Given the following article text, generate a list of 3-5 relevant keywords or tags.
These tags should capture the main topics, entities, or themes of the article.
Return the tags as a comma-separated list. For example: "Technology,Artificial Intelligence,Startups,Venture Capital,Innovation"

Article:
{text}

Tags:""")


if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY environment variable is not set. LLM features will be impaired.")

print(f"CONFIG LOADED: DATABASE_URL: {DATABASE_URL}")
print(f"CONFIG LOADED: GEMINI_API_KEY Set: {'Yes' if GEMINI_API_KEY else 'NO'}")
print(f"CONFIG LOADED: DEFAULT_SUMMARY_MODEL_NAME: {DEFAULT_SUMMARY_MODEL_NAME}")
print(f"CONFIG LOADED: DEFAULT_CHAT_MODEL_NAME: {DEFAULT_CHAT_MODEL_NAME}")
print(f"CONFIG LOADED: DEFAULT_TAG_MODEL_NAME: {DEFAULT_TAG_MODEL_NAME}")
print(f"CONFIG LOADED: SUMMARY_MAX_OUTPUT_TOKENS: {SUMMARY_MAX_OUTPUT_TOKENS}")
print(f"CONFIG LOADED: CHAT_MAX_OUTPUT_TOKENS: {CHAT_MAX_OUTPUT_TOKENS}")
print(f"CONFIG LOADED: TAG_MAX_OUTPUT_TOKENS: {TAG_MAX_OUTPUT_TOKENS}")
print(f"CONFIG LOADED: RSS_FEED_URLS from ENV: {RSS_FEED_URLS}")
print(f"CONFIG LOADED: DEFAULT_PAGE_SIZE: {DEFAULT_PAGE_SIZE}")
print(f"CONFIG LOADED: MAX_ARTICLES_PER_INDIVIDUAL_FEED: {MAX_ARTICLES_PER_INDIVIDUAL_FEED}")
print(f"CONFIG LOADED: DEFAULT_RSS_FETCH_INTERVAL_MINUTES: {DEFAULT_RSS_FETCH_INTERVAL_MINUTES}")
print(f"CONFIG LOADED: PLAYWRIGHT_TIMEOUT: {PLAYWRIGHT_TIMEOUT}")
print(f"CONFIG LOADED: PATH_TO_EXTENSION: {PATH_TO_EXTENSION}")
print(f"CONFIG LOADED: USE_HEADLESS_BROWSER: {USE_HEADLESS_BROWSER}")
print(f"CONFIG LOADED: DEFAULT_SUMMARY_PROMPT (first 100 chars): {DEFAULT_SUMMARY_PROMPT[:100]}...")
print(f"CONFIG LOADED: DEFAULT_CHAT_PROMPT (first 100 chars): {DEFAULT_CHAT_PROMPT[:100]}...")
print(f"CONFIG LOADED: CHAT_NO_ARTICLE_PROMPT (first 100 chars): {CHAT_NO_ARTICLE_PROMPT[:100]}...")
print(f"CONFIG LOADED: DEFAULT_TAG_GENERATION_PROMPT (first 100 chars): {DEFAULT_TAG_GENERATION_PROMPT[:100]}...")
