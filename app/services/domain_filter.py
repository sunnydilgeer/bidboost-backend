"""
NAICS-based domain filtering (company-agnostic, scalable)

Uses 4-digit NAICS industry groups to prevent cross-industry false matches.
Works for ANY company type without hardcoded logic.

Examples:
- Consulting (5416) only matches consulting contracts (5416)
- Manufacturing (3327) only matches manufacturing contracts (3327)
- No hardcoded compatibility matrices needed
"""
import logging
from typing import Optional, Set
from app.models.company import CompanyProfile
from app.models.contract import Contract

logger = logging.getLogger(__name__)


class DomainFilter:
    """
    Industry-aware filtering using 4-digit NAICS codes.
    Prevents semantic matching from crossing industry boundaries.
    """
    
    def __init__(self):
        pass
    
    def passes_domain_filter(
        self,
        contract: Contract,
        profile: CompanyProfile
    ) -> bool:
        """
        Check if contract NAICS matches company's industry groups.
        
        Uses 4-digit NAICS groups for precision:
        - 5416 = Management, Scientific, and Technical Consulting
        - 5415 = Computer Systems Design and Related Services
        - 5617 = Services to Buildings and Dwellings (janitorial, etc.)
        - 3327 = Machine Shops
        
        This ensures semantic matching only happens WITHIN the correct industry,
        preventing "monitoring compliance" from matching "monitoring fire alarms".
        
        Returns:
            True if contract is in compatible industry
            False if cross-industry mismatch
        """
        try:
            contract_naics = getattr(contract, "naics_code", None)
            company_naics = profile.naics_codes or []
            
            # DEBUG: Log what we're checking
            logger.info(
                f"🔍 DOMAIN CHECK: {contract.title[:50]}... | "
                f"Contract NAICS: {contract_naics} | "
                f"Company NAICS: {company_naics}"
            )
            
            # No filter if NAICS data missing (fall back to pure semantic)
            if not contract_naics or not company_naics:
                logger.warning(
                    f"⚠️ NO NAICS DATA - Allowing semantic match for: {contract.title[:50]}..."
                )
                return True
            
            # Extract 4-digit industry groups
            contract_group = self._extract_naics_group(contract_naics)
            company_groups = self._extract_company_groups(company_naics)
            
            if not contract_group:
                logger.warning(f"⚠️ Could not extract NAICS group from: {contract_naics}")
                return True  # Can't determine, allow through
            
            # Check if contract is in company's industry groups
            if contract_group in company_groups:
                logger.debug(
                    f"✅ NAICS match: contract group '{contract_group}' "
                    f"in company groups {company_groups}"
                )
                return True
            
            # BLOCKED - Log why
            logger.info(
                f"❌ NAICS mismatch: contract group '{contract_group}' "
                f"not in company groups {company_groups}. "
                f"Title: {contract.title[:60]}... | "
                f"Contract NAICS: {contract_naics}"
            )
            return False
            
        except Exception as e:
            logger.error(f"Error in domain filter: {e}", exc_info=True)
            return True  # On error, fall back to allowing match
    
    def _extract_naics_group(self, naics_code: str) -> Optional[str]:
        """
        Extract 4-digit NAICS industry group.
        
        Examples:
        - "541611" → "5416"
        - "561720" → "5617"
        - "332710" → "3327"
        """
        try:
            naics_str = str(naics_code).strip()
            
            if len(naics_str) >= 4:
                return naics_str[:4]
            
            return None
            
        except Exception:
            return None
    
    def _extract_company_groups(self, naics_codes: list) -> Set[str]:
        """
        Extract all 4-digit industry groups from company's NAICS list.
        
        Example:
        Input: ["541611", "541618", "541512"]
        Output: {"5416", "5415"}
        """
        groups = set()
        
        for code in naics_codes:
            group = self._extract_naics_group(code)
            if group:
                groups.add(group)
        
        return groups
    
    def get_naics_group_name(self, naics_code: str) -> str:
        """
        Get human-readable name for NAICS group (for debugging/logging).
        
        Common groups:
        - 5416: Management, Scientific, Technical Consulting
        - 5415: Computer Systems Design
        - 5417: Scientific R&D
        - 5418: Advertising, PR, Marketing
        - 5611: Office Administrative Services
        - 5617: Services to Buildings (janitorial, landscaping)
        - 3327: Machine Shops
        - 3364: Aerospace Product Manufacturing
        """
        group_names = {
            "5416": "Management, Scientific, Technical Consulting",
            "5415": "Computer Systems Design and Related Services",
            "5417": "Scientific Research and Development",
            "5418": "Advertising, Public Relations, Marketing",
            "5413": "Architectural, Engineering Services",
            "5419": "Other Professional, Scientific, Technical Services",
            "5611": "Office Administrative Services",
            "5614": "Business Support Services",
            "5616": "Investigation and Security Services",
            "5617": "Services to Buildings and Dwellings",
            "5621": "Waste Collection",
            "3327": "Machine Shops",
            "3364": "Aerospace Product and Parts Manufacturing",
            "3343": "Audio and Video Equipment Manufacturing",
            "3359": "Other Electrical Equipment Manufacturing",
            "2362": "Nonresidential Building Construction",
        }
        
        group = self._extract_naics_group(naics_code)
        return group_names.get(group, f"NAICS Group {group}")


# Singleton instance
_domain_filter = None

def get_domain_filter() -> DomainFilter:
    """Get singleton instance of domain filter."""
    global _domain_filter
    if _domain_filter is None:
        _domain_filter = DomainFilter()
    return _domain_filter