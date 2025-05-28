# app/scraper.py
import asyncio
import logging
import os
import tempfile
import shutil # For cleaning up the temp user data directory
import re # <<< IMPORT ADDED HERE
from playwright.async_api import async_playwright, BrowserContext, Page
from readability import Document as ReadabilityDocument # For extracting main content
from typing import Optional, List, Dict, Any # Make sure List is imported

from langchain_core.documents import Document as LangchainDocument # Use Langchain Document type

from . import config as app_config # For PATH_TO_EXTENSION and USE_HEADLESS_BROWSER

# Configure logging
logger = logging.getLogger(__name__)
# Ensure logger is configured (it should be by main_api.py, but good practice)
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


async def _extract_content_with_readability(html_content: str, url: str) -> Dict[str, Any]:
    """
    Uses Readability to extract title, text content, and main HTML content.
    """
    metadata_updates = {
        "title": None,
        "text_content": "",
        "main_html_content": None,
        "readability_error": None
    }
    try:
        doc = ReadabilityDocument(html_content)
        metadata_updates["title"] = doc.title()
        
        text_summary = doc.summary(html_partial=False) # Get plain text
        if text_summary:
            # Basic cleaning: replace multiple newlines/spaces with single ones
            text_summary = re.sub(r'\s*\n\s*', '\n', text_summary).strip()
            text_summary = re.sub(r'[ \t]{2,}', ' ', text_summary)
        metadata_updates["text_content"] = text_summary or ""
        
        # CORRECTED METHOD: Use summary(html_partial=True) to get main article HTML
        main_article_html = doc.summary(html_partial=True) 
        metadata_updates["main_html_content"] = main_article_html
        
        if not metadata_updates["text_content"] and not metadata_updates["main_html_content"]:
            metadata_updates["readability_error"] = "Readability extracted no text or HTML content."
            logger.warning(f"Readability found no main content for {url}")
        else:
            logger.info(f"Readability extracted content for {url}. Text length: {len(metadata_updates['text_content'])}, HTML length: {len(metadata_updates['main_html_content'] or '')}")

    except Exception as e:
        logger.error(f"Error processing with Readability for {url}: {e}", exc_info=True)
        metadata_updates["readability_error"] = f"Readability processing error: {str(e)}"
    
    return metadata_updates


async def _scrape_single_url_with_playwright_and_readability(page: Page, url: str) -> LangchainDocument:
    """
    Scrapes a single URL using a provided Playwright page object.
    Gets the full page HTML after JavaScript execution.
    Then uses Readability to extract main text and main HTML content.
    Returns a Langchain Document object.
    """
    logger.info(f"Attempting to scrape with Playwright & Readability: {url}")
    page_text_content = ""
    main_html_content = None
    scraped_title = None
    metadata = {"source": url, "source_method": "Playwright"} 

    try:
        await page.goto(url, timeout=app_config.PLAYWRIGHT_TIMEOUT, wait_until='domcontentloaded')
        await page.wait_for_timeout(3000) 
        full_page_html = await page.content()

        if not full_page_html:
            logger.warning(f"Playwright returned empty page content for {url}.")
            metadata["error"] = "Playwright returned empty page content."
            return LangchainDocument(page_content="", metadata=metadata)

        readability_results = await _extract_content_with_readability(full_page_html, url)
        
        page_text_content = readability_results["text_content"]
        main_html_content = readability_results["main_html_content"]
        scraped_title = readability_results["title"]
        
        if readability_results["readability_error"]:
            metadata["error"] = (metadata.get("error", "") + " | " + readability_results["readability_error"]).strip(" | ")
        
        metadata["title"] = scraped_title 
        metadata["full_html_content"] = main_html_content 

        if not page_text_content or len(page_text_content) < 100: 
            msg = f"Extracted text content too short (<100 chars) or empty for {url} after Readability. Length: {len(page_text_content or '')}"
            logger.warning(msg)
            metadata["error"] = (metadata.get("error", "") + " | " + msg).strip(" | ")
        else:
            logger.info(f"Successfully processed with Readability: {url} (Final Text Length: {len(page_text_content)})")

    except Exception as e:
        error_msg = f"General Playwright/Readability failure for {url}: {type(e).__name__} - {str(e)}"
        logger.error(error_msg, exc_info=True)
        metadata["error"] = error_msg
        page_text_content = "" 
        metadata["full_html_content"] = None
    
    return LangchainDocument(page_content=page_text_content, metadata=metadata)


