import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

class DescriptionClassifier:
    """
    Detects "garbage" contract descriptions that need SOW extraction.
    
    Examples of garbage:
    - "Amendment 003 posted"
    - "See attachment for details"
    - "***Modification 001***"
    - Very short descriptions (< 20 words)
    """
    
    # Patterns that indicate garbage descriptions
    GARBAGE_PATTERNS = [
        r"(?i)amendment\s+\d+",
        r"(?i)modification\s+\d+",
        r"(?i)mod\s+\d+",
        r"(?i)see\s+attachment",
        r"(?i)see\s+attached",
        r"(?i)refer\s+to\s+attachment",
        r"(?i)^\*+.*\*+$",  # Text wrapped in asterisks
        r"(?i)posted",
        r"(?i)updated",
        r"(?i)revised",
        r"(?i)corrected",
    ]
    
    MIN_WORD_COUNT = 20  # Descriptions with fewer words are considered garbage
    
    @classmethod
    def is_description_garbage(cls, description: str) -> bool:
        """
        Check if a contract description is garbage/useless.
        
        Args:
            description: Contract description text
            
        Returns:
            True if description is garbage and needs SOW extraction
        """
        if not description or not description.strip():
            return True
        
        # Check word count
        word_count = len(description.split())
        if word_count < cls.MIN_WORD_COUNT:
            logger.debug(f"Garbage: too short ({word_count} words)")
            return True
        
        # Check for garbage patterns
        for pattern in cls.GARBAGE_PATTERNS:
            if re.search(pattern, description):
                logger.debug(f"Garbage: matched pattern '{pattern}'")
                return True
        
        return False
    
    @classmethod
    def get_garbage_reason(cls, description: str) -> str:
        """
        Get the reason why a description is classified as garbage.
        
        Args:
            description: Contract description text
            
        Returns:
            Human-readable reason
        """
        if not description or not description.strip():
            return "Empty description"
        
        word_count = len(description.split())
        if word_count < cls.MIN_WORD_COUNT:
            return f"Too short ({word_count} words)"
        
        for pattern in cls.GARBAGE_PATTERNS:
            if re.search(pattern, description):
                return f"Matches pattern: {pattern}"
        
        return "Unknown"
    
    @classmethod
    def analyze_description(cls, description: str) -> Tuple[bool, str]:
        """
        Analyze description and return classification + reason.
        
        Returns:
            (is_garbage, reason)
        """
        is_garbage = cls.is_description_garbage(description)
        reason = cls.get_garbage_reason(description) if is_garbage else "Good quality"
        return is_garbage, reason