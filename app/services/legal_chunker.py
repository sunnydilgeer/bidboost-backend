import re
from typing import List, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class LegalChunk:
    text: str
    metadata: Dict[str, Any]
    chunk_type: str  # 'clause', 'section', 'paragraph', 'fallback'

class LegalDocumentChunker:
    """Chunks legal documents respecting clause boundaries and numbered sections."""
    
    # Patterns for legal document structures
    PATTERNS = {
        'numbered_clause': re.compile(r'^\s*\d+\.(?:\d+\.)*\s+[A-Z]', re.MULTILINE),
        'lettered_clause': re.compile(r'^\s*\([a-z]\)\s+', re.MULTILINE),
        'section_header': re.compile(r'^\s*(?:SECTION|ARTICLE|CLAUSE)\s+\d+', re.IGNORECASE | re.MULTILINE),
        'whereas_clause': re.compile(r'^\s*WHEREAS[,:]', re.IGNORECASE | re.MULTILINE),
        'schedule': re.compile(r'^\s*(?:SCHEDULE|APPENDIX|ANNEX)\s+[A-Z0-9]', re.IGNORECASE | re.MULTILINE),
        'page_marker': re.compile(r'\[Page (\d+)\]')
    }
    
    def __init__(self, max_chunk_size: int = 800, min_chunk_size: int = 100, overlap_sentences: int = 1):
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self.overlap_sentences = overlap_sentences
    
    def chunk_document(self, text: str, base_metadata: Dict[str, Any]) -> List[LegalChunk]:
        """Main chunking method with legal-awareness."""
        
        # Build page map FIRST - maps character positions to page numbers
        page_map = self._build_page_map(text)
        
        # Try legal structure detection first
        chunks = self._chunk_by_clauses(text, base_metadata, page_map)
        
        # Fallback to sentence-based for non-structured documents
        if not chunks or self._is_poorly_structured(chunks):
            logger.info(f"Using fallback chunking for {base_metadata.get('filename', 'unknown')}")
            chunks = self._chunk_by_sentences(text, base_metadata, page_map)
        else:
            logger.info(f"Used clause-based chunking for {base_metadata.get('filename', 'unknown')}, created {len(chunks)} chunks")
        
        return chunks
    
    def _build_page_map(self, text: str) -> Dict[int, int]:
        """
        Build a map of character positions to page numbers.
        Returns dict: {char_position: page_number}
        """
        page_map = {}
        
        # Find all [Page X] markers and their positions
        for match in self.PATTERNS['page_marker'].finditer(text):
            page_num = int(match.group(1))
            position = match.start()
            page_map[position] = page_num
        
        return page_map
    
    def _get_page_for_position(self, position: int, page_map: Dict[int, int]) -> int:
        """Get the page number for a given character position in text."""
        if not page_map:
            return 1
        
        # Find the last page marker that appears before this position
        relevant_positions = [pos for pos in page_map.keys() if pos <= position]
        
        if not relevant_positions:
            return 1  # Before first page marker
        
        last_marker_pos = max(relevant_positions)
        return page_map[last_marker_pos]
    
    def _chunk_by_clauses(self, text: str, metadata: Dict[str, Any], page_map: Dict[int, int]) -> List[LegalChunk]:
        """Chunk by numbered clauses/sections."""
        chunks = []
        
        # Find all numbered clause positions
        clause_matches = list(self.PATTERNS['numbered_clause'].finditer(text))
        section_matches = list(self.PATTERNS['section_header'].finditer(text))
        schedule_matches = list(self.PATTERNS['schedule'].finditer(text))
        
        all_boundaries = sorted(
            clause_matches + section_matches + schedule_matches, 
            key=lambda m: m.start()
        )
        
        if not all_boundaries:
            return []
        
        # Extract chunks between boundaries
        for i, match in enumerate(all_boundaries):
            start_pos = match.start()
            end_pos = all_boundaries[i + 1].start() if i + 1 < len(all_boundaries) else len(text)
            
            chunk_text = text[start_pos:end_pos].strip()
            
            # Skip tiny chunks (likely false positives)
            if len(chunk_text) < 50:
                continue
            
            # Get page number using position in original text
            page_number = self._get_page_for_position(start_pos, page_map)
            
            # Split oversized chunks at sentence boundaries
            if len(chunk_text) > self.max_chunk_size:
                sub_chunks = self._split_large_chunk(chunk_text, metadata, 'clause', page_map, start_pos)
                chunks.extend(sub_chunks)
            else:
                chunk_metadata = metadata.copy()
                chunk_metadata['clause_number'] = self._extract_clause_number(chunk_text)
                chunk_metadata['page'] = page_number
                
                chunks.append(LegalChunk(
                    text=chunk_text,
                    metadata=chunk_metadata,
                    chunk_type='clause'
                ))
        
        return chunks
    
    def _chunk_by_sentences(self, text: str, metadata: Dict[str, Any], page_map: Dict[int, int]) -> List[LegalChunk]:
        """Fallback: sentence-based chunking with overlap."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = []
        current_length = 0
        current_position = 0
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Get page for current position
            page_number = self._get_page_for_position(current_position, page_map)
            
            sentence_length = len(sentence)
            
            if current_length + sentence_length > self.max_chunk_size and current_chunk:
                chunk_metadata = metadata.copy()
                chunk_metadata['page'] = page_number
                
                chunks.append(LegalChunk(
                    text=' '.join(current_chunk),
                    metadata=chunk_metadata,
                    chunk_type='fallback'
                ))
                # Overlap: keep last N sentences
                current_chunk = current_chunk[-self.overlap_sentences:] if len(current_chunk) > self.overlap_sentences else []
                current_length = sum(len(s) for s in current_chunk)
            
            current_chunk.append(sentence)
            current_length += sentence_length
            current_position += sentence_length + 1  # +1 for space
        
        if current_chunk:
            page_number = self._get_page_for_position(current_position, page_map)
            chunk_metadata = metadata.copy()
            chunk_metadata['page'] = page_number
            
            chunks.append(LegalChunk(
                text=' '.join(current_chunk),
                metadata=chunk_metadata,
                chunk_type='fallback'
            ))
        
        return chunks
    
    def _split_large_chunk(self, text: str, metadata: Dict[str, Any], chunk_type: str, page_map: Dict[int, int], start_position: int) -> List[LegalChunk]:
        """Split oversized chunks at sentence boundaries while preserving page numbers."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sub_chunks = []
        current = []
        current_len = 0
        relative_pos = 0
        
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            
            # Calculate absolute position in original text
            absolute_pos = start_position + relative_pos
            page_number = self._get_page_for_position(absolute_pos, page_map)
            
            if current_len + len(sent) > self.max_chunk_size and current:
                chunk_metadata = metadata.copy()
                chunk_metadata['page'] = page_number
                
                sub_chunks.append(LegalChunk(' '.join(current), chunk_metadata, chunk_type))
                current = [sent]
                current_len = len(sent)
            else:
                current.append(sent)
                current_len += len(sent)
            
            relative_pos += len(sent) + 1
        
        if current:
            absolute_pos = start_position + relative_pos
            page_number = self._get_page_for_position(absolute_pos, page_map)
            chunk_metadata = metadata.copy()
            chunk_metadata['page'] = page_number
            sub_chunks.append(LegalChunk(' '.join(current), chunk_metadata, chunk_type))
        
        return sub_chunks
    
    def _extract_clause_number(self, text: str) -> str:
        """Extract clause number from text."""
        match = re.match(r'^\s*(\d+(?:\.\d+)*)', text)
        return match.group(1) if match else 'unknown'
    
    def _is_poorly_structured(self, chunks: List[LegalChunk]) -> bool:
        """Check if clause-based chunking produced poor results."""
        if len(chunks) < 2:
            return True
        avg_size = sum(len(c.text) for c in chunks) / len(chunks)
        return avg_size < self.min_chunk_size