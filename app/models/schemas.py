from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any, Literal, Optional
from datetime import datetime, date
from enum import Enum

# ========== AUTHENTICATION MODELS ==========

class UserCreate(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password (min 8 characters)")
    full_name: str = Field(..., min_length=1, description="User's full name")
    firm_name: Optional[str] = Field(None, description="Law firm name (creates new firm if not exists)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "john.smith@cliffordchance.com",
                "password": "SecurePass123!",
                "full_name": "John Smith",
                "firm_name": "Clifford Chance"
            }
        }

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]

class User(BaseModel):
    email: str
    full_name: str
    firm_id: str
    firm_name: Optional[str] = None
    role: str = "user"

# ========== DOCUMENT INGESTION MODELS ==========

class DocumentIngest(BaseModel):
    content: str = Field(..., min_length=1, description="Raw document text content")
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict, 
        description="Document metadata (case_id, doc_type, date, etc.)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "content": "This employment contract is entered into on 15th March 2024...",
                "metadata": {
                    "case_id": "EMP-2024-001",
                    "document_type": "employment_contract",
                    "date": "2024-03-15",
                    "client_name": "ABC Ltd",
                    "filename": "employment_contract.pdf"
                }
            }
        }

class DocumentChunk(BaseModel):
    chunk_id: str
    content: str
    metadata: Dict[str, Any]
    
class IngestResponse(BaseModel):
    success: bool
    document_id: str
    chunks_created: int
    message: str

class DocumentMetadata(BaseModel):
    """Metadata for a single document in the knowledge base"""
    id: str = Field(..., description="Unique document identifier")
    filename: str = Field(..., description="Original filename")
    uploaded_at: str = Field(..., description="ISO timestamp of upload")
    chunk_count: int = Field(..., description="Number of chunks created")
    uploaded_by: str = Field(..., description="Email of user who uploaded")

class DocumentListResponse(BaseModel):
    """Response for listing documents"""
    documents: List[DocumentMetadata]

# ========== RAG QUERY MODELS ==========

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Legal question or query")
    max_results: int = Field(default=5, ge=1, le=20, description="Max context chunks to retrieve")
    conversation_id: Optional[str] = Field(None, description="Conversation ID to continue existing conversation")
    
    class Config:
        json_schema_extra = {
            "example": {
                "question": "What is the notice period for termination in employment contracts?",
                "max_results": 5,
                "conversation_id": None
            }
        }

class ContextChunk(BaseModel):
    """A single chunk of context retrieved from vector store"""
    content: str = Field(..., description="Text content of the chunk")
    metadata: Dict[str, Any] = Field(..., description="Metadata about the chunk")
    score: float = Field(..., description="Relevance score (0-1)")

class SourceCitation(BaseModel):
    """Source citation for frontend display"""
    filename: str = Field(..., description="Source document filename")
    chunk_text: str = Field(..., description="Preview of the chunk text (truncated)")
    score: float = Field(..., description="Relevance score (0-1)")
    page: Optional[int] = Field(None, description="Page number if available")
    chunk_index: Optional[int] = Field(None, description="Chunk index within document")
    document_id: Optional[str] = Field(None, description="Document ID")

class QueryResponse(BaseModel):
    """Enhanced response with source citations"""
    question: str = Field(..., description="Original question")
    answer: str = Field(..., description="Generated answer from LLM")
    context: List[ContextChunk] = Field(..., description="Retrieved context chunks (full data)")
    sources: Optional[List[SourceCitation]] = Field(
        default=None, 
        description="Source citations for frontend display"
    )
    num_sources: Optional[int] = Field(None, description="Number of sources used")
    conversation_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "question": "What is the notice period?",
                "answer": "According to Source 1, the notice period is 30 days...",
                "context": [
                    {
                        "content": "The employee must provide 30 days notice...",
                        "metadata": {"filename": "contract.pdf", "page": 3},
                        "score": 0.92
                    }
                ],
                "sources": [
                    {
                        "filename": "contract.pdf",
                        "chunk_text": "The employee must provide 30 days notice...",
                        "score": 0.92,
                        "page": 3,
                        "chunk_index": 5
                    }
                ],
                "num_sources": 1,
                "timestamp": "2024-03-15T10:30:00"
            }
        }

