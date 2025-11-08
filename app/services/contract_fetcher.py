import httpx
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import logging
from app.models.schemas import ContractOpportunity

logger = logging.getLogger(__name__)

class ContractFetcherService:
    BASE_URL = "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search"
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def close(self):
        """Close the HTTP client"""
        await self.client.aclose()
    
    async def fetch_contracts_with_cursor(
        self,
        published_from: Optional[datetime] = None,
        limit: int = 100,
        cursor: Optional[str] = None
    ) -> Tuple[List[ContractOpportunity], Optional[str]]:
        """
        Fetch contracts using cursor pagination (RECOMMENDED).
        The cursor is actually a full URL from links.next.
        NOW WITH POST-FETCH FILTERING FOR OPEN CONTRACTS ONLY.
        """
        try:
            # If cursor provided, use it as the complete URL
            if cursor:
                url = cursor
                logger.info(f"Fetching from next page URL")
                response = await self.client.get(url)
            else:
                # First request - build params
                url = self.BASE_URL
                params = {
                    "limit": limit,
                    "format": "json"
                }
                
                # Only add publishedFrom if provided
                if published_from:
                    params["publishedFrom"] = published_from.isoformat()
                    logger.info(f"Fetching initial page (limit: {limit}, published from: {published_from.date()})")
                else:
                    logger.info(f"Fetching initial page (limit: {limit}, ALL published dates)")
                
                # Always filter by closing date (only open contracts)
                params["closingDate[from]"] = datetime.now(timezone.utc).isoformat()
                
                response = await self.client.get(url, params=params)
            
            response.raise_for_status()
            data = response.json()
            contracts = self._parse_contracts(data)
            next_cursor = data.get('links', {}).get('next')
            
            logger.info(f"Fetched {len(contracts)} OPEN TENDER opportunities. Has next page: {bool(next_cursor)}")
            return contracts, next_cursor
            
        except Exception as e:
            logger.error(f"Failed to fetch contracts: {str(e)}")
            raise
    
    def _parse_contracts(self, api_data: Dict[str, Any]) -> List[ContractOpportunity]:
        """
        Parse API response into ContractOpportunity objects.
        FILTERS: Only "tender" tags (active opportunities) + open closing dates.
        """
        contracts = []
        releases = api_data.get("releases", [])
        now = datetime.now(timezone.utc)
        
        for release in releases:
            try:
                # ✅ FILTER 1: Only process "tender" tags (active opportunities)
                tags = release.get("tag", [])
                if "tender" not in tags:
                    logger.debug(f"Skipping non-tender: {release.get('id')} (tags: {tags})")
                    continue
                
                tender = release.get("tender", {})
                buyer = release.get("buyer", {})
                
                # Parse dates
                published_date_str = release.get("date")
                published_date = None
                if published_date_str:
                    try:
                        published_date = datetime.fromisoformat(published_date_str.replace('Z', '+00:00'))
                    except:
                        pass
                
                closing_date_str = tender.get("tenderPeriod", {}).get("endDate")
                closing_date = None
                if closing_date_str:
                    try:
                        closing_date = datetime.fromisoformat(closing_date_str.replace('Z', '+00:00'))
                    except:
                        pass
                
                # ✅ FILTER 2: Skip closed contracts
                if closing_date and closing_date < now:
                    logger.debug(f"Skipping closed contract: {release.get('id')} (closed: {closing_date.date()})")
                    continue
                
                # Parse value
                value = None
                value_data = tender.get("value", {})
                if value_data and "amount" in value_data:
                    try:
                        value = float(value_data["amount"])
                    except:
                        pass
                
                # Parse CPV codes
                cpv_codes = []
                items = tender.get("items", [])
                for item in items:
                    classification = item.get("classification", {})
                    if classification.get("scheme") == "CPV":
                        cpv_codes.append(classification.get("id", ""))
                
                # Parse region (if available)
                region = None
                delivery_addresses = tender.get("deliveryAddresses", [])
                if delivery_addresses:
                    region = delivery_addresses[0].get("region")
                
                # Create contract object
                contract = ContractOpportunity(
                    notice_id=release.get("id", ""),
                    title=tender.get("title", ""),
                    description=tender.get("description", ""),
                    buyer_name=buyer.get("name", "Unknown Buyer"),
                    published_date=published_date,
                    closing_date=closing_date,
                    value=value,
                    cpv_codes=cpv_codes,
                    region=region
                )
                
                contracts.append(contract)
                
            except Exception as e:
                logger.warning(f"Failed to parse contract {release.get('id', 'unknown')}: {str(e)}")
                continue
        
        logger.info(f"Parsed {len(contracts)} TENDER opportunities out of {len(releases)} total releases")
        return contracts
    
    async def fetch_contracts(
        self,
        limit: int = 100,
        days_back: int = 90,
        offset: int = 0
    ) -> List[ContractOpportunity]:
        """
        Fetch contracts using offset pagination (NOT RECOMMENDED - use cursor instead).
        UK API ignores offset parameter, always returns same results.
        """
        try:
            published_from = datetime.utcnow() - timedelta(days=days_back)
            
            params = {
                "limit": limit,
                "publishedFrom": published_from.isoformat(),
                "format": "json"
            }
            
            response = await self.client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            
            data = response.json()
            contracts = self._parse_contracts(data)
            
            return contracts
            
        except Exception as e:
            logger.error(f"Failed to fetch contracts: {str(e)}")
            raise