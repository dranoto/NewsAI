# app/scraper.py
import asyncio
import logging
import os
import tempfile
import shutil # For cleaning up the temp user data directory
from playwright.async_api import async_playwright, BrowserContext, Page 
from langchain_core.documents import Document
from typing import Optional, List # Make sure List is imported

# Configure logging
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


async def _scrape_single_url_with_playwright_direct(page: Page, url: str) -> Document:
    """
    Scrapes a single URL using a provided Playwright page object.
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
            "header", "footer", "nav", "aside", "script", "style", "iframe",
            ".ad-slot", "[aria-label='advertisement']", "div[id*='ad']", "div[class*='ad']",
            ".cookie-banner", ".gdpr-banner", ".modal", ".popup", "dialog",
            "#comments", ".comments-area", ".related-articles", ".related-posts",
            ".social-share", ".sidebar", ".site-navigation", ".sub-nav",
            ".utility-bar", "figure.caption-placeholder", "div[class*='overlay']",
            "div[class*='modal']", "div[id*='modal']", "div[id*='popup']",
            "div[class*='hidden']", "div[style*='display: none']",
            "form", ".newsletter-signup"
        ]
        for selector in selectors_to_remove:
            try:
                await page.evaluate(f"document.querySelectorAll('{selector}').forEach(el => el.remove())")
            except Exception as e_remove:
                logger.debug(f"Could not remove elements for selector '{selector}' on {url}: {e_remove}")

        # Try to find and extract text from more specific main content selectors
        main_content_selectors = [
            "article[data-component='article-body']", "div[data-component='story-body']",
            "article.article-body", "article .post-content", "article .entry-content",
            "main#main-content", "div.article-content", "div.story", "div.content-body",
            "div.articletext", "article", "main", "div[role='main']",
            ".main-content", ".story-content", ".post", "section.content",
            "div.content", "div.body-text", "div.articleBody", "div.article__body",
            "div.entry-content", "div.td-post-content", "div.single-post-content",
            "div.article-container__content"
        ]
        
        candidate_texts = []
        for selector in main_content_selectors:
            try:
                elements = page.locator(selector)
                count = await elements.count()
                if count > 0:
                    logger.debug(f"Found {count} element(s) for selector '{selector}' on {url}")
                    for i in range(min(count, 3)): # Check up to 3 matches for a given selector type
                        element_text: Optional[str] = None
                        try:
                            element_text = await elements.nth(i).inner_text(timeout=5000)
                        except Exception as e_inner_text:
                            logger.debug(f"Timeout/error getting inner_text for '{selector}' (match {i+1}) on {url}: {e_inner_text}")
                            continue
                        
                        if element_text and len(element_text.strip()) > 250:
                            stripped_text = " ".join(element_text.strip().split())
                            candidate_texts.append(stripped_text)
                            logger.info(f"Added candidate text (length: {len(stripped_text)}) from selector '{selector}', match #{i+1}")
                            if len(stripped_text) > 2000: break 
                    if any(len(ct) > 2000 for ct in candidate_texts): break 
            except Exception as e_select:
                logger.debug(f"Error processing selector '{selector}' for {url}: {e_select}")
        
        if candidate_texts:
            page_content_text = max(candidate_texts, key=len)
            logger.info(f"Selected best candidate text (length: {len(page_content_text)}) for {url}.")
        else:
            logger.warning(f"No specific main content selectors yielded substantial text for {url}. Falling back to globally cleaned body text.")
            try:
                body_locator = page.locator("body")
                if await body_locator.count() > 0:
                    page_content_text = await body_locator.inner_text(timeout=10000)
                    if page_content_text:
                        page_content_text = " ".join(page_content_text.split())
                else:
                    page_content_text = ""
            except Exception as e_body:
                logger.error(f"Error falling back to body text for {url}: {e_body}")
                page_content_text = ""

        if not page_content_text or len(page_content_text) < 100:
            msg = f"Scraped content too short (<100 chars) or empty for {url}. Length: {len(page_content_text or '')}"
            logger.warning(msg)
            metadata["error"] = msg
            page_content_text = "" 
        else:
            logger.info(f"Successfully scraped and processed: {url} (Final Text Length: {len(page_content_text)})")

    except Exception as e:
        error_msg = f"General scraping failure for {url}: {type(e).__name__} - {str(e)}"
        logger.error(error_msg, exc_info=True)
        metadata["error"] = error_msg
        page_content_text = "" 
    
    return Document(page_content=page_content_text, metadata=metadata)


async def scrape_urls(
    urls: list[str],
    path_to_extension_folder: Optional[str] = None,
    use_headless_browser: bool = True,
    prioritized_sites: Optional[List[str]] = None # Added Optional for consistency
) -> list[Document]:
    """
    Scrapes content from a list of URLs using Playwright, with support for loading a browser extension.
    """
    if not urls:
        return []
    
    if prioritized_sites:
        logger.info(f"Note: 'prioritized_sites' argument received but not currently used for special handling.")

    logger.info(f"Attempting to scrape {len(urls)} URLs. Extension path: {path_to_extension_folder}, Headless: {use_headless_browser}")
    
    all_loaded_docs: list[Document] = []
    
    browser_launch_args: List[str] = [
        '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
        '--disable-accelerated-2d-canvas', '--no-first-run', '--no-zygote',
        '--disable-gpu'
    ]

    if path_to_extension_folder:
        if not os.path.isdir(path_to_extension_folder):
            logger.error(f"Extension path not found or not a directory: {path_to_extension_folder}. Proceeding without extension.")
            path_to_extension_folder = None # Disable extension if path is invalid
        else:
            absolute_extension_path = os.path.abspath(path_to_extension_folder)
            browser_launch_args.extend([
                f"--disable-extensions-except={absolute_extension_path}",
                f"--load-extension={absolute_extension_path}",
            ])
            logger.info(f"Attempting to load extension from: {absolute_extension_path}")
    else:
        logger.info("No extension path provided. Running browser without custom extensions.")

    # Create a temporary directory for user data for the persistent context
    user_data_dir = tempfile.mkdtemp()
    logger.info(f"Using temporary user data directory: {user_data_dir}")

    context: Optional[BrowserContext] = None

    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir,
                headless=use_headless_browser,
                channel='chromium', # Important for extensions
                args=browser_launch_args,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
                # java_script_enabled is True by default for contexts
                ignore_https_errors=True,
                viewport={'width': 1280, 'height': 720}
            )
            logger.info(f"Persistent browser context launched. Headless: {use_headless_browser}, Args: {browser_launch_args}")

            if path_to_extension_folder:
                # Check for service worker to confirm Manifest v3 extension loading
                try:
                    # Wait a bit for the extension to potentially initialize its service worker
                    await asyncio.sleep(2) # Give a couple of seconds
                    service_workers = context.service_workers
                    if service_workers:
                        logger.info(f"Found {len(service_workers)} service worker(s). Extension likely loaded (Manifest v3).")
                        for sw in service_workers:
                            logger.info(f"Service Worker URL: {sw.url}")
                            # Example: extension_id = sw.url.split('/')[2]
                            # logger.info(f"Example Extension ID (from SW): {extension_id}")
                    else:
                        logger.info("No service workers found immediately. Waiting for event...")
                        sw = await context.wait_for_event('serviceworker', timeout=7000)
                        if sw:
                            logger.info("Service worker event received (Manifest v3).")
                            extension_id = sw.url().split('/')[2]
                            logger.info(f"Extension ID from service worker event: {extension_id}")
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for serviceworker event (Manifest v3). Extension might not have loaded or has no active SW.")
                except Exception as e_sw:
                    logger.warning(f"Error checking for service worker: {e_sw}")
            
            # Create one page to reuse for all URLs in this batch
            page: Page = await context.new_page()

            for url in urls:
                logger.info(f"Processing URL with persistent context: {url}")
                doc = await _scrape_single_url_with_playwright_direct(page, url)
                all_loaded_docs.append(doc)
                await asyncio.sleep(1) # Small delay between requests

        except Exception as e:
            logger.error(f"Error during Playwright persistent context session: {e}", exc_info=True)
            # Create error documents for any URLs that were not processed due to early exit
            processed_urls = {d.metadata.get("source") for d in all_loaded_docs}
            for url_not_processed in urls:
                if url_not_processed not in processed_urls:
                    all_loaded_docs.append(Document(
                        page_content="", 
                        metadata={"source": url_not_processed, "error": f"Playwright session failed before processing: {e}"}
                    ))
        finally:
            if context:
                try:
                    await context.close()
                    logger.info("Persistent browser context closed.")
                except Exception as e_close_context:
                    logger.error(f"Error closing persistent context: {e_close_context}", exc_info=True)
            
            # Clean up the temporary user data directory
            try:
                if os.path.exists(user_data_dir):
                    shutil.rmtree(user_data_dir)
                    logger.info(f"Cleaned up temporary user data directory: {user_data_dir}")
            except Exception as e_cleanup:
                logger.warning(f"Could not clean up temporary user data directory {user_data_dir}: {e_cleanup}")
            
    successful_scrapes = len([
        d for d in all_loaded_docs 
        if d.page_content and not d.metadata.get('error')
    ])
    logger.info(f"Playwright scraping with persistent context finished. Successfully scraped meaningful content for {successful_scrapes}/{len(urls)} URLs.")
    return all_loaded_docs

# Example of how to test this scraper module directly (optional)
async def _test_scraper():
    test_urls = [
        "https://www.example.com", # A simple site
        # "https://www.theverge.com/2022/2/7/22921420/wordle-new-york-times-free-word-archive-website", 
        # "https://nonexistenturltotestfailure.com/article"
    ]
    # To test with an extension, create a dummy extension folder, e.g., 'my_test_extension'
    # with a manifest.json, and pass its path.
    # For example, if 'my_test_extension' is in the same directory as scraper.py:
    # test_extension_path = "my_test_extension" 
    test_extension_path = None # Set to a valid path to test extension loading
    
    # Create a dummy extension for testing if one is specified and doesn't exist
    if test_extension_path and not os.path.exists(test_extension_path):
        os.makedirs(test_extension_path, exist_ok=True)
        with open(os.path.join(test_extension_path, "manifest.json"), "w") as f:
            f.write('{"manifest_version": 3, "name": "Test Scraper Assistant", "version": "1.0"}')
        logger.info(f"Created dummy extension for testing at {test_extension_path}")


    logger.info("Starting scraper test with persistent context...")
    results = await scrape_urls(
        test_urls,
        path_to_extension_folder=test_extension_path,
        use_headless_browser=True # Or False to see the browser (if not in a headless environment)
    )
    for doc in results:
        print("\n" + "="*30)
        print(f"URL: {doc.metadata.get('source')}")
        if doc.metadata.get('error'):
            print(f"Error: {doc.metadata.get('error')}")
        else:
            print(f"Content Length: {len(doc.page_content)}")
            print(f"Preview: {doc.page_content[:200]}...")
        print("="*30)
    
    # Clean up dummy extension if created
    if test_extension_path and os.path.exists(test_extension_path) and "dummy extension" in logger.handlers[0].formatter._fmt : # crude check
        shutil.rmtree(test_extension_path)
        logger.info(f"Cleaned up dummy extension folder: {test_extension_path}")


if __name__ == '__main__':
    # This allows running `python -m app.scraper` to test
    # Note: Ensure playwright browsers are installed (`python -m playwright install chromium`)
    asyncio.run(_test_scraper())
