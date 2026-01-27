"""
Test script to validate SAM.gov web scraping using Playwright.
Playwright runs a real headless browser to execute JavaScript.

Usage:
    pip install playwright
    playwright install chromium
    python test_sam_scraper_playwright.py <NoticeId>
    
Example:
    python test_sam_scraper_playwright.py 12c167468aff46b4a22e5b3c38fb9a2e
"""

import sys
import asyncio
import json
from playwright.async_api import async_playwright

async def scrape_sam_opportunity(notice_id: str) -> dict:
    """
    Scrape SAM.gov opportunity page using Playwright headless browser.
    
    Args:
        notice_id: The NoticeId from SAM.gov CSV
        
    Returns:
        Dict with attachments, description, and metadata
    """
    url = f"https://sam.gov/opp/{notice_id}/view"
    
    print(f"🌐 Loading: {url}")
    print("⏳ Starting headless browser...")
    print()
    
    async with async_playwright() as p:
        # Launch browser (headless=False to see it in action, set to True for production)
        browser = await p.chromium.launch(headless=False)  # Set to True for production
        page = await browser.new_page()
        
        # Set viewport and user agent
        await page.set_viewport_size({"width": 1920, "height": 1080})
        
        try:
            # Navigate to page
            print("📄 Navigating to page...")
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Wait for content to load (adjust selector based on what we find)
            print("⏳ Waiting for content to load...")
            await page.wait_for_timeout(5000)  # Wait 5 seconds for JS to execute
            
            # Get page title
            page_title = await page.title()
            print(f"✅ Page Title: {page_title}")
            print()
            
            # Try to find attachment links
            # Strategy 1: Look for any links with .pdf or download
            attachments = []
            
            all_links = await page.locator('a').all()
            print(f"🔗 Found {len(all_links)} total links on page")
            
            for link in all_links:
                try:
                    href = await link.get_attribute('href')
                    text = await link.inner_text()
                    
                    if href and any(ext in href.lower() for ext in ['.pdf', '.doc', '.docx', 'download', 'attachment']):
                        attachments.append({
                            'text': text.strip(),
                            'href': href,
                            'full_url': href if href.startswith('http') else f"https://sam.gov{href}"
                        })
                except:
                    continue
            
            print(f"📎 Found {len(attachments)} potential attachment links")
            print()
            
            if attachments:
                print("📋 Potential Attachments:")
                for i, att in enumerate(attachments[:10], 1):
                    print(f"   {i}. {att['text'][:60]}")
                    print(f"      URL: {att['full_url'][:80]}...")
                    print()
            
            # Get full page content for inspection
            full_html = await page.content()
            
            # Save HTML for debugging
            with open('sam_page_playwright.html', 'w', encoding='utf-8') as f:
                f.write(full_html)
            print("💾 Saved full HTML to: sam_page_playwright.html")
            print()
            
            # Take a screenshot
            await page.screenshot(path='sam_page_screenshot.png', full_page=True)
            print("📸 Saved screenshot to: sam_page_screenshot.png")
            print()
            
            # Try to find specific sections by common patterns
            # Look for text containing "attachment", "document", "download"
            description_text = ""
            try:
                # Try to find main content area
                main_content = await page.locator('main, [role="main"], .main-content').first.inner_text()
                description_text = main_content[:1000] if main_content else ""
            except:
                pass
            
            await browser.close()
            
            return {
                "notice_id": notice_id,
                "url": url,
                "page_title": page_title,
                "attachments": attachments,
                "description_preview": description_text[:500] if description_text else "No description found",
                "total_links": len(all_links),
                "html_saved": "sam_page_playwright.html",
                "screenshot_saved": "sam_page_screenshot.png"
            }
            
        except Exception as e:
            await browser.close()
            print(f"❌ Error: {str(e)}")
            return {"error": str(e)}


async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_sam_scraper_playwright.py <NoticeId>")
        print("\nExample:")
        print("  python test_sam_scraper_playwright.py 12c167468aff46b4a22e5b3c38fb9a2e")
        sys.exit(1)
    
    notice_id = sys.argv[1]
    
    print("=" * 70)
    print("SAM.gov Playwright Scraper Test")
    print("=" * 70)
    print()
    
    result = await scrape_sam_opportunity(notice_id)
    
    print("=" * 70)
    print("Results Summary")
    print("=" * 70)
    print()
    print(json.dumps(result, indent=2, default=str))
    print()
    
    if result.get('attachments'):
        print("✅ SUCCESS: Found attachment links!")
        print("   Check sam_page_screenshot.png to see what the page looks like")
        print("   Check sam_page_playwright.html for the full HTML")
    else:
        print("⚠️  No attachments found")
        print("   Check sam_page_screenshot.png to see the actual page")
        print("   We may need to adjust our selectors")


if __name__ == "__main__":
    asyncio.run(main())