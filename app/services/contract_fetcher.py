# app/services/contract_fetcher.py
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
        published_to: Optional[datetime] = None,
        limit: int = 100,
        cursor: Optional[str] = None
    ) -> Tuple[List[ContractOpportunity], Optional[str]]:
        """
        Fetch contracts using cursor pagination.
        CRITICAL: Must use BOTH publishedFrom AND publishedTo for API to work properly.
        """
        try:
            if cursor:
                url = cursor
                logger.info(f"Fetching from next page URL")
                response = await self.client.get(url)
            else:
                url = self.BASE_URL
                params = {
                    "limit": limit,
                    "format": "json"
                }
                
                # CRITICAL: API requires BOTH parameters to filter properly
                if published_from:
                    params["publishedFrom"] = published_from.isoformat()
                if published_to:
                    params["publishedTo"] = published_to.isoformat()
                
                logger.info(f"Fetching contracts: {published_from.date() if published_from else 'any'} to {published_to.date() if published_to else 'any'}")
                response = await self.client.get(url, params=params)
            
            response.raise_for_status()
            data = response.json()
            contracts = self._parse_contracts(data)
            next_cursor = data.get('links', {}).get('next')
            
            logger.info(f"Fetched {len(contracts)} ACTIVE contracts. Has next page: {bool(next_cursor)}")
            return contracts, next_cursor
            
        except Exception as e:
            logger.error(f"Failed to fetch contracts: {str(e)}")
            raise
    
    def _parse_contracts(self, api_data: Dict[str, Any]) -> List[ContractOpportunity]:
        """
        Parse API response into ContractOpportunity objects.
        FILTERS: tender.status="active" + closing_date > now
        """
        contracts = []
        releases = api_data.get("releases", [])
        now = datetime.now(timezone.utc)
        
        for release in releases:
            try:
                tender = release.get("tender", {})
                
                # FILTER 1: Only "active" status (live opportunities)
                tender_status = tender.get("status")
                if tender_status != "active":
                    logger.debug(f"Skipping non-active: {release.get('id')} (status: {tender_status})")
                    continue
                
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
                
                # FILTER 2: Skip closed contracts
                if closing_date and closing_date < now:
                    logger.debug(f"Skipping closed: {release.get('id')} (closed: {closing_date.date()})")
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
                
                # Parse region
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
        
        logger.info(f"Parsed {len(contracts)} ACTIVE contracts out of {len(releases)} total")
        return contracts
    
    async def fetch_contracts(
        self,
        limit: int = 100,
        days_back: int = 90,
        offset: int = 0
    ) -> List[ContractOpportunity]:
        """Legacy method - use fetch_contracts_with_cursor instead"""
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