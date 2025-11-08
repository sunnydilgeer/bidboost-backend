# app/services/contract_fetcher.py - COMPLETE REWRITE

import httpx
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from app.models.schemas import ContractOpportunity

logger = logging.getLogger(__name__)

class ContractFetcherService:
    """Service to fetch contract opportunities from Contracts Finder API."""
    
    BASE_URL = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
    TIMEOUT = 30.0
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=self.TIMEOUT)
    
    async def fetch_contracts(
        self, 
        limit: int = 100,
        days_back: int = 7,
        offset: int = 0
    ) -> List[ContractOpportunity]:
        """
        Fetch recent contract opportunities from Contracts Finder.
        NOTE: This is kept for backwards compatibility but cursor-based pagination is preferred.
        
        Args:
            limit: Max contracts to fetch (default 100, max 100 per API rules)
            days_back: How many days back to search (default 7)
            offset: DEPRECATED - not reliable with this API
        """
        try:
            published_from = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
            
            params = {
                "limit": limit,
                "publishedFrom": published_from,
                "format": "json"
            }
            
            logger.info(f"Fetching contracts from {published_from} (limit: {limit})")
            
            response = await self.client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            
            data = response.json()
            contracts = self._parse_contracts(data)
            
            logger.info(f"Successfully fetched {len(contracts)} contracts")
            return contracts
            
        except Exception as e:
            logger.error(f"Failed to fetch contracts: {str(e)}")
            raise
    
    async def fetch_contracts_with_cursor(
        self,
        published_from: datetime,
        limit: int = 100,
        cursor: Optional[str] = None
    ) -> Tuple[List[ContractOpportunity], Optional[str]]:
        """
        Fetch contracts using cursor-based pagination (RECOMMENDED METHOD).
        Returns tuple of (contracts, next_cursor).
        
        Args:
            published_from: Start date for filtering
            limit: Max contracts per page (default 100, max 100 per API rules)
            cursor: Pagination cursor from previous response (None for first page)
            
        Returns:
            Tuple of (list of contracts, next cursor or None)
        """
        try:
            params = {
                "limit": limit,
                "publishedFrom": published_from.isoformat(),
                "format": "json"
            }
            
            # Add cursor if provided (not for first request)
            if cursor:
                params["cursor"] = cursor
            
            logger.info(f"Fetching contracts with cursor: {cursor or 'initial'} (limit: {limit})")
            
            response = await self.client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            
            data = response.json()
            contracts = self._parse_contracts(data)
            
            # Extract next cursor from response
            # Try multiple possible locations in API response
            next_cursor = (
                data.get('cursor') or 
                data.get('next_cursor') or 
                data.get('nextCursor') or
                data.get('links', {}).get('next') or
                data.get('meta', {}).get('cursor')
            )
            
            logger.info(f"Successfully fetched {len(contracts)} contracts. Next cursor: {next_cursor or 'none'}")
            return contracts, next_cursor
            
        except Exception as e:
            logger.error(f"Failed to fetch contracts with cursor {cursor}: {str(e)}")
            raise
    
    def _parse_contracts(self, api_data: Dict[str, Any]) -> List[ContractOpportunity]:
        """Parse API response into ContractOpportunity objects."""
        contracts = []
        
        # Handle OCDS format - contracts are in 'releases' array
        releases = api_data.get('releases', [])
        
        for release in releases:
            try:
                # Extract basic fields following OCDS schema
                tender = release.get('tender', {})
                buyer = release.get('buyer', {})
                
                contract = ContractOpportunity(
                    notice_id=release.get('id', ''),
                    title=tender.get('title', 'Untitled'),
                    description=tender.get('description', ''),
                    buyer_name=buyer.get('name', 'Unknown'),
                    published_date=self._parse_date(release.get('date')),
                    closing_date=self._parse_date(tender.get('tenderPeriod', {}).get('endDate')),
                    value=self._extract_value(tender.get('value')),
                    cpv_codes=self._extract_cpv_codes(tender.get('classification')),
                    region=self._extract_region(tender.get('deliveryAddresses'))
                )
                
                contracts.append(contract)
                
            except Exception as e:
                logger.warning(f"Failed to parse contract {release.get('id', 'unknown')}: {str(e)}")
                continue
        
        return contracts
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO date string to datetime."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            return None
    
    def _extract_value(self, value_obj: Optional[Dict]) -> Optional[float]:
        """Extract monetary value from OCDS value object."""
        if not value_obj:
            return None
        
        amount = value_obj.get('amount')
        if amount is None:
            return None
        
        try:
            return float(amount)
        except (ValueError, TypeError):
            return None
    
    def _extract_cpv_codes(self, classification: Optional[Dict]) -> List[str]:
        """Extract CPV codes from classification object."""
        if not classification:
            return []
        
        codes = []
        if 'id' in classification:
            codes.append(classification['id'])
        
        return codes
    
    def _extract_region(self, addresses: Optional[List[Dict]]) -> Optional[str]:
        """Extract region from delivery addresses."""
        if not addresses or not addresses[0]:
            return None
        
        address = addresses[0]
        return address.get('region') or address.get('locality')
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()