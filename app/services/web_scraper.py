"""
Web scraping service for extracting company capabilities from websites
Ultra-enhanced to thoroughly explore navigation menus and service pages
"""
import logging
from typing import Dict, List, Optional, Set
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import asyncio
import re

logger = logging.getLogger(__name__)

class WebScraperService:
    """Extract company information with comprehensive navigation exploration"""
    
    def __init__(self):
        self.timeout = 15.0
        self.max_pages = 12  # Increased for thorough coverage
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
    
    def _should_skip_url(self, url: str) -> bool:
        """Skip non-content URLs"""
        skip_patterns = [
            '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip', '.doc', '.xls',
            '/login', '/signin', '/signup', '/cart', '/checkout', '/account',
            '/contact', '/careers', '/jobs', '/blog', '/news', '/press',
            '#', 'javascript:', 'mailto:', 'tel:'
        ]
        url_lower = url.lower()
        return any(pattern in url_lower for pattern in skip_patterns)
    
    def _extract_all_navigation_links(self, base_url: str, soup: BeautifulSoup) -> Set[str]:
        """
        COMPREHENSIVE navigation link extraction
        Looks everywhere: nav, header, footer, menu classes, dropdowns
        """
        found_links = set()
        base_netloc = urlparse(base_url).netloc
        
        # 1. PRIMARY: Extract from <nav> elements
        nav_elements = soup.find_all('nav')
        logger.info(f"🧭 Found {len(nav_elements)} <nav> elements")
        for nav in nav_elements:
            for a_tag in nav.find_all('a', href=True):
                href = a_tag['href']
                full_url = urljoin(base_url, href)
                if urlparse(full_url).netloc == base_netloc and not self._should_skip_url(full_url):
                    found_links.add(full_url)
                    logger.debug(f"  📎 Nav link: {full_url}")
        
        # 2. HEADER: Look in <header> element
        headers = soup.find_all('header')
        logger.info(f"📰 Found {len(headers)} <header> elements")
        for header in headers:
            for a_tag in header.find_all('a', href=True):
                href = a_tag['href']
                full_url = urljoin(base_url, href)
                if urlparse(full_url).netloc == base_netloc and not self._should_skip_url(full_url):
                    found_links.add(full_url)
        
        # 3. MENU CLASSES: Look for common menu/navigation class patterns
        menu_patterns = [
            'menu', 'navigation', 'nav-menu', 'main-menu', 'primary-menu',
            'navbar', 'nav-bar', 'site-nav', 'header-nav', 'top-menu',
            'mega-menu', 'dropdown', 'submenu', 'sub-menu'
        ]
        for pattern in menu_patterns:
            elements = soup.find_all(class_=re.compile(pattern, re.I))
            for elem in elements:
                for a_tag in elem.find_all('a', href=True):
                    href = a_tag['href']
                    full_url = urljoin(base_url, href)
                    if urlparse(full_url).netloc == base_netloc and not self._should_skip_url(full_url):
                        found_links.add(full_url)
        
        # 4. ROLE-BASED: Look for ARIA navigation roles
        aria_nav = soup.find_all(attrs={"role": "navigation"})
        for nav in aria_nav:
            for a_tag in nav.find_all('a', href=True):
                href = a_tag['href']
                full_url = urljoin(base_url, href)
                if urlparse(full_url).netloc == base_netloc and not self._should_skip_url(full_url):
                    found_links.add(full_url)
        
        # 5. LIST-BASED MENUS: Many sites use <ul> for menus
        list_menus = soup.find_all('ul', class_=re.compile(r'(menu|nav)', re.I))
        for ul in list_menus:
            for a_tag in ul.find_all('a', href=True):
                href = a_tag['href']
                full_url = urljoin(base_url, href)
                if urlparse(full_url).netloc == base_netloc and not self._should_skip_url(full_url):
                    found_links.add(full_url)
        
        logger.info(f"🔗 Extracted {len(found_links)} navigation links")
        return found_links
    
    def _get_common_service_urls(self, base_url: str) -> Set[str]:
        """Generate common service page URL patterns"""
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        # Comprehensive list of common paths
        common_paths = [
            # Services
            '/services', '/our-services', '/solutions', '/offerings',
            '/capabilities', '/what-we-do', '/expertise',
            # Technology
            '/products', '/platforms', '/technology', '/tech-stack',
            '/software', '/tools', '/applications',
            # Consulting
            '/consulting', '/advisory', '/professional-services',
            # Industries
            '/industries', '/sectors', '/verticals',
            # Specific tech (common)
            '/cloud', '/data', '/ai', '/ml', '/analytics', '/cybersecurity',
            '/digital', '/digital-transformation', '/innovation',
            # About variations
            '/about', '/about-us', '/who-we-are', '/company',
            # Workday specific (since user mentioned it)
            '/workday', '/salesforce', '/oracle', '/sap', '/microsoft'
        ]
        
        return {f"{base}{path}" for path in common_paths}
    
    def _score_link_relevance(self, url: str, link_text: str) -> int:
        """
        Score a link's relevance for capability extraction
        Higher score = more relevant
        """
        score = 0
        url_lower = url.lower()
        text_lower = link_text.lower()
        combined = url_lower + " " + text_lower
        
        # HIGH PRIORITY: Explicit service/solution pages
        high_priority = ['service', 'solution', 'offering', 'capabilit']
        for keyword in high_priority:
            if keyword in combined:
                score += 10
        
        # MEDIUM PRIORITY: Products, platforms, technology
        medium_priority = ['product', 'platform', 'technolog', 'software', 'tool']
        for keyword in medium_priority:
            if keyword in combined:
                score += 7
        
        # GOOD: Industry, consulting, expertise
        good_keywords = ['industr', 'consult', 'expertise', 'advisory']
        for keyword in good_keywords:
            if keyword in combined:
                score += 5
        
        # RELEVANT: Specific technologies
        tech_keywords = ['cloud', 'data', 'ai', 'analytics', 'cyber', 'digital', 
                        'workday', 'salesforce', 'oracle', 'sap', 'aws', 'azure']
        for keyword in tech_keywords:
            if keyword in combined:
                score += 4
        
        # BONUS: About pages (usually have overview)
        if 'about' in combined:
            score += 3
        
        # PENALTY: Generic/navigation pages
        penalty_keywords = ['home', 'contact', 'blog', 'news', 'career']
        for keyword in penalty_keywords:
            if keyword in combined:
                score -= 5
        
        return score
    
    def _prioritize_links(self, base_url: str, soup: BeautifulSoup, nav_links: Set[str]) -> List[str]:
        """
        Intelligently prioritize which links to scrape
        Combines navigation links + common patterns + scoring
        """
        # Start with navigation links
        all_candidates = nav_links.copy()
        
        # Add common service URL patterns
        common_urls = self._get_common_service_urls(base_url)
        all_candidates.update(common_urls)
        
        logger.info(f"📊 Total candidate URLs: {len(all_candidates)}")
        
        # Score each link
        scored_links = []
        for url in all_candidates:
            # Try to find the link text in the original page
            link_text = ""
            a_tags = soup.find_all('a', href=lambda x: x and url.endswith(urlparse(x).path))
            if a_tags:
                link_text = a_tags[0].get_text(strip=True)
            
            score = self._score_link_relevance(url, link_text)
            if score > 0:  # Only include if relevant
                scored_links.append((url, score, link_text))
        
        # Sort by score (highest first)
        scored_links.sort(key=lambda x: x[1], reverse=True)
        
        # Log top candidates
        logger.info(f"🎯 Top priority links:")
        for url, score, text in scored_links[:10]:
            logger.info(f"  [{score:2d}] {text[:30]:30s} → {url}")
        
        # Return top N URLs
        return [url for url, score, text in scored_links[:self.max_pages - 1]]
    
    def _extract_text_from_html(self, soup: BeautifulSoup) -> str:
        """Enhanced text extraction with service-focused approach"""
        # Remove noise
        for element in soup(['script', 'style', 'footer', 'cookie', 'banner']):
            element.decompose()
        
        text_parts = []
        
        # 1. MAIN CONTENT
        main = soup.find('main') or soup.find('article') or soup.find(id='content')
        if main:
            text_parts.append(main.get_text(separator=' ', strip=True))
        
        # 2. SERVICE SECTIONS (look for class patterns)
        service_patterns = ['service', 'solution', 'product', 'offering', 
                          'capability', 'expertise', 'feature']
        for pattern in service_patterns:
            sections = soup.find_all(class_=re.compile(pattern, re.I))
            for section in sections:
                text = section.get_text(separator=' ', strip=True)
                if len(text) > 50:
                    text_parts.append(text)
        
        # 3. STRUCTURED CONTENT (headings + following content)
        for heading in soup.find_all(['h1', 'h2', 'h3']):
            h_text = heading.get_text(strip=True)
            if h_text:
                text_parts.append(h_text)
                # Get content after heading
                for sibling in heading.find_next_siblings(['p', 'ul', 'ol', 'div'])[:3]:
                    text_parts.append(sibling.get_text(separator=' ', strip=True))
        
        # 4. LISTS (often contain services)
        for ul in soup.find_all(['ul', 'ol']):
            list_text = ul.get_text(separator=' | ', strip=True)
            if len(list_text) > 30:
                text_parts.append(list_text)
        
        # 5. FALLBACK: Body text
        if not text_parts or sum(len(t) for t in text_parts) < 500:
            body = soup.find('body')
            if body:
                text_parts.append(body.get_text(separator=' ', strip=True))
        
        # Combine and clean
        combined = ' '.join(text_parts)
        lines = [line.strip() for line in combined.splitlines() if line.strip()]
        text = ' '.join(lines)
        text = re.sub(r'\s+', ' ', text)
        
        return text
    
    async def _fetch_page(self, url: str, client: httpx.AsyncClient) -> Optional[str]:
        """Fetch a single page"""
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
                return response.text
            return None
        except Exception as e:
            logger.debug(f"Failed to fetch {url}: {e}")
            return None
    
    async def _fetch_page_with_playwright(self, url: str) -> Optional[str]:
        """Fetch page using Playwright"""
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
                await page.wait_for_timeout(3000)
                
                # Scroll to trigger lazy loading
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await page.wait_for_timeout(1000)
                
                content = await page.content()
                await browser.close()
                
                logger.info(f"✅ Playwright rendered {url}")
                return content
                
        except ImportError:
            return None
        except Exception as e:
            logger.debug(f"Playwright failed for {url}: {e}")
            return None
    
    async def scrape_company_website(self, url: str) -> Dict[str, any]:
        """
        Comprehensive website scraping with thorough navigation exploration
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
        
        logger.info(f"🌐 Starting COMPREHENSIVE scrape of: {url}")
        logger.info(f"=" * 70)
        
        try:
            # STEP 1: Fetch homepage
            homepage_html = None
            
            if self.use_playwright:
                logger.info("🎭 Attempting Playwright render...")
                homepage_html = await self._fetch_page_with_playwright(url)
            
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
            
            logger.info(f"📛 Company: {company_name}")
            
            # STEP 3: COMPREHENSIVE navigation link discovery
            logger.info(f"\n{'='*70}")
            logger.info(f"🔍 PHASE 1: DISCOVERING NAVIGATION LINKS")
            logger.info(f"{'='*70}")
            
            nav_links = self._extract_all_navigation_links(url, soup)
            
            # STEP 4: Prioritize and select best links
            logger.info(f"\n{'='*70}")
            logger.info(f"🎯 PHASE 2: PRIORITIZING LINKS")
            logger.info(f"{'='*70}")
            
            priority_links = self._prioritize_links(url, soup, nav_links)
            
            # STEP 5: Extract homepage text
            logger.info(f"\n{'='*70}")
            logger.info(f"📝 PHASE 3: EXTRACTING CONTENT")
            logger.info(f"{'='*70}")
            
            homepage_text = self._extract_text_from_html(soup)
            all_text = [homepage_text]
            logger.info(f"✅ Homepage: {len(homepage_text)} chars")
            
            # STEP 6: Fetch priority pages in parallel
            logger.info(f"\n🌐 Fetching {len(priority_links)} priority pages...")
            
            async with httpx.AsyncClient() as client:
                tasks = [self._fetch_page(link, client) for link in priority_links]
                pages_html = await asyncio.gather(*tasks)
            
            # STEP 7: Extract text from each page
            successfully_scraped = 0
            for i, (page_html, page_url) in enumerate(zip(pages_html, priority_links)):
                if page_html:
                    page_soup = BeautifulSoup(page_html, 'html.parser')
                    page_text = self._extract_text_from_html(page_soup)
                    if len(page_text) > 100:
                        all_text.append(page_text)
                        successfully_scraped += 1
                        logger.info(f"  ✅ Page {i+1}: {len(page_text):,} chars from {urlparse(page_url).path}")
                    else:
                        logger.info(f"  ⚠️  Page {i+1}: Too short ({len(page_text)} chars)")
                else:
                    logger.info(f"  ❌ Page {i+1}: Failed to fetch")
            
            # STEP 8: Combine all text
            combined_text = ' '.join(all_text)
            
            # STEP 9: Truncate if needed
            max_chars = 40000  # Generous limit
            if len(combined_text) > max_chars:
                combined_text = combined_text[:max_chars] + "..."
                logger.info(f"✂️  Truncated from {len(combined_text):,} to {max_chars:,} chars")
            
            logger.info(f"\n{'='*70}")
            logger.info(f"✅ SCRAPING COMPLETE")
            logger.info(f"{'='*70}")
            logger.info(f"📚 Pages scraped: {len(all_text)}")
            logger.info(f"📝 Total content: {len(combined_text):,} characters")
            logger.info(f"✅ Success rate: {successfully_scraped}/{len(priority_links)} priority pages")
            logger.info(f"{'='*70}\n")
            
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