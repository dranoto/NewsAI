# app/scraper.py
from langchain_community.document_loaders import PlaywrightURLLoader
from langchain_core.documents import Document # For type hinting

async def scrape_urls(urls: list[str]) -> list[Document]:
    """Scrapes content from a list of URLs using PlaywrightURLLoader."""
    if not urls:
        return []

    print(f"Attempting to scrape {len(urls)} URLs...")
    loader = PlaywrightURLLoader(
        urls=urls,
        remove_selectors=["header", "footer", "nav", "aside", "script", "style"],
        continue_on_failure=True
    )
    try:
        documents = await loader.aload()
        print(f"Scraped {len(documents)} documents successfully.")
        return documents
    except Exception as e:
        print(f"An error occurred during scraping with PlaywrightURLLoader: {e}")
        # Depending on the desired behavior, you might return partial results
        # or an empty list for a general failure.
        return []
