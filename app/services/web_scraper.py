"""
Web scraping service for extracting company capabilities from websites
Enhanced to better discover and scrape service/solution pages
"""
import logging
from typing import Dict, List, Optional
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import asyncio
import re

logger = logging.getLogger(__name__)

class WebScraperService:
    """Extract company information from websites with enhanced service discovery"""
    
    def __init__(self):
        self.timeout = 15.0
        self.max_pages = 8  # Increased to get more service pages
        self.use_playwright = True
        
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
    
    def _get_common_service_urls(self, base_url: str) -> List[str]:
        """
        Generate common service page URL patterns
        Many companies use predictable patterns for service pages
        """
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        common_paths = [
            '/services',
            '/solutions',
            '/capabilities',
            '/what-we-do',
            '/our-services',
            '/expertise',
            '/offerings',
            '/products',
            '/industries',
            '/digital-services',
            '/consulting',
            '/technology',
            '/platforms',
        ]
        
        return [f"{base}{path}" for path in common_paths]
    
    def _get_relevant_links(self, base_url: str, soup: BeautifulSoup) -> List[str]:
        """
        Extract relevant internal links for capability discovery
        Enhanced to find service pages from navigation and content
        """
        relevant_keywords = [
            'service', 'solution', 'capabilit', 'expertise', 'offering',
            'product', 'platform', 'consult', 'industr', 'technolog',
            'digital', 'cloud', 'data', 'workday', 'software', 'about'
        ]
        
        found_links = set()
        base_netloc = urlparse(base_url).netloc
        
        # 1. Extract from ALL links (including nav menus)
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            full_url = urljoin(base_url, href)
            
            # Only internal links
            if urlparse(full_url).netloc != base_netloc:
                continue
            
            # Skip non-page links
            if any(ext in full_url.lower() for ext in ['.pdf', '.jpg', '.png', '.zip', '#']):
                continue
            
            # Check if URL or link text contains relevant keywords
            href_lower = href.lower()
            text_lower = a_tag.get_text().lower()
            
            if any(keyword in href_lower or keyword in text_lower for keyword in relevant_keywords):
                found_links.add(full_url)
        
        # 2. Add common service URL patterns (even if not found in links)
        for common_url in self._get_common_service_urls(base_url):
            found_links.add(common_url)
        
        # 3. Look specifically in navigation elements
        nav_elements = soup.find_all(['nav', 'header'])
        for nav in nav_elements:
            for a_tag in nav.find_all('a', href=True):
                href = a_tag['href']
                full_url = urljoin(base_url, href)
                
                if urlparse(full_url).netloc == base_netloc:
                    # Navigation links are usually important
                    found_links.add(full_url)
        
        # Convert to list and prioritize
        links_list = list(found_links)
        
        # Sort by priority (services pages first)
        def link_priority(url):
            url_lower = url.lower()
            # Higher priority for explicit service pages
            if '/services' in url_lower or '/solutions' in url_lower:
                return 0
            elif any(kw in url_lower for kw in ['capabilit', 'offering', 'expertise']):
                return 1
            elif any(kw in url_lower for kw in ['product', 'platform', 'industr']):
                return 2
            elif '/about' in url_lower:
                return 3
            else:
                return 4
        
        links_list.sort(key=link_priority)
        
        logger.info(f"Found {len(links_list)} relevant links")
        return links_list[:self.max_pages - 1]  # Reserve 1 for homepage
    
    def _extract_text_from_html(self, soup: BeautifulSoup) -> str:
        """
        Extract meaningful text from HTML
        Enhanced to capture service descriptions better
        """
        # Remove unwanted elements
        for element in soup(['script', 'style', 'footer', 'cookie-notice', 'cookie-banner']):
            element.decompose()
        
        text_parts = []
        
        # Strategy 1: Extract from main content areas
        content_tags = ['main', 'article', '[role="main"]', '.content', '#content']
        for selector in content_tags:
            elements = soup.select(selector) if selector.startswith(('.', '#', '[')) else soup.find_all(selector)
            for elem in elements:
                text = elem.get_text(separator=' ', strip=True)
                if text and len(text) > 100:
                    text_parts.append(text)
        
        # Strategy 2: Look for service/product sections specifically
        service_sections = soup.find_all(['section', 'div'], class_=re.compile(r'(service|solution|product|offering|capability)', re.I))
        for section in service_sections:
            text = section.get_text(separator=' ', strip=True)
            if text and len(text) > 50:
                text_parts.append(text)
        
        # Strategy 3: Extract from headings + paragraphs (structured content)
        for heading in soup.find_all(['h1', 'h2', 'h3']):
            heading_text = heading.get_text(strip=True)
            if heading_text:
                text_parts.append(heading_text)
                # Get paragraphs after this heading
                next_elem = heading.find_next_sibling()
                while next_elem and next_elem.name in ['p', 'ul', 'ol']:
                    text_parts.append(next_elem.get_text(separator=' ', strip=True))
                    next_elem = next_elem.find_next_sibling()
                    if len(text_parts) > 50:  # Prevent infinite loops
                        break
        
        # Strategy 4: Fallback to body
        if not text_parts or sum(len(t) for t in text_parts) < 500:
            body = soup.find('body')
            if body:
                text_parts.append(body.get_text(separator=' ', strip=True))
        
        # Combine and clean
        combined = ' '.join(text_parts)
        
        # Clean up whitespace
        lines = [line.strip() for line in combined.splitlines() if line.strip()]
        text = ' '.join(lines)
        text = re.sub(r'\s+', ' ', text)
        
        return text
    
    async def _fetch_page(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """Fetch a single page with error handling"""
        try:
            response = await client.get(
                url, 
                timeout=self.timeout, 
                follow_redirects=True,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            if response.status_code == 200:
                logger.info(f"✅ Successfully fetched {url}")
                return response.text
            else:
                logger.warning(f"⚠️ Got {response.status_code} for {url}")
                return None
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None
    
    async def _fetch_page_with_playwright(self, url: str) -> Optional[str]:
        """Fetch page using Playwright - renders JavaScript"""
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
                page.set_default_timeout(self.timeout * 1000)
                
                await page.goto(url, wait_until='domcontentloaded')
                await page.wait_for_timeout(3000)  # Wait for dynamic content
                
                # Scroll to load lazy content
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await page.wait_for_timeout(1000)
                
                content = await page.content()
                await browser.close()
                
                logger.info(f"✅ Playwright rendered {url}")
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
        Enhanced with better service page discovery
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
        
        logger.info(f"🌐 Starting enhanced scrape of: {url}")
        
        try:
            # STEP 1: Fetch homepage (try Playwright first for JS sites)
            homepage_html = None
            
            if self.use_playwright:
                logger.info("🎭 Attempting Playwright render...")
                homepage_html = await self._fetch_page_with_playwright(url)
            
            # Fallback to httpx
            if not homepage_html:
                logger.info("📄 Falling back to httpx...")
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
            
            # STEP 2: Extract company name
            company_name = ""
            if soup.title:
                company_name = soup.title.string.strip()
            elif soup.find('h1'):
                company_name = soup.find('h1').get_text(strip=True)
            
            logger.info(f"📛 Company name: {company_name}")
            
            # STEP 3: Extract homepage text
            homepage_text = self._extract_text_from_html(soup)
            all_text = [homepage_text]
            
            logger.info(f"📝 Homepage text: {len(homepage_text)} chars")
            
            # STEP 4: Find relevant service pages
            relevant_links = self._get_relevant_links(url, soup)
            logger.info(f"🔗 Found {len(relevant_links)} relevant pages")
            
            # STEP 5: Fetch all relevant pages (parallel)
            async with httpx.AsyncClient() as client:
                tasks = [self._fetch_page(link, client) for link in relevant_links]
                pages_html = await asyncio.gather(*tasks)
            
            # STEP 6: Extract text from all pages
            successfully_scraped = 0
            for i, page_html in enumerate(pages_html):
                if page_html:
                    page_soup = BeautifulSoup(page_html, 'html.parser')
                    page_text = self._extract_text_from_html(page_soup)
                    if len(page_text) > 100:  # Only add if meaningful content
                        all_text.append(page_text)
                        successfully_scraped += 1
                        logger.info(f"  ✅ Page {i+1}: {len(page_text)} chars")
            
            logger.info(f"📚 Successfully scraped {successfully_scraped}/{len(relevant_links)} additional pages")
            
            # STEP 7: Combine all text
            combined_text = ' '.join(all_text)
            
            # STEP 8: Truncate if too long
            max_chars = 35000  # Increased for more context
            if len(combined_text) > max_chars:
                combined_text = combined_text[:max_chars] + "..."
                logger.info(f"✂️ Truncated from {len(combined_text)} to {max_chars} chars")
            
            logger.info(f"✅ COMPLETE: {len(all_text)} pages, {len(combined_text)} chars total")
            
            return {
                "success": True,
                "company_name": company_name,
                "capabilities_text": combined_text,
                "pages_scraped": len(all_text),
                "error": None
            }
                
        except Exception as e:
            logger.error(f"❌ Scraping error: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "company_name": "",
                "capabilities_text": "",
                "pages_scraped": 0
            }