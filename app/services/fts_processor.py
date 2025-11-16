"""
FTS Processor - Converts FTS JSON data to ContractOpportunity and AwardedContract objects
"""
import json
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import re
import logging

from app.models.schemas import ContractOpportunity, AwardedContract

logger = logging.getLogger(__name__)


class FTSProcessor:
    """Process FTS JSON data into structured objects"""
    
    def __init__(self, json_file_path: str = "fts_live_rich.json"):
        self.json_file_path = Path(json_file_path)
        
    async def fetch_opportunities(self) -> List[ContractOpportunity]:
        """Load opportunities from FTS JSON"""
        if not self.json_file_path.exists():
            logger.error(f"FTS JSON file not found: {self.json_file_path}")
            return []
        
        with open(self.json_file_path, 'r') as f:
            data = json.load(f)
        
        opportunities = []
        for entry in data:
            if entry.get('notice_type') == 'opportunity':
                try:
                    opp = self._convert_to_opportunity(entry)
                    if opp:
                        opportunities.append(opp)
                except Exception as e:
                    logger.warning(f"Failed to convert opportunity {entry.get('tender_id')}: {e}")
        
        logger.info(f"Loaded {len(opportunities)} opportunities from FTS")
        return opportunities
    
    async def fetch_awarded_contracts(self) -> List[AwardedContract]:
        """Load awarded contracts from FTS JSON"""
        if not self.json_file_path.exists():
            logger.error(f"FTS JSON file not found: {self.json_file_path}")
            return []
        
        with open(self.json_file_path, 'r') as f:
            data = json.load(f)
        
        awards = []
        for entry in data:
            if entry.get('notice_type') == 'award':
                try:
                    award = self._convert_to_award(entry)
                    if award:
                        awards.append(award)
                except Exception as e:
                    logger.warning(f"Failed to convert award {entry.get('tender_id')}: {e}")
        
        logger.info(f"Loaded {len(awards)} awards from FTS")
        return awards
    
    def _convert_to_opportunity(self, entry: dict) -> Optional[ContractOpportunity]:
        """Convert FTS JSON entry to ContractOpportunity"""
        
        # Parse deadline
        closing_date = None
        closing_time = None
        if entry.get('deadline'):
            closing_date, closing_time = self._parse_deadline(entry['deadline'])
        
        # Parse published_date (required field)
        published_date = self._parse_published_date(entry.get('published_date'))
        
        # Handle links - schema expects Optional[str], not list
        links_list = entry.get('links', [])
        if isinstance(links_list, str):
            links = links_list
        elif isinstance(links_list, list) and links_list:
            links = links_list[0]  # Take first URL
        elif entry.get('url'):
            links = entry.get('url')
        else:
            links = None
        
        return ContractOpportunity(
            notice_id=entry.get('tender_id', ''),
            title=entry.get('title', 'Untitled'),
            description=entry.get('description'),
            buyer_name=entry.get('authority_name') or 'Unknown Buyer',
            published_date=published_date,
            closing_date=closing_date,
            closing_time=closing_time,
            value=entry.get('contract_value'),
            cpv_codes=entry.get('cpv_codes', []),
            region=entry.get('region'),
            contact_email=entry.get('authority_email'),
            suitable_for_sme=entry.get('suitable_for_sme'),
            notice_type=entry.get('notice_type', 'opportunity'),
            links=links
        )
    
    def _convert_to_award(self, entry: dict) -> Optional[AwardedContract]:
        """Convert FTS JSON entry to AwardedContract"""
        
        return AwardedContract(
            tender_id=entry.get('tender_id', ''),
            title=entry.get('title', 'Untitled'),
            description=entry.get('description'),
            supplier_name=entry.get('supplier_name'),
            buyer_name=entry.get('authority_name'),
            contract_value=entry.get('contract_value'),
            award_date=entry.get('award_date'),
            cpv_codes=entry.get('cpv_codes', []),
            buyer_region=entry.get('region'),
            buyer_email=entry.get('authority_email'),
            reference=entry.get('reference'),
            suitable_for_sme=entry.get('suitable_for_sme'),
            url=entry.get('url', '')
        )
    
    def _parse_published_date(self, published_str: Optional[str]) -> datetime:
        """Parse published_date string or return current date as fallback"""
        if not published_str:
            # Use current date as fallback
            return datetime.now()
        
        try:
            # Try ISO format first
            return datetime.fromisoformat(published_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass
        
        try:
            # Try common date formats
            for fmt in ['%d %B %Y', '%B %d %Y', '%Y-%m-%d', '%d/%m/%Y']:
                try:
                    return datetime.strptime(published_str, fmt)
                except ValueError:
                    continue
        except Exception:
            pass
        
        # Fallback to current date
        logger.warning(f"Could not parse published_date '{published_str}', using current date")
        return datetime.now()
    
    def _parse_deadline(self, deadline_str: str) -> tuple[Optional[datetime], Optional[str]]:
        """Parse FTS deadline string into date and time"""
        if not deadline_str:
            return None, None
        
        try:
            # Try common formats
            # "5 December 2025, 12:00pm"
            # "24 December 2025"
            # Extract time if present
            time_match = re.search(r'(\d{1,2}:\d{2}[ap]m)', deadline_str, re.IGNORECASE)
            time_str = time_match.group(1) if time_match else None
            
            # Remove time from string for date parsing
            date_str = re.sub(r',?\s*\d{1,2}:\d{2}[ap]m', '', deadline_str, flags=re.IGNORECASE).strip()
            
            # Try to parse date
            for fmt in ['%d %B %Y', '%B %d %Y', '%Y-%m-%d']:
                try:
                    date = datetime.strptime(date_str, fmt)
                    return date, time_str
                except ValueError:
                    continue
            
            return None, None
        except Exception:
            return None, None
    
    async def close(self):
        """Cleanup (no-op for JSON processor)"""
        pass