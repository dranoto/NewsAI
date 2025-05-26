# app/scraper.py
import asyncio
from langchain_community.document_loaders import PlaywrightURLLoader
from langchain_core.documents import Document

async def _scrape_single_url_with_playwright_async(url: str) -> Document:
    """
    Asynchronously loads a single URL using PlaywrightURLLoader.
    This helper is to ensure individual error handling for each URL.
    """
    print(f"Scraping with Playwright (async): {url}")
    try:
        loader = PlaywrightURLLoader(
            urls=[url], 
            remove_selectors=["header", "footer", "nav", "aside", "script", "style", ".ad-slot", "[aria-label='advertisement']", "#standalone-paywall"],
            continue_on_failure=True # For internal loader retries/handling
        )
        
        documents = await loader.aload()

        if documents:
            doc = documents[0] 
            if doc.page_content and doc.page_content.strip():
                print(f"Successfully scraped with Playwright: {url} (Length: {len(doc.page_content)})")
                return doc
            else:
                msg = "No meaningful content extracted by PlaywrightURLLoader (content was empty or whitespace)"
                print(f"{msg} for: {url}")
                return Document(page_content="", metadata={"source": url, "error": msg})
        else:
            msg = "PlaywrightURLLoader returned no documents"
            print(f"{msg} for: {url}")
            return Document(page_content="", metadata={"source": url, "error": msg})
    except Exception as e:
        error_msg = f"Failed to scrape {url} with Playwright: {type(e).__name__} - {e}"
        print(error_msg)
        return Document(page_content="", metadata={"source": url, "error": error_msg})

async def scrape_urls(urls: list[str], prioritized_sites: list[str] = None) -> list[Document]:
    """
    Scrapes content from a list of URLs using PlaywrightURLLoader asynchronously.
    The 'prioritized_sites' argument is now ignored as no special authentication logic is used.
    """
    if not urls:
        return []
    if prioritized_sites: # Log if it's passed, but it won't be used for different logic
        print(f"Note: 'prioritized_sites' argument received but not used for special handling in this scraper version.")

    print(f"Attempting to scrape {len(urls)} URLs using PlaywrightURLLoader asynchronously...")
    
    tasks = [_scrape_single_url_with_playwright_async(url) for url in urls]
    all_loaded_docs_results = await asyncio.gather(*tasks)
    
    all_loaded_docs = [doc for doc in all_loaded_docs_results if isinstance(doc, Document)]
            
    successful_scrapes = len([
        d for d in all_loaded_docs 
        if d.page_content and d.page_content.strip() and not d.metadata.get('error')
    ])
    print(f"PlaywrightURLLoader finished. Successfully scraped meaningful content for {successful_scrapes}/{len(urls)} URLs.")
    return all_loaded_docs
