"""
Selenium-based SAM.gov scraper - Updated for scraped_at tracking
Scrapes LIVE opportunities only with rate limiting and deduplication.

Usage:
    python scrape_sam_with_selenium.py --limit 190
"""

import argparse
import time
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime, timezone
import re
import random
import os

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

import requests
import docx
import fitz
from openai import OpenAI
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.database import SessionLocal
from app.models.company import OpportunityChain


def get_contracts_to_scrape(session: Session, limit: int = 190) -> List[OpportunityChain]:
    """
    Get POOR/MISSING contracts that match LIVE ingestion filters.
    
    Filters:
    - Quality: POOR or MISSING
    - Closing date: Future (LIVE opportunities only)
    - BaseType: Solicitation or Combined Synopsis/Solicitation
    - Never scraped: scraped_at IS NULL
    """
    now = datetime.now(timezone.utc)
    
    query = session.query(OpportunityChain).filter(
        and_(
            # Quality filters
            OpportunityChain.base_description_quality.in_(['POOR', 'MISSING']),
            
            # LIVE filter - closing date in future
            OpportunityChain.latest_closing_date >= now,
            
            # Base type filter (matches ingestion)
            OpportunityChain.base_type.in_(['Solicitation', 'Combined Synopsis/Solicitation']),
            
            # Deduplication - never scraped before
            OpportunityChain.scraped_at == None
        )
    ).limit(limit)
    
    return query.all()


def setup_driver():
    """Setup headless Chrome driver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def extract_download_links(notice_id: str, debug: bool = False, follow_chain: bool = True) -> List[Dict]:
    """
    Use Selenium to load SAM.gov page and extract attachment download links.
    If no attachments found and follow_chain=True, look for predecessor notices.
    """
    driver = setup_driver()
    attachments = []
    
    try:
        url = f"https://sam.gov/opp/{notice_id}/view"
        print(f"   🌐 Loading: {url}")
        
        driver.get(url)
        time.sleep(5)
        
        # Click Attachments/Links tab
        print(f"   🖱️  Clicking 'Attachments/Links' tab...")
        try:
            attachment_tab = driver.find_element(By.LINK_TEXT, "Attachments/Links")
            attachment_tab.click()
            time.sleep(3)
        except:
            pass
        
        # Try to find attachments
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            
            for row in rows:
                try:
                    links_in_row = row.find_elements(By.TAG_NAME, "a")
                    
                    for link in links_in_row:
                        href = link.get_attribute("href")
                        text = link.text.strip()
                        
                        if href and text and len(text) > 3:
                            attachments.append({
                                'filename': text,
                                'url': href
                            })
                            print(f"      📎 Found: {text}")
                except:
                    continue
                    
        except:
            pass
        
        # If no attachments and follow_chain enabled, look for predecessor
        if not attachments and follow_chain:
            print(f"   🔗 No attachments - searching for predecessor notice...")
            
            try:
                # Click History tab
                history_tab = driver.find_element(By.LINK_TEXT, "History")
                history_tab.click()
                time.sleep(2)
                
                # Look for links with "Original", "Combined Synopsis", "Presolicitation"
                history_links = driver.find_elements(By.TAG_NAME, "a")
                
                for link in history_links:
                    text = link.text.strip()
                    href = link.get_attribute("href")
                    
                    # Look for original/base notices
                    if any(keyword in text for keyword in ['Original', 'Combined Synopsis', 'Presolicitation', 'Solicitation']):
                        if '/opp/' in href and 'view' in href:
                            # Extract notice ID from URL
                            match = re.search(r'/opp/([a-f0-9]+)/view', href)
                            if match:
                                predecessor_id = match.group(1)
                                
                                if predecessor_id != notice_id:  # Don't follow self
                                    print(f"      ↪️  Found predecessor: {predecessor_id}")
                                    print(f"         Type: {text[:50]}")
                                    
                                    # Recursively get attachments from predecessor (but don't follow chain again)
                                    driver.quit()
                                    return extract_download_links(predecessor_id, debug=False, follow_chain=False)
            except Exception as e:
                print(f"      ⚠️  Could not check history: {str(e)[:100]}")
        
        if attachments:
            print(f"   ✅ Extracted {len(attachments)} attachment(s)")
        else:
            print(f"   ⚠️  No attachments found")
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)[:200]}")
    
    finally:
        driver.quit()
    
    return attachments


def download_file(url: str, filename: str, cache_dir: Path) -> Optional[Path]:
    """Download file from URL."""
    try:
        # Sanitize filename
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', filename)[:180]
        if not any(safe_name.endswith(ext) for ext in ['.pdf', '.docx', '.doc']):
            # Guess extension from URL or filename
            if '.pdf' in url.lower() or '.pdf' in filename.lower():
                safe_name += '.pdf'
            elif '.docx' in url.lower() or '.docx' in filename.lower():
                safe_name += '.docx'
            else:
                safe_name += '.pdf'
        
        filepath = cache_dir / safe_name
        
        # Check cache
        if filepath.exists():
            print(f"      ✅ Found in cache")
            return filepath
        
        print(f"      📥 Downloading...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        response.raise_for_status()
        
        # Validate response
        if 'text/html' in response.headers.get('content-type', ''):
            print(f"      ⚠️  Got HTML instead of file")
            return None
        
        # Save
        with open(filepath, 'wb') as f:
            f.write(response.content)
        
        print(f"      ✅ Downloaded ({len(response.content) / 1024:.1f} KB)")
        return filepath
        
    except Exception as e:
        print(f"      ❌ Download failed: {str(e)[:100]}")
        return None


def extract_text_from_file(file_path: Path) -> Optional[str]:
    """Extract text from PDF or DOCX."""
    try:
        ext = file_path.suffix.lower()
        
        if ext == '.pdf':
            doc = fitz.open(file_path)
            text_parts = []
            for i in range(min(20, len(doc))):
                text_parts.append(doc[i].get_text())
            doc.close()
            text = "\n".join(text_parts)
            
        elif ext in ['.docx', '.doc']:
            doc = docx.Document(file_path)
            text_parts = [p.text for p in doc.paragraphs]
            text = "\n".join(text_parts)
            
        else:
            return None
        
        # Clean
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text if len(text) > 500 else None
        
    except Exception as e:
        print(f"      ⚠️  Extraction error: {str(e)[:100]}")
        return None


def extract_sow_with_gpt(text: str, openai_client: OpenAI) -> Optional[str]:
    """Use GPT to extract SOW."""
    if len(text) > 12000:
        text = text[:12000] + "\n\n[Text truncated...]"
    
    prompt = f"""Extract the Statement of Work (SOW) or Performance Work Statement (PWS) from this government contract document.

