# app/scraper.py
import asyncio
import logging
from playwright.async_api import async_playwright
from langchain_core.documents import Document # Keep Document for Langchain compatibility

# Configure logging
logger = logging.getLogger(__name__)
# You might want to set the logging level in your main application setup if it's not already.
# For this module, if it's run standalone or if no other config is set, let's default:
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


async def _scrape_single_url_with_playwright_direct(page, url: str) -> Document:
    """
    Scrapes a single URL using a provided Playwright page object.
    This is an adapted version of the logic from the Colab test script.
    Returns a Langchain Document object.
    """
    logger.info(f"Attempting to scrape: {url}")
    page_content_text = ""
    metadata = {"source": url} # Initialize metadata with the source URL

    try:
        await page.goto(url, timeout=60000, wait_until='domcontentloaded')
        await page.wait_for_timeout(3000) # Allow time for dynamic content

        # Global removals: Remove common non-content elements
        selectors_to_remove = [
            "header", "footer", "nav", "aside", "script", "style", 
            ".ad-slot", "[aria-label='advertisement']", "iframe",
            ".cookie-banner", ".gdpr-banner", ".modal", ".popup", 
            "#comments", ".comments-area", ".related-articles",
            ".social-share", ".sidebar", ".related-content", ".site-navigation",
            ".sub-nav", ".utility-bar", "figure.caption-placeholder",
            "div[class*='overlay']", "div[class*='modal']", "div[id*='modal']"
        ]
        for selector in selectors_to_remove:
            try:
                await page.evaluate(f"document.querySelectorAll('{selector}').forEach(el => el.remove())")
            except Exception as e_remove:
                logger.debug(f"Could not remove selector {selector} for {url}: {e_remove}")

        # Try to find and extract text from more specific main content selectors
        main_content_selectors = [
            "article[data-component='article-body']", "div[data-component='story-body']",
            "article.article-body", "article .post-content", "article .entry-content",
            "main#main-content", "div.article-content", "div.story", "div.content-body",
            "div.articletext", "article", "main", "div[role='main']",
            ".main-content", ".story-content", ".post", "section.content", 
            "div.content", "div.body-text"
        ]
        
        candidate_texts = []
        for selector in main_content_selectors:
            try:
                elements = page.locator(selector)
                count = await elements.count()
                if count > 0:
                    logger.debug(f"Found {count} element(s) for selector '{selector}' on {url}")
                    for i in range(min(count, 3)): # Check up to 3 matches for a given selector type
                        element_text = await elements.nth(i).inner_text(timeout=3000)
                        if element_text and len(element_text.strip()) > 250:
                            candidate_texts.append(element_text.strip())
                            logger.info(f"Added candidate text (length: {len(element_text.strip())}) from selector '{selector}', match #{i+1}")
                            if len(element_text.strip()) > 2000: break 
                    if any(len(ct) > 2000 for ct in candidate_texts): break
            except Exception as e_select:
                logger.debug(f"Error processing selector '{selector}' for {url}: {e_select}")
        
        if candidate_texts:
            page_content_text = max(candidate_texts, key=len)
            logger.info(f"Selected best candidate text (length: {len(page_content_text)}) for {url}.")
        else:
            logger.warning(f"No specific main content selectors yielded substantial text for {url}. Falling back to globally cleaned body text.")
            page_content_text = await page.locator("body").inner_text(timeout=10000)
        
        page_content_text = " ".join(page_content_text.split()) if page_content_text else ""

        if not page_content_text or len(page_content_text) < 100:
            msg = "Scraped content was too short or empty after processing."
            logger.warning(f"{msg} for {url}")
            metadata["error"] = msg
            page_content_text = "" # Return empty string for Langchain Document if no good content
        else:
            logger.info(f"Successfully scraped and processed: {url} (Final Text Length: {len(page_content_text)})")

    except Exception as e:
        error_msg = f"General scraping failure for {url}: {type(e).__name__} - {str(e)}"
        logger.error(error_msg, exc_info=True)
        metadata["error"] = error_msg
        page_content_text = "" # Return empty string for Langchain Document on error
    
    return Document(page_content=page_content_text, metadata=metadata)


async def scrape_urls(urls: list[str], prioritized_sites: list[str] = None) -> list[Document]:
    """
    Scrapes content from a list of URLs using direct Playwright interaction.
    The 'prioritized_sites' argument is currently noted but not used for different logic.
    """
    if not urls:
        return []
    if prioritized_sites:
        logger.info(f"Note: 'prioritized_sites' argument received but not used for special handling in this scraper version.")

    logger.info(f"Attempting to scrape {len(urls)} URLs using direct Playwright calls...")
    
    all_loaded_docs: list[Document] = []
    
    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(headless=True) # Default to headless for server-side app
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36",
                java_script_enabled=True,
                ignore_https_errors=True 
            )
            page = await context.new_page()

            for url in urls:
                doc = await _scrape_single_url_with_playwright_direct(page, url)
                all_loaded_docs.append(doc)
                await asyncio.sleep(1) # Small delay between requests

        except Exception as e:
            logger.error(f"Error during Playwright browser session in scrape_urls: {e}", exc_info=True)
            # If browser failed to launch, all URLs will effectively fail.
            # We can create error documents for any remaining URLs if needed,
            # but the current loop structure won't execute for them.
            # For simplicity, let's just return what we have.
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception as e_close:
                    logger.error(f"Error closing browser in scrape_urls: {e_close}", exc_info=True)
            
    successful_scrapes = len([
        d for d in all_loaded_docs 
        if d.page_content and not d.metadata.get('error')
    ])
    logger.info(f"Direct Playwright scraping finished. Successfully scraped meaningful content for {successful_scrapes}/{len(urls)} URLs.")
    return all_loaded_docs

# Example of how to test this scraper module directly (optional)
async def _test_scraper():
    test_urls = [
        "https://www.bbc.com/news/world-us-canada-60288047", # Example BBC article
        "https://www.theverge.com/2022/2/7/22921420/wordle-new-york-times-free-word-archive-website", # Example Verge
        "https://nonexistenturltotestfailure.com/article"
    ]
    logger.info("Starting direct scraper test...")
    results = await scrape_urls(test_urls)
    for doc in results:
        print("\n" + "="*30)
        print(f"URL: {doc.metadata.get('source')}")
        if doc.metadata.get('error'):
            print(f"Error: {doc.metadata.get('error')}")
        else:
            print(f"Content Length: {len(doc.page_content)}")
            print(f"Preview: {doc.page_content[:200]}...")
        print("="*30)

if __name__ == '__main__':
    # This allows running `python -m app.scraper` to test (adjust path if needed)
    # Note: Ensure playwright browsers are installed (`python -m playwright install`)
    
    # For this to run standalone, you might need to adjust sys.path if . is not app's root
    # Or run from the project root: python -m app.scraper
    asyncio.run(_test_scraper())
