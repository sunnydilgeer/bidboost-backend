"""
SAM.gov Attachment Scraper using Playwright
Extracts attachment URLs from SAM.gov contract opportunity pages.

Usage:
    scraper = SAMAttachmentScraper()
    await scraper.initialize()
    attachments = await scraper.get_attachments(notice_id)
    await scraper.close()
"""

import asyncio
import logging
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout
import random

logger = logging.getLogger(__name__)


class SAMAttachmentScraper:
    """Scrapes SAM.gov contract opportunity pages for attachment URLs."""
    
    BASE_URL = "https://sam.gov/opp/{notice_id}/view"
    
    # User agents to rotate (avoid detection)
    USER_AGENTS = [
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]
    
    def __init__(self, headless: bool = True, timeout: int = 30000):
        """
        Initialize scraper.
        
        Args:
            headless: Run browser in headless mode (True for production)
            timeout: Page load timeout in milliseconds
        """
        self.headless = headless
        self.timeout = timeout
        self.playwright = None
        self.browser: Optional[Browser] = None
        
    async def initialize(self):
        """Initialize Playwright browser."""
        logger.info("Initializing Playwright browser...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        logger.info("Browser initialized successfully")
        
    async def close(self):
        """Close browser and cleanup."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")
    
    async def get_attachments(self, notice_id: str) -> Dict[str, any]:
        """
        Scrape attachments for a given notice ID.
        
        Args:
            notice_id: SAM.gov NoticeId (from CSV)
            
        Returns:
            Dict with attachments, description, and metadata
        """
        if not self.browser:
            raise RuntimeError("Browser not initialized. Call initialize() first.")
        
        url = self.BASE_URL.format(notice_id=notice_id)
        logger.info(f"Scraping: {url}")
        
        # Create new page with random user agent
        page = await self.browser.new_page(
            user_agent=random.choice(self.USER_AGENTS)
        )
        
        try:
            # Navigate to page
            await page.goto(url, wait_until="networkidle", timeout=self.timeout)
            logger.info(f"Page loaded: {url}")
            
            # Wait for page to be ready (main content visible)
            await page.wait_for_selector('h1', timeout=10000)
            
            # Get page title (for validation)
            title = await page.title()
            
            # Wait for attachments section to load
            # Strategy: Wait for either attachments or "no attachments" message
            attachments = []
            
            try:
                # Wait for spinner to disappear (max 15 seconds)
                await page.wait_for_selector('.fa-spinner', state='detached', timeout=15000)
                logger.info("Attachments section loaded")
                
                # Now extract attachment links
                # SAM.gov typically has download links in the attachments section
                attachment_section = page.locator('#attachments-links')
                
                # Look for download links
                links = await attachment_section.locator('a').all()
                
                for link in links:
                    try:
                        href = await link.get_attribute('href')
                        text = await link.inner_text()
                        
                        # Filter for actual file downloads
                        if href and any(ext in href.lower() for ext in ['.pdf', '.doc', '.docx', 'download', '/file/']):
                            # Make absolute URL
                            if href.startswith('/'):
                                href = f"https://sam.gov{href}"
                            elif not href.startswith('http'):
                                href = f"https://sam.gov/{href}"
                            
                            attachments.append({
                                'filename': text.strip(),
                                'url': href,
                            })
                    except Exception as e:
                        logger.warning(f"Failed to parse attachment link: {e}")
                        continue
                
                logger.info(f"Found {len(attachments)} attachments")
                
            except PlaywrightTimeout:
                logger.warning("Attachments section did not load (spinner timeout)")
            
            # Extract description (from the page, might be better than CSV)
            description = ""
            try:
                desc_section = page.locator('#description .inner-html-description')
                description = await desc_section.inner_text()
                description = description.strip()
            except:
                logger.warning("Could not extract description from page")
            
            # Extract opportunity type
            opp_type = ""
            try:
                type_elem = page.locator('.sam.top.right.attached.mini.label')
                opp_type = await type_elem.inner_text()
            except:
                pass
            
            await page.close()
            
            return {
                "notice_id": notice_id,
                "url": url,
                "title": title,
                "attachments": attachments,
                "description": description[:500] if description else "",
                "opportunity_type": opp_type,
                "success": True,
            }
            
        except Exception as e:
            await page.close()
            logger.error(f"Failed to scrape {notice_id}: {str(e)}")
            return {
                "notice_id": notice_id,
                "url": url,
                "attachments": [],
                "success": False,
                "error": str(e),
            }
    
    async def get_attachments_batch(
        self, 
        notice_ids: List[str], 
        delay_range: tuple = (2, 5)
    ) -> List[Dict]:
        """
        Scrape multiple notice IDs with rate limiting.
        
        Args:
            notice_ids: List of NoticeIds to scrape
            delay_range: Random delay between requests (min, max) in seconds
            
        Returns:
            List of results for each notice_id
        """
        results = []
        
        for i, notice_id in enumerate(notice_ids, 1):
            logger.info(f"Processing {i}/{len(notice_ids)}: {notice_id}")
            
            result = await self.get_attachments(notice_id)
            results.append(result)
            
            # Rate limiting: random delay between requests
            if i < len(notice_ids):
                delay = random.uniform(*delay_range)
                logger.info(f"Waiting {delay:.1f} seconds before next request...")
                await asyncio.sleep(delay)
        
        return results


# Synchronous wrapper for use in non-async code
def scrape_sam_attachments(notice_id: str, headless: bool = True) -> Dict:
    """
    Synchronous wrapper for scraping a single notice.
    
    Args:
        notice_id: SAM.gov NoticeId
        headless: Run in headless mode
        
    Returns:
        Dict with attachments and metadata
    """
    async def _scrape():
        scraper = SAMAttachmentScraper(headless=headless)
        await scraper.initialize()
        result = await scraper.get_attachments(notice_id)
        await scraper.close()
        return result
    
    return asyncio.run(_scrape())


def scrape_sam_attachments_batch(
    notice_ids: List[str], 
    headless: bool = True,
    delay_range: tuple = (2, 5)
) -> List[Dict]:
    """
    Synchronous wrapper for scraping multiple notices.
    
    Args:
        notice_ids: List of NoticeIds
        headless: Run in headless mode
        delay_range: Delay between requests (seconds)
        
    Returns:
        List of results
    """
    async def _scrape():
        scraper = SAMAttachmentScraper(headless=headless)
        await scraper.initialize()
        results = await scraper.get_attachments_batch(notice_ids, delay_range)
        await scraper.close()
        return results
    
    return asyncio.run(_scrape())