async def scrape_urls(
    urls: list[str],
    path_to_extension_folder: Optional[str] = app_config.PATH_TO_EXTENSION,
    use_headless_browser: bool = app_config.USE_HEADLESS_BROWSER,
) -> list[LangchainDocument]:
    if not urls:
        return []
    
    logger.info(f"Starting scrape_urls for {len(urls)} URLs. Headless: {use_headless_browser}, Extension path: {path_to_extension_folder}")
    
    all_loaded_docs: list[LangchainDocument] = []
    browser_launch_args: List[str] = [
        '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
        '--disable-accelerated-2d-canvas', '--no-first-run', '--no-zygote',
        '--disable-gpu' 
    ]

    actual_extension_path = None
    if path_to_extension_folder:
        if not os.path.isdir(path_to_extension_folder):
            logger.error(f"Extension path not found or not a directory: {path_to_extension_folder}. Proceeding without extension.")
        else:
            actual_extension_path = os.path.abspath(path_to_extension_folder)
            browser_launch_args.extend([
                f"--disable-extensions-except={actual_extension_path}",
                f"--load-extension={actual_extension_path}",
            ])
            logger.info(f"Attempting to load extension from: {actual_extension_path}")
    else:
        logger.info("No extension path provided. Running browser without custom extensions.")

    user_data_dir = tempfile.mkdtemp() 
    logger.info(f"Using temporary user data directory for Playwright: {user_data_dir}")

    context: Optional[BrowserContext] = None
    p = None 

    try:
        p = await async_playwright().start()
        browser = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=use_headless_browser,
            channel='chromium', 
            args=browser_launch_args,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", 
            ignore_https_errors=True,
            viewport={'width': 1280, 'height': 720} 
        )
        context = browser 
        logger.info(f"Persistent browser context launched. Headless: {use_headless_browser}, Args: {browser_launch_args}")

        if actual_extension_path:
            try:
                await asyncio.sleep(3) 
                service_workers = context.service_workers
                if service_workers:
                    logger.info(f"Found {len(service_workers)} service worker(s). Extension likely active (Manifest v3).")
                    for sw in service_workers: logger.info(f"Service Worker URL: {sw.url}")
                else:
                    logger.info("No service workers found immediately. If using an MV3 extension, this might indicate an issue or it has no active SW.")
            except Exception as e_sw:
                logger.warning(f"Error checking for service worker (optional check): {e_sw}")
        
        page: Page = await context.new_page() 

        for url in urls:
            doc = await _scrape_single_url_with_playwright_and_readability(page, url)
            all_loaded_docs.append(doc)
            await asyncio.sleep(1) 

    except Exception as e:
        logger.error(f"Critical error during Playwright session setup or execution: {e}", exc_info=True)
        processed_urls = {d.metadata.get("source") for d in all_loaded_docs}
        for url_not_processed in urls:
            if url_not_processed not in processed_urls:
                all_loaded_docs.append(LangchainDocument(
                    page_content="", 
                    metadata={"source": url_not_processed, "error": f"Playwright session failed before processing: {type(e).__name__} - {str(e)}"}
                ))
    finally:
        if context:
            try:
                await context.close()
                logger.info("Persistent browser context closed.")
            except Exception as e_close_context:
                logger.error(f"Error closing persistent context: {e_close_context}", exc_info=True)
        if p: 
            try:
                await p.stop()
                logger.info("Playwright manager stopped.")
            except Exception as e_stop_p:
                logger.error(f"Error stopping Playwright manager: {e_stop_p}")
        
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
    logger.info(f"Playwright scraping finished. Successfully extracted meaningful text for {successful_scrapes}/{len(urls)} URLs.")
    return all_loaded_docs

async def _test_scraper():
    test_urls = [
        "https://www.theverge.com/2023/10/26/23933440/google-search-ai-sge-links-perspectives-forums", 
    ]
    test_extension_path = app_config.PATH_TO_EXTENSION 
    
    logger.info("Starting scraper test with direct Playwright and Readability...")
    results = await scrape_urls(
        test_urls,
        path_to_extension_folder=test_extension_path, 
        use_headless_browser=app_config.USE_HEADLESS_BROWSER 
    )
    for i, doc in enumerate(results):
        print(f"\n--- Document {i+1}: {doc.metadata.get('source')} ---")
        print(f"Title: {doc.metadata.get('title')}")
        print(f"Error: {doc.metadata.get('error')}")
        print(f"Text Content Length: {len(doc.page_content or '')}")
        print(f"Text Preview: {(doc.page_content or '')[:300]}...")
        print(f"Main HTML Content Present: {'Yes' if doc.metadata.get('full_html_content') else 'No'}")
        if doc.metadata.get('full_html_content'):
             print(f"Main HTML Preview: {doc.metadata['full_html_content'][:300]}...")
        print("="*30)

if __name__ == '__main__':
    asyncio.run(_test_scraper())
