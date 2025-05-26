# app/scraper.py
import asyncio
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.documents import Document # For type hinting

# THIS MUST BE A SYNCHRONOUS FUNCTION for asyncio.to_thread
def _scrape_single_url_blocking(url: str) -> Document:
    """
    Synchronous helper function to load a single URL using WebBaseLoader's .load().
    This function is intended to be run in a separate thread via asyncio.to_thread.
    """
    print(f"Scraping (in thread): {url}")
    try:
        # WebBaseLoader can accept headers if needed, e.g., for user-agent
        # header_template = {"User-Agent": "MyNewsSummarizerBot/1.0"}
        # loader = WebBaseLoader(web_path=url, header_template=header_template)
        loader = WebBaseLoader(web_path=url)
        
        # Use the synchronous .load() method here
        docs_from_url = loader.load() 
        
        if docs_from_url:
            # Assuming WebBaseLoader.load() for a single URL returns a list with one Document
            doc = docs_from_url[0] 
            if doc.page_content and doc.page_content.strip():
                print(f"Successfully scraped: {url} (Length: {len(doc.page_content)})")
                return doc
            else:
                msg = "No meaningful content extracted by WebBaseLoader"
                print(f"{msg} for: {url}")
                return Document(page_content="", metadata={"source": url, "error": msg})
        else:
            msg = "WebBaseLoader returned no documents"
            print(f"{msg} for: {url}")
            return Document(page_content="", metadata={"source": url, "error": msg})
    except Exception as e:
        # Catching a broader range of exceptions during scraping
        error_msg = f"Failed to scrape {url}: {type(e).__name__} - {e}"
        print(error_msg)
        return Document(page_content="", metadata={"source": url, "error": error_msg})

async def scrape_urls(urls: list[str]) -> list[Document]:
    """
    Scrapes content from a list of URLs by running WebBaseLoader.load()
    for each URL in a separate thread to avoid blocking the asyncio event loop.
    """
    if not urls:
        return []

    print(f"Attempting to scrape {len(urls)} URLs using WebBaseLoader in threads...")
    
    # Create a list of tasks to run the _scrape_single_url_blocking function for each URL
    tasks = [asyncio.to_thread(_scrape_single_url_blocking, url) for url in urls]
    
    # Run all tasks concurrently and wait for them to complete.
    # The results from asyncio.to_thread (when awaited via gather) are the return values 
    # of the synchronous function (_scrape_single_url_blocking).
    all_loaded_docs_results = await asyncio.gather(*tasks)
    
    # Filter out potential None results if any critical error happened before Document creation, though unlikely with current helper.
    all_loaded_docs = [doc for doc in all_loaded_docs_results if isinstance(doc, Document)] 
            
    successful_scrapes = len([d for d in all_loaded_docs if not d.metadata.get('error')])
    print(f"WebBaseLoader (in threads) finished. Successfully scraped content for {successful_scrapes}/{len(urls)} URLs.")
    return all_loaded_docs