{text}

Provide a clear 2-3 paragraph summary of:
- What services/products are being procured
- Scope of work and requirements
- Deliverables

If NO useful SOW exists, respond: NO_SOW_FOUND"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a government contracting expert."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=600
        )
        
        extracted = response.choices[0].message.content.strip()
        
        if "NO_SOW_FOUND" in extracted or len(extracted) < 100:
            return None
        
        return extracted
        
    except Exception as e:
        print(f"      ⚠️  GPT error: {str(e)[:100]}")
        return None


def assess_quality(description: str) -> str:
    """Assess description quality."""
    if not description or len(description) < 50:
        return "POOR"
    if any(kw in description.lower() for kw in ['see attached', 'refer to']):
        return "POOR"
    return "GOOD"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=190, help="Number of contracts to process")
    parser.add_argument('--debug', action='store_true', help="Save screenshots and HTML")
    args = parser.parse_args()
    
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    cache_dir = Path("./selenium_cache")
    cache_dir.mkdir(exist_ok=True)
    
    db = SessionLocal()
    
    print("=" * 70)
    print("SELENIUM-BASED SAM.GOV SCRAPER")
    print("=" * 70)
    print()
    
    # Get LIVE POOR/MISSING contracts that haven't been scraped
    contracts = get_contracts_to_scrape(db, limit=args.limit)
    
    print(f"📊 Found {len(contracts)} LIVE POOR/MISSING contracts to scrape")
    print(f"   (Active=Yes, Closing Date >= Today, Never Scraped)")
    if args.debug:
        print(f"🐛 Debug mode enabled")
    print()
    
    if len(contracts) == 0:
        print("✅ No contracts need scraping!")
        db.close()
        return
    
    improved_count = 0
    no_attachments_count = 0
    failed_count = 0
    
    for idx, contract in enumerate(contracts, 1):
        print(f"[{idx}/{len(contracts)}] {contract.solicitation_number}")
        print(f"   Notice: {contract.base_notice_id}")
        print(f"   Closing: {contract.latest_closing_date.strftime('%Y-%m-%d')}")
        
        # ✅ CRITICAL: Mark as scraped (even if no attachments)
        contract.scraped_at = datetime.now(timezone.utc)
        
        # Extract download links with Selenium
        attachments = extract_download_links(contract.base_notice_id, debug=args.debug)
        
        if not attachments:
            no_attachments_count += 1
            print(f"   ❌ No attachments")
            db.commit()  # Save the scraped_at timestamp
            
            # CRITICAL: Rate limiting
            if idx < len(contracts):
                sleep_time = random.uniform(10, 15)
                print(f"   ⏳ Waiting {sleep_time:.1f}s before next request...")
                time.sleep(sleep_time)
            print()
            continue
        
        # Try to download and process
        extracted_sow = None
        
        for att in attachments:
            filename = att['filename']
            url = att['url']
            
            print(f"   📄 {filename}")
            
            # Download
            file_path = download_file(url, filename, cache_dir)
            
            if not file_path:
                continue
            
            # Extract text
            print(f"      📖 Extracting text...")
            text = extract_text_from_file(file_path)
            
            if not text:
                print(f"      ⚠️  No text extracted")
                continue
            
            # GPT extraction
            print(f"      🤖 Using GPT...")
            extracted_sow = extract_sow_with_gpt(text, openai_client)
            
            if extracted_sow:
                print(f"      ✅ Found SOW!")
                break
        
        # Update database
        if extracted_sow and assess_quality(extracted_sow) == "GOOD":
            contract.base_description = extracted_sow
            contract.base_description_quality = "GOOD"
            contract.needs_sow_extraction = False
            contract.updated_at = datetime.now(timezone.utc)
            
            improved_count += 1
            
            preview = extracted_sow[:150] + "..." if len(extracted_sow) > 150 else extracted_sow
            print(f"   ✅ IMPROVED TO GOOD")
            print(f"      {preview}")
        else:
            failed_count += 1
            if extracted_sow:
                print(f"   ⚠️  Extracted but still POOR quality")
            else:
                print(f"   ❌ Could not extract SOW")
        
        # Commit every 5 contracts
        if idx % 5 == 0:
            db.commit()
        
        # CRITICAL: Rate limiting (avoid SAM.gov blocks)
        if idx < len(contracts):
            sleep_time = random.uniform(10, 15)
            print(f"   ⏳ Waiting {sleep_time:.1f}s before next request...")
            time.sleep(sleep_time)
        
        print()
    
    db.commit()
    
    print("=" * 70)
    print("✅ SELENIUM SCRAPING COMPLETE")
    print("=" * 70)
    print(f"   Improved to GOOD: {improved_count}")
    print(f"   No attachments found: {no_attachments_count}")
    print(f"   Failed extraction: {failed_count}")
    print(f"   Total processed: {len(contracts)}")
    
    if len(contracts) > 0:
        success_rate = (improved_count / len(contracts)) * 100
        print(f"   Success rate: {success_rate:.1f}%")
    
    print()
    
    # Show overall stats for LIVE opportunities only
    from sqlalchemy import func
    now = datetime.now(timezone.utc)
    
    stats = db.query(
        OpportunityChain.base_description_quality,
        func.count(OpportunityChain.id)
    ).filter(
        OpportunityChain.latest_closing_date >= now
    ).group_by(OpportunityChain.base_description_quality).all()
    
    total = sum(count for _, count in stats)
    print("📊 Overall Quality (LIVE Opportunities Only):")
    for quality, count in stats:
        pct = (count / total * 100) if total > 0 else 0
        print(f"   {quality}: {count} ({pct:.1f}%)")
    
    db.close()


if __name__ == "__main__":
    main()