import requests
import json
from pathlib import Path
from datetime import datetime, timedelta
import time

class TEDSearchScraper:
    """Scrape TED using the Search API instead of daily packages"""
    SEARCH_API_URL = "https://ted.europa.eu/api/v3/notices/search"
    OUTPUT_DIR = Path("ted_data")
    
    def __init__(self):
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    def search_recent_notices(self, days_back: int = 7, country_codes: list = None) -> list:
        """
        Search for recent TED notices using the Search API
        
        Args:
            days_back: How many days back to search
            country_codes: List of ISO country codes (e.g., ['GBR', 'IRL'])
        """
        if country_codes is None:
            country_codes = ['GBR', 'IRL']
        
        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        # Build query for UK/Ireland relevant tenders
        # RC = Country code filter
        country_query = " OR ".join([f"RC=[{code}]" for code in country_codes])
        
        # PD = Publication date
        date_query = f"PD=[{start_date.strftime('%Y%m%d')} <> {end_date.strftime('%Y%m%d')}]"
        
        # Combine queries
        query = f"({country_query}) AND {date_query}"
        
        print(f"🔍 Searching TED for: {query}")
        print(f"📅 Date range: {start_date.date()} to {end_date.date()}")
        
        all_notices = []
        page = 1
        page_size = 100
        
        while True:
            params = {
                'q': query,
                'pageNum': page,
                'pageSize': page_size,
                'reverseOrder': False,
                'sortField': 'PD'  # Sort by publication date
            }
            
            try:
                print(f"  Fetching page {page}...")
                response = requests.get(
                    self.SEARCH_API_URL,
                    params=params,
                    headers={
                        'Accept': 'application/json',
                        'User-Agent': 'BidMatch-TED-Scraper/1.0'
                    },
                    timeout=30
                )
                response.raise_for_status()
                
                data = response.json()
                notices = data.get('notices', [])
                
                if not notices:
                    print(f"  No more notices found")
                    break
                
                all_notices.extend(notices)
                print(f"  ✅ Found {len(notices)} notices on page {page}")
                
                # Check if we've reached the end
                total_results = data.get('total', 0)
                if len(all_notices) >= total_results:
                    break
                
                page += 1
                time.sleep(0.5)  # Be nice to the API
                
            except requests.exceptions.RequestException as e:
                print(f"❌ Error fetching page {page}: {e}")
                break
        
        print(f"\n✅ Total notices found: {len(all_notices)}")
        return all_notices
    
    def download_notice_xml(self, notice_id: str) -> str:
        """Download full XML for a specific notice"""
        # Notice ID format: "123456-2024"
        xml_url = f"https://ted.europa.eu/api/v3/notices/{notice_id}"
        
        try:
            response = requests.get(
                xml_url,
                headers={
                    'Accept': 'application/xml',
                    'User-Agent': 'BidMatch-TED-Scraper/1.0'
                },
                timeout=30
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"  ⚠️  Failed to download XML for {notice_id}: {e}")
            return None
    
    def save_search_results(self, notices: list, filename: str = "ted_search_results.json"):
        """Save search results to JSON"""
        output_file = self.OUTPUT_DIR / filename
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(notices, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved {len(notices)} notices to {output_file}")
        return output_file
    
    def download_all_xmls(self, notices: list):
        """Download XML for all notices"""
        xml_dir = self.OUTPUT_DIR / "xml"
        xml_dir.mkdir(exist_ok=True)
        
        print(f"\n📥 Downloading XML files...")
        successful = 0
        
        for i, notice in enumerate(notices, 1):
            notice_id = notice.get('ND')  # Notice ID
            if not notice_id:
                continue
            
            print(f"  [{i}/{len(notices)}] Downloading {notice_id}...")
            
            xml_content = self.download_notice_xml(notice_id)
            if xml_content:
                xml_file = xml_dir / f"{notice_id.replace('-', '_')}.xml"
                with open(xml_file, 'w', encoding='utf-8') as f:
                    f.write(xml_content)
                successful += 1
            
            # Rate limiting
            if i % 10 == 0:
                time.sleep(2)
        
        print(f"\n✅ Downloaded {successful}/{len(notices)} XML files to {xml_dir}")
        return xml_dir


if __name__ == "__main__":
    scraper = TEDSearchScraper()
    
    # Search for notices from last 30 days
    notices = scraper.search_recent_notices(
        days_back=30,
        country_codes=['GBR', 'IRL']
    )
    
    if notices:
        # Save search results
        scraper.save_search_results(notices)
        
        # Optional: Download full XMLs (can be slow for many notices)
        download_xml = input("\n📥 Download full XML files? (y/n): ").lower() == 'y'
        if download_xml:
            scraper.download_all_xmls(notices)