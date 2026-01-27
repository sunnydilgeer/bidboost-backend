"""
Quick test: Scrape SAM.gov and download attachments for a single contract.
Uses network interception to catch the attachments API call.

Usage:
    python test_sam_download.py <NoticeId>
    
Example:
    python test_sam_download.py 12c167468aff46b4a22e5b3c38fb9a2e
"""

import sys
import asyncio
import logging
from pathlib import Path
from playwright.async_api import async_playwright
import httpx
import json

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


async def scrape_and_download(notice_id: str):
    """Scrape SAM.gov and download attachments."""
    
    url = f"https://sam.gov/opp/{notice_id}/view"
    download_dir = Path("./downloads")
    download_dir.mkdir(exist_ok=True)
    
    print("=" * 70)
    print(f"🌐 Testing SAM.gov Scraper")
    print("=" * 70)
    print(f"Notice ID: {notice_id}")
    print(f"URL: {url}")
    print(f"Download Dir: {download_dir.absolute()}")
    print()
    
    # Store attachments from API calls
    attachments_from_api = []
    
    async with async_playwright() as p:
        # Launch browser
        print("🚀 Launching browser...")
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Intercept network requests to catch attachments API
        async def handle_response(response):
            # Look for API calls that might contain attachments
            if 'api' in response.url and ('attachment' in response.url.lower() or 'file' in response.url.lower() or 'resource' in response.url.lower()):
                print(f"🔍 Found API call: {response.url[:100]}...")
                try:
                    data = await response.json()
                    # Save for inspection
                    with open('api_response.json', 'w') as f:
                        json.dump(data, f, indent=2)
                    print(f"   💾 Saved API response to api_response.json")
                except:
                    pass
        
        page.on('response', handle_response)
        
        try:
            # Navigate to page
            print(f"📄 Loading page...")
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Get title
            title = await page.title()
            print(f"✅ Page loaded: {title}")
            print()
            
            # Wait for main content
            await page.wait_for_selector('h1', timeout=10000)
            
            # Get opportunity title
            h1 = await page.locator('h1').inner_text()
            print(f"📋 Opportunity: {h1[:80]}...")
            print()
            
            # STRATEGY 1: Wait LONGER for spinner to disappear
            print("⏳ Waiting for attachments section to load (up to 60 seconds)...")
            
            try:
                await page.wait_for_selector('.fa-spinner', state='detached', timeout=60000)
                print("✅ Spinner disappeared - attachments should be loaded")
            except:
                print("⚠️  Spinner still present after 60 seconds")
            
            # STRATEGY 2: Wait for actual attachment links to appear
            print("⏳ Waiting for attachment links to appear...")
            try:
                await page.wait_for_selector('#attachments-links a[href*="file"], #attachments-links a[href*="download"], #attachments-links a[href*=".pdf"]', timeout=30000)
                print("✅ Found attachment links!")
            except:
                print("⚠️  No attachment links appeared")
            
            # STRATEGY 3: Check for "no attachments" message
            try:
                no_attachments = await page.locator('text=/no attachments/i').count()
                if no_attachments > 0:
                    print("ℹ️  Page says 'No attachments'")
            except:
                pass
            
            # Wait a bit more for good measure
            await asyncio.sleep(5)
            
            # Extract attachment links
            print()
            print("🔍 Looking for attachment links...")
            
            # Get the attachments section
            attachment_section = page.locator('#attachments-links')
            
            # Strategy A: Look for ANY links in attachments section
            all_links = await attachment_section.locator('a').all()
            
            attachments = []
            for link in all_links:
                try:
                    href = await link.get_attribute('href')
                    text = await link.inner_text()
                    
                    if href and text:
                        # Make absolute URL
                        if href.startswith('/'):
                            href = f"https://sam.gov{href}"
                        elif not href.startswith('http'):
                            continue
                        
                        attachments.append({
                            'filename': text.strip(),
                            'url': href
                        })
                        print(f"   Found: {text.strip()}")
                except:
                    continue
            
            # Strategy B: Look for download buttons
            download_buttons = await page.locator('button:has-text("Download"), a:has-text("Download")').all()
            print(f"   Found {len(download_buttons)} download buttons")
            
            print()
            print(f"📎 Total attachment links found: {len(attachments)}")
            print()
            
            if attachments:
                print("Attachments:")
                for i, att in enumerate(attachments, 1):
                    print(f"  {i}. {att['filename']}")
                    print(f"     URL: {att['url'][:80]}...")
                print()
                
                # Download attachments
                print("💾 Downloading attachments...")
                print()
                
                async with httpx.AsyncClient(timeout=60.0) as client:
                    for i, att in enumerate(attachments, 1):
                        filename = att['filename']
                        url = att['url']
                        
                        # Clean filename
                        safe_filename = "".join(c for c in filename if c.isalnum() or c in (' ', '.', '_', '-'))
                        if not safe_filename.endswith('.pdf'):
                            safe_filename += '.pdf'
                        
                        filepath = download_dir / safe_filename
                        
                        try:
                            print(f"  Downloading {i}/{len(attachments)}: {filename}")
                            
                            response = await client.get(url, follow_redirects=True)
                            response.raise_for_status()
                            
                            with open(filepath, 'wb') as f:
                                f.write(response.content)
                            
                            size_kb = len(response.content) / 1024
                            print(f"    ✅ Saved: {filepath.name} ({size_kb:.1f} KB)")
                        
                        except Exception as e:
                            print(f"    ❌ Failed: {str(e)}")
                
                print()
                print("=" * 70)
                print("✅ TEST COMPLETE")
                print("=" * 70)
                print(f"Downloaded {len(attachments)} files to: {download_dir.absolute()}")
            
            else:
                print("❌ No attachments found")
                print()
                print("Debugging info:")
                
                # Get the HTML of attachments section
                html = await attachment_section.inner_html()
                print(f"Attachments section HTML:")
                print(html)
                print()
                
                # Get ALL links on the page (debug)
                all_page_links = await page.locator('a').all()
                print(f"Total links on page: {len(all_page_links)}")
                
                pdf_links = []
                for link in all_page_links:
                    href = await link.get_attribute('href')
                    if href and ('.pdf' in href.lower() or 'download' in href.lower() or 'file' in href.lower()):
                        text = await link.inner_text()
                        pdf_links.append((text[:50], href[:80]))
                
                if pdf_links:
                    print(f"\nFound {len(pdf_links)} potential file links elsewhere on page:")
                    for text, href in pdf_links[:5]:
                        print(f"  - {text}: {href}")
                
                # Save full page for inspection
                full_html = await page.content()
                debug_file = Path("debug_sam_page.html")
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(full_html)
                print(f"\n💾 Saved full page to: {debug_file.absolute()}")
                print("   Open this file and search for 'attachment' or '.pdf'")
                
                # Take screenshot
                screenshot_file = Path("debug_sam_screenshot.png")
                await page.screenshot(path=str(screenshot_file), full_page=True)
                print(f"📸 Saved screenshot to: {screenshot_file.absolute()}")
        
        finally:
            # Keep browser open for manual inspection
            print()
            print("🔍 Browser will stay open for 10 seconds for manual inspection...")
            await asyncio.sleep(10)
            await browser.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_sam_download.py <NoticeId>")
        print()
        print("Example:")
        print("  python test_sam_download.py 12c167468aff46b4a22e5b3c38fb9a2e")
        sys.exit(1)
    
    notice_id = sys.argv[1]
    asyncio.run(scrape_and_download(notice_id))


if __name__ == "__main__":
    main()