# ========== BATCH UPLOAD MODELS ==========

class BatchUploadResult(BaseModel):
    """Result for a single file in batch upload"""
    filename: str
    document_id: Optional[str] = None
    chunks_created: Optional[int] = None
    reason: Optional[str] = None

class BatchUploadResponse(BaseModel):
    """Response for batch upload endpoint"""
    total_files: int
    successful: List[Dict[str, Any]]
    failed: List[Dict[str, Any]]
    success_count: int
    failed_count: int
    message: str

# ========== ERROR MODELS ==========

class ErrorResponse(BaseModel):
    """Standard error response"""
    detail: str
    status_code: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)

# ========== CONTRACT MODELS ==========

class ContractOpportunity(BaseModel):
    """Model for a contract opportunity from Contracts Finder"""
    notice_id: str = Field(..., description="Unique notice identifier")
    title: str = Field(..., description="Contract title")
    description: Optional[str] = Field(None, description="Contract description")
    buyer_name: str = Field(..., description="Purchasing organization")
    published_date: datetime = Field(..., description="Publication date")
    closing_date: Optional[datetime] = Field(None, description="Application deadline")
    value: Optional[float] = Field(None, description="Contract value")
    cpv_codes: Optional[List[str]] = Field(default_factory=list, description="CPV classification codes")
    region: Optional[str] = Field(None, description="Geographic region")

class ContractSyncResponse(BaseModel):
    """Response for contract sync operation"""
    success: bool
    contracts_fetched: int
    contracts_processed: int
    message: str

# ========== CONTRACT SEARCH MODELS ==========

class ContractSearchRequest(BaseModel):
    """Request model for contract search"""
    query: str = Field(..., min_length=3, description="Search query for contracts")
    limit: int = Field(default=10, ge=1, le=50, description="Max results to return")
    min_value: Optional[float] = Field(None, ge=0, description="Minimum contract value")
    max_value: Optional[float] = Field(None, ge=0, description="Maximum contract value")
    region: Optional[str] = Field(None, description="Filter by region")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "software development AI technology",
                "limit": 10,
                "min_value": 10000,
                "max_value": 500000,
                "region": "London"
            }
        }

class ContractSearchResult(BaseModel):
    notice_id: str
    title: str
    buyer_name: str
    description: str
    value: Optional[float]
    region: Optional[str]
    closing_date: Optional[str]
    score: float  # Semantic similarity score
    
    # Personalized match scoring fields
    match_scores: Optional[Dict[str, Any]] = None
    total_match_score: Optional[float] = None
    match_reasons: Optional[List[str]] = None  # 🔧 ADDED: For "Why this matches" tags
    
    class Config:
        from_attributes = True

class ContractSearchResponse(BaseModel):
    """Response for contract search"""
    query: str
    results: List[ContractSearchResult]
    total_found: int
    message: str

class CompanySizeEnum(str, Enum):
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"

# ========== COMPANY PROFILE SCHEMAS ==========
# These match the routes.py expectations and database models

class CompanyProfileBase(BaseModel):
    """Base fields for company profile"""
    company_name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None

class CompanyProfileCreate(CompanyProfileBase):
    """Create company profile"""
    registration_number: Optional[str] = Field(None, max_length=50)
    size: CompanySizeEnum
    founded_year: Optional[int] = Field(None, ge=1800, le=2025)
    
    class Config:
        json_schema_extra = {
            "example": {
                "company_name": "TechSolutions Ltd",
                "registration_number": "12345678",
                "size": "small",
                "founded_year": 2018,
                "description": "IT consultancy specializing in cloud infrastructure"
            }
        }

