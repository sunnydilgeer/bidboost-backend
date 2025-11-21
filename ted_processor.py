import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timezone, timedelta
import requests
import os

from app.models.schemas import ContractOpportunity

class TEDProcessor:
    def __init__(self, json_file_path: str = "ted_opportunities.json"):
        self.json_file = Path(json_file_path)
        self.deepl_api_key = os.getenv("DEEPL_API_KEY")
        self.target_countries = os.getenv("TED_TARGET_COUNTRIES", "GBR,IRL").split(",")
        self.min_value = float(os.getenv("TED_MIN_VALUE", "0"))
        self.translation_cache = {}
    
    async def fetch_opportunities(self) -> List[ContractOpportunity]:
        """Main processing pipeline"""
        if not self.json_file.exists():
            print(f"TED data file not found: {self.json_file}")
            return []
        
        with open(self.json_file, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        
        opportunities = []
        processed_count = 0
        skipped_non_english = 0
        skipped_expired = 0
        skipped_low_value = 0
        
        for entry in raw_data:
            filter_result = self._should_process_notice(entry)
            if filter_result == "process":
                opp = await self._convert_to_opportunity(entry)
                if opp:
                    opportunities.append(opp)
                    processed_count += 1
            elif filter_result == "non_english":
                skipped_non_english += 1
            elif filter_result == "expired":
                skipped_expired += 1
            elif filter_result == "low_value":
                skipped_low_value += 1
        
        print(f"\n📊 TED Processing Summary:")
        print(f"  Total raw notices: {len(raw_data)}")
        print(f"  ✅ Processed: {processed_count}")
        print(f"  ⏰ Skipped (expired): {skipped_expired}")
        print(f"  💰 Skipped (low value): {skipped_low_value}")
        print(f"  🌍 Skipped (non-English): {skipped_non_english}")
        
        if not self.deepl_api_key and skipped_non_english > 0:
            print(f"\n💡 Tip: Add DEEPL_API_KEY to process {skipped_non_english} non-English notices")
        
        return opportunities
    
    def _should_process_notice(self, entry: Dict) -> str:
        """Filter notices before processing. Returns: 'process', 'expired', 'low_value', 'non_english'"""
        
        # 1. DATE FILTER DISABLED FOR TESTING
        
        # 2. Value threshold - set to 0 in .env to disable
        if entry.get('value'):
            if self.min_value > 0 and entry['value'] < self.min_value:
                return "low_value"
        
        # 3. LANGUAGE FILTER DISABLED FOR TESTING - Accept all languages
        return "process"
    
    async def _convert_to_opportunity(self, entry: Dict) -> Optional[ContractOpportunity]:
        """Convert TED JSON to ContractOpportunity schema"""
        try:
            # Get original text
            title = entry.get('title', '')
            description = entry.get('description', '')
            original_lang = entry.get('original_language', 'EN')
            
            # Translate if needed and DeepL is available
            translated = False
            if original_lang.upper() != 'EN' and self.deepl_api_key:
                print(f"  🌍 Translating {entry.get('notice_id')} from {original_lang}...")
                title = self._translate_text(title, original_lang)
                description = self._translate_text(description, original_lang)
                translated = True
            
            # Fix date formats - convert "2025-11-17+01:00" to "2025-11-17T00:00:00+01:00"
            def fix_date_format(date_str):
                if not date_str:
                    return None
                # If date has timezone but no time, add midnight time
                if '+' in date_str and 'T' not in date_str:
                    parts = date_str.split('+')
                    return f"{parts[0]}T00:00:00+{parts[1]}"
                elif date_str.endswith('Z') and 'T' not in date_str:
                    return f"{date_str[:-1]}T00:00:00Z"
                return date_str
            
            published_date = fix_date_format(entry.get('published_date'))
            closing_date = fix_date_format(entry.get('closing_date'))
            
            # Fix links - convert list to string (take first link or None)
            links_list = entry.get('links', [])
            links_str = links_list[0] if links_list else None
            
            return ContractOpportunity(
                notice_id=entry['notice_id'],
                title=title[:500] if title else "Untitled",
                description=description,
                published_date=published_date,
                closing_date=closing_date,
                value=entry.get('value'),
                buyer_name=entry.get('buyer_name', 'Unknown'),
                cpv_codes=entry.get('cpv_codes', []),
                region=", ".join(entry.get('region', [])) if entry.get('region') else None,
                contact_email=entry.get('contact_email'),
                contact_phone=entry.get('contact_phone'),
                links=links_str,
                source="TED",
                document_type="contract_opportunity",
                metadata={
                    "original_language": original_lang,
                    "translated": translated,
                    "available_languages": entry.get('available_languages', []),
                    "closing_time": entry.get('closing_time'),
                    "all_links": links_list
                }
            )
        except Exception as e:
            print(f"❌ Error converting notice {entry.get('notice_id')}: {e}")
            return None
    
    def _translate_text(self, text: str, source_lang: str) -> str:
        """Translate text using DeepL API with caching"""
        if not text or len(text) < 10:
            return text
        
        # Truncate very long text
        if len(text) > 5000:
            text = text[:5000] + "..."
        
        # Check cache
        cache_key = f"{source_lang}:{text[:50]}"
        if cache_key in self.translation_cache:
            return self.translation_cache[cache_key]
        
        try:
            response = requests.post(
                'https://api-free.deepl.com/v2/translate',
                data={
                    'auth_key': self.deepl_api_key,
                    'text': text,
                    'source_lang': source_lang.upper(),
                    'target_lang': 'EN-GB'
                },
                timeout=10
            )
            response.raise_for_status()
            translated = response.json()['translations'][0]['text']
            
            # Cache result
            self.translation_cache[cache_key] = translated
            return translated
        except Exception as e:
            print(f"⚠️  Translation failed for {source_lang}: {e}")
            return text


async def test_processor():
    """Quick test of TED processor"""
    processor = TEDProcessor()
    opportunities = await processor.fetch_opportunities()
    
    print(f"\n✅ Successfully processed {len(opportunities)} opportunities")
    
    if opportunities:
        print("\n📋 Sample (first 3):")
        for i, opp in enumerate(opportunities[:3], 1):
            print(f"\n{i}. {opp.title[:80]}")
            print(f"   Buyer: {opp.buyer_name}")
            print(f"   Value: €{opp.value:,.2f}" if opp.value else "   Value: N/A")
            print(f"   Deadline: {opp.closing_date}")
            print(f"   Lang: {opp.metadata.get('original_language')} | Translated: {opp.metadata.get('translated')}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_processor())