"""
Web scraping service for extracting company capabilities from websites
Focuses on key pages: homepage, /about, /services, /capabilities

Uses Playwright for JavaScript-heavy sites with httpx fallback for simple sites
"""
import logging
from typing import Dict, List, Optional
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import asyncio

logger = logging.getLogger(__name__)

class WebScraperService:
    """Extract company information from websites"""
    
    def __init__(self):
        self.timeout = 15.0  # Increased for Playwright
        self.max_pages = 5  # Limit pages to scrape per domain
        self.use_playwright = True  # Try Playwright first for better success rate
        
    def _normalize_url(self, url: str) -> str:
        """Add https:// if missing"""
        if not url.startswith(('http://', 'https://')):
            url = f'https://{url}'
        return url
    
    def _is_valid_url(self, url: str) -> bool:
        """Basic URL validation"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False
    
    def _get_relevant_links(self, base_url: str, soup: BeautifulSoup) -> List[str]:
        """
        Extract relevant internal links for capability discovery
        Prioritizes: /about, /services, /capabilities, /solutions, /what-we-do
        """
        relevant_keywords = [
            'about', 'services', 'capabilities', 'solutions', 
            'what-we-do', 'expertise', 'offerings', 'products'
        ]
        
        links = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            full_url = urljoin(base_url, href)
            
            # Only include internal links
            if urlparse(full_url).netloc != urlparse(base_url).netloc:
                continue
                
            # Check if URL contains relevant keywords
            href_lower = href.lower()
            if any(keyword in href_lower for keyword in relevant_keywords):
                if full_url not in links:
                    links.append(full_url)
        
        return links[:self.max_pages - 1]  # Reserve 1 slot for homepage
    
    def _extract_text_from_html(self, soup: BeautifulSoup) -> str:
        """
        Extract meaningful text from HTML
        Less aggressive filtering for JS-heavy sites
        """
        # Remove unwanted elements (but keep header for brand info)
        for element in soup(['script', 'style', 'nav', 'footer']):
            element.decompose()
        
        # Try multiple content strategies
        text = ""
        
        # Strategy 1: Look for main content areas
        main_content = soup.find('main') or soup.find('article') or soup.find(id='content')
        if main_content:
            text = main_content.get_text(separator=' ', strip=True)
        
        # Strategy 2: If main content is empty, try body but skip header/footer
        if not text or len(text) < 200:
            body = soup.find('body')
            if body:
                text = body.get_text(separator=' ', strip=True)
        
        # Strategy 3: Fallback to everything
        if not text or len(text) < 100:
            text = soup.get_text(separator=' ', strip=True)
        
        # Clean up whitespace while preserving content
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = ' '.join(lines)
        
        # Remove excessive repeated spaces
        import re
        text = re.sub(r'\s+', ' ', text)
        
        return text
    
    async def _fetch_page(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """Fetch a single page with error handling - simple httpx fallback"""
        try:
            response = await client.get(url, timeout=self.timeout, follow_redirects=True)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None
    
    async def _fetch_page_with_playwright(self, url: str) -> Optional[str]:
        """
        Fetch page using Playwright - renders JavaScript
        This handles modern React/Next.js sites that httpx can't scrape
        """
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                
                page = await context.new_page()
                
                # Set timeout and navigate
                page.set_default_timeout(self.timeout * 1000)  # Convert to ms
                await page.goto(url, wait_until='domcontentloaded')
                
                # Wait longer for dynamic content to load (JS frameworks need time)
                await page.wait_for_timeout(3000)
                
                # Scroll to trigger lazy-loaded content
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await page.wait_for_timeout(1000)
                
                # Get rendered HTML
                content = await page.content()
                
                await browser.close()
                
                logger.info(f"✅ Playwright successfully rendered {url}")
                return content
                
        except ImportError:
            logger.warning("Playwright not installed - falling back to httpx")
            return None
        except Exception as e:
            logger.warning(f"Playwright failed for {url}: {e}")
            return None
    
    async def scrape_company_website(self, url: str) -> Dict[str, any]:
        """
        Scrape company website and extract capability information
        
        Args:
            url: Company website URL (e.g., "acmedefense.com" or "https://acmedefense.com")
        
        Returns:
            dict with:
                - success: bool
                - company_name: str (extracted from title/h1)
                - capabilities_text: str (combined text from all pages)
                - pages_scraped: int
                - error: Optional[str]
        """
        url = self._normalize_url(url)
        
        if not self._is_valid_url(url):
            return {
                "success": False,
                "error": "Invalid URL format",
                "company_name": "",
                "capabilities_text": "",
                "pages_scraped": 0
            }
        
        logger.info(f"🌐 Scraping company website: {url}")
        
        try:
            # STEP 1: Try Playwright first (better for JS-heavy sites)
            homepage_html = None
            
            if self.use_playwright:
                logger.info("Attempting Playwright render...")
                homepage_html = await self._fetch_page_with_playwright(url)
            
            # STEP 2: Fallback to httpx if Playwright failed
            if not homepage_html:
                logger.info("Falling back to httpx...")
                async with httpx.AsyncClient() as client:
                    homepage_html = await self._fetch_page(url, client)
            
            if not homepage_html:
                return {
                    "success": False,
                    "error": "Could not fetch homepage",
                    "company_name": "",
                    "capabilities_text": "",
                    "pages_scraped": 0
                }
            
            soup = BeautifulSoup(homepage_html, 'html.parser')
            
            # 2. Extract company name from title or h1
            company_name = ""
            if soup.title:
                company_name = soup.title.string.strip()
            elif soup.find('h1'):
                company_name = soup.find('h1').get_text(strip=True)
            
            # 3. Get text from homepage
            homepage_text = self._extract_text_from_html(soup)
            all_text = [homepage_text]
            
            # 4. Find and scrape relevant pages (use httpx for speed)
            relevant_links = self._get_relevant_links(url, soup)
            logger.info(f"Found {len(relevant_links)} relevant pages to scrape")
            
            # Fetch relevant pages with httpx (faster than Playwright for multiple pages)
            async with httpx.AsyncClient() as client:
                tasks = [self._fetch_page(link, client) for link in relevant_links]
                pages_html = await asyncio.gather(*tasks)
            
            # 5. Extract text from all pages
            for page_html in pages_html:
                if page_html:
                    page_soup = BeautifulSoup(page_html, 'html.parser')
                    page_text = self._extract_text_from_html(page_soup)
                    all_text.append(page_text)
            
            # 6. Combine all text
            combined_text = ' '.join(all_text)
            
            # 7. Truncate if too long (OpenAI embedding max: ~8000 tokens ≈ 32k chars)
            max_chars = 30000
            if len(combined_text) > max_chars:
                combined_text = combined_text[:max_chars] + "..."
                logger.info(f"Truncated text from {len(combined_text)} to {max_chars} chars")
            
            logger.info(f"✅ Scraped {len(all_text)} pages, extracted {len(combined_text)} chars")
            
            return {
                "success": True,
                "company_name": company_name,
                "capabilities_text": combined_text,
                "pages_scraped": len(all_text),
                "error": None
            }
                
        except Exception as e:
            logger.error(f"❌ Scraping error: {e}")
            return {
                "success": False,
                "error": str(e),
                "company_name": "",
                "capabilities_text": "",
                "pages_scraped": 0
            }