class CompanyProfileUpdate(BaseModel):
    """Update company profile (all fields optional)"""
    company_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None

# ========== CAPABILITY SCHEMAS ==========

class CapabilityCreate(BaseModel):
    """Create a new capability"""
    capability_text: str = Field(..., min_length=1, description="Description of the capability")
    category: Optional[str] = Field(None, max_length=100, description="Capability category (e.g., 'Technology', 'Construction')")
    
    class Config:
        json_schema_extra = {
            "example": {
                "capability_text": "Cloud migration and AWS infrastructure deployment with 5+ years experience",
                "category": "Technology"
            }
        }

class CapabilityUpdate(BaseModel):
    """Update an existing capability"""
    capability_text: str = Field(..., min_length=1)
    category: Optional[str] = Field(None, max_length=100)

class CapabilityResponse(BaseModel):
    """Response model for a single capability"""
    id: int
    capability_text: str
    category: Optional[str]
    qdrant_id: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

# ========== PAST WIN SCHEMAS ==========

class PastWinCreate(BaseModel):
    """Create a new past contract win"""
    contract_title: str = Field(..., max_length=500)
    buyer_name: str = Field(..., max_length=255)  # Matches DB column name
    contract_value: Optional[float] = Field(None, ge=0)
    award_date: date = Field(..., description="Date contract was awarded")  # Matches DB column name
    description: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "contract_title": "Cloud Infrastructure Modernization",
                "buyer_name": "Manchester City Council",
                "contract_value": 250000.00,
                "award_date": "2024-01-15",
                "description": "Migration of legacy systems to AWS cloud"
            }
        }

class PastWinUpdate(BaseModel):
    """Update an existing past win (all fields optional)"""
    contract_title: Optional[str] = Field(None, max_length=500)
    buyer_name: Optional[str] = Field(None, max_length=255)
    contract_value: Optional[float] = Field(None, ge=0)
    award_date: Optional[date] = None
    description: Optional[str] = None

class PastWinResponse(BaseModel):
    """Response model for a single past win"""
    id: int
    contract_title: str
    buyer_name: str
    contract_value: Optional[float]
    award_date: date
    description: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

# ========== SEARCH PREFERENCES SCHEMAS ==========

class PreferencesUpdate(BaseModel):
    """Update search preferences (all fields optional)"""
    min_contract_value: Optional[float] = Field(None, ge=0)
    max_contract_value: Optional[float] = Field(None, ge=0)
    preferred_regions: Optional[List[str]] = None
    excluded_categories: Optional[List[str]] = None  # Matches DB column name
    keywords: Optional[List[str]] = None  # Matches DB column name
    
    class Config:
        json_schema_extra = {
            "example": {
                "min_contract_value": 50000,
                "max_contract_value": 500000,
                "preferred_regions": ["North West", "Yorkshire", "London"],
                "excluded_categories": ["Construction", "Healthcare"],
                "keywords": ["cloud", "technology", "digital"]
            }
        }

class PreferencesResponse(BaseModel):
    """Response model for search preferences"""
    min_contract_value: Optional[float]
    max_contract_value: Optional[float]
    preferred_regions: List[str]
    excluded_categories: List[str]
    keywords: List[str]
    
    class Config:
        from_attributes = True

# ========== FULL COMPANY PROFILE RESPONSE ==========

class CompanyProfileResponse(BaseModel):
    """Complete company profile with all related data"""
    firm_id: str
    company_name: str
    description: Optional[str]
    size: Optional[str] = None
    founded_year: Optional[int] = None
    registration_number: Optional[str] = None
    capabilities: List[CapabilityResponse]
    past_wins: List[PastWinResponse]
    preferences: PreferencesResponse
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "firm_id": "techsolutions-ltd",
                "company_name": "TechSolutions Ltd",
                "description": "IT consultancy specializing in cloud infrastructure",
                "size": "small",
                "capabilities": [
                    {
                        "id": 1,
                        "capability_text": "AWS cloud migration",
                        "category": "Technology",
                        "qdrant_id": "cap_123",
                        "created_at": "2024-01-01T00:00:00"
                    }
                ],
                "past_wins": [
                    {
                        "id": 1,
                        "contract_title": "Cloud Migration Project",
                        "client_name": "City Council",
                        "contract_value": 150000.0,
                        "contract_date": "2024-01-15",
                        "description": "Migrated systems to AWS",
                        "created_at": "2024-01-01T00:00:00"
                    }
                ],
                "preferences": {
                    "min_contract_value": 50000,
                    "max_contract_value": 500000,
                    "preferred_regions": ["North West", "London"],
                    "preferred_sectors": ["Technology"],
                    "excluded_keywords": ["construction"]
                },
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00"
            }
        }

# ========== SAVED CONTRACTS SCHEMAS ==========

class ContractStatusEnum(str, Enum):
    INTERESTED = "interested"
    BIDDING = "bidding"
    WON = "won"
    LOST = "lost"

class SaveContractRequest(BaseModel):
    """Request to save a contract"""
    notice_id: str = Field(..., description="Contract notice ID")
    contract_title: str = Field(..., max_length=500)
    buyer_name: str = Field(..., max_length=255)
    contract_value: Optional[float] = None
    deadline: Optional[datetime] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "notice_id": "2024/S 123-456789",
                "contract_title": "IT Support Services",
                "buyer_name": "Manchester City Council",
                "contract_value": 150000.00,
                "deadline": "2025-12-31T23:59:59"
            }
        }

class UpdateContractStatusRequest(BaseModel):
    """Update status of a saved contract"""
    status: ContractStatusEnum
    notes: Optional[str] = Field(None, max_length=1000)
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "bidding",
                "notes": "Preparing bid proposal, deadline next week"
            }
        }

class SavedContractResponse(BaseModel):
    """Response for a saved contract"""
    id: int
    notice_id: str
    contract_title: str
    buyer_name: str
    contract_value: Optional[float]
    deadline: Optional[datetime]
    status: str
    notes: Optional[str]
    saved_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class SavedContractsListResponse(BaseModel):
    """Response for listing saved contracts"""
    total: int
    contracts: List[SavedContractResponse]

class EmailPreferencesUpdate(BaseModel):
    """Schema for updating user email preferences."""
    
    email_notifications_enabled: Optional[bool] = Field(
        None,
        description="Enable/disable all email notifications"
    )
    
    notification_frequency: Optional[Literal["daily", "weekly", "never"]] = Field(
        None,
        description="How often to receive new contract emails"
    )
    
    @validator('notification_frequency')
    def validate_frequency(cls, v):
        """Ensure frequency is one of allowed values."""
        if v is not None and v not in ["daily", "weekly", "never"]:
            raise ValueError("notification_frequency must be 'daily', 'weekly', or 'never'")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "email_notifications_enabled": True,
                "notification_frequency": "daily"
            }
        }


class EmailPreferencesResponse(BaseModel):
    """Schema for returning user email preferences."""
    
    email_notifications_enabled: bool = Field(
        description="Whether email notifications are enabled"
    )
    
    notification_frequency: str = Field(
        description="How often the user receives new contract emails"
    )
    
    last_email_sent_at: Optional[datetime] = Field(
        None,
        description="When the last email was sent to this user"
    )
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "email_notifications_enabled": True,
                "notification_frequency": "daily",
                "last_email_sent_at": "2025-10-30T08:00:00Z"
            }
        }



# Backward compatibility aliases for old router
CompanyCapabilityCreate = CapabilityCreate
CompanyCapabilityResponse = CapabilityResponse
SearchPreferenceCreate = PreferencesUpdate
SearchPreferenceResponse = PreferencesResponse
PastWinCreate = PastWinCreate 
PastWinResponse = PastWinResponse  
CompanyProfileFull = CompanyProfileResponse