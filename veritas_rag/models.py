from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid
import time

class DocumentMetadata(BaseModel):
    title: str
    author: Optional[str] = "Unknown"
    year: Optional[int] = 2025
    category: Optional[str] = "General"
    source_type: str = "upload" # pdf, txt, markdown, preloaded
    file_size_bytes: int = 0
    created_at: float = Field(default_factory=time.time)

class DocumentChunk(BaseModel):
    id: str = Field(default_factory=lambda: f"chk_{uuid.uuid4().hex[:8]}")
    doc_id: str
    doc_title: str
    section: Optional[str] = "General"
    page_number: Optional[int] = 1
    content: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)

class DocumentUploadRequest(BaseModel):
    title: str
    content: str
    author: Optional[str] = "Anonymous"
    year: Optional[int] = 2025
    category: Optional[str] = "General"

class SearchFilters(BaseModel):
    category: Optional[str] = None
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    doc_ids: Optional[List[str]] = None

class Citation(BaseModel):
    id: str
    doc_id: str
    doc_title: str
    section: Optional[str] = ""
    page_number: Optional[int] = 1
    snippet: str
    similarity_score: float
    keyword_score: float = 0.0
    combined_score: float
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ConflictItem(BaseModel):
    id: str = Field(default_factory=lambda: f"cnf_{uuid.uuid4().hex[:6]}")
    subject: str
    claim_a: str
    source_a: str
    value_a: Optional[str] = None
    claim_b: str
    source_b: str
    value_b: Optional[str] = None
    delta: Optional[str] = None
    unit: Optional[str] = None
    condition: Optional[str] = None
    discrepancy_type: str # quantitative, temporal, policy_revision, contradictory
    severity: str # high, medium, notice
    explanation: str

class ReportExportRequest(BaseModel):
    query: str
    answer: str
    citations: List[Citation]
    conflicts: List[ConflictItem]
    groundedness_score: float
    format: str = "markdown" # markdown, json, text

class QueryRequest(BaseModel):
    question: str
    filters: Optional[SearchFilters] = None
    use_hybrid: bool = True
    top_k: int = 5
    temperature: float = 0.2

class QueryResponse(BaseModel):
    question: str
    answer: str
    abstained: bool = False
    abstention_reason: Optional[str] = None
    citations: List[Citation] = Field(default_factory=list)
    conflicts: List[ConflictItem] = Field(default_factory=list)
    groundedness_score: float = 0.0 # 0 to 100%
    latency_ms: float = 0.0
    explain_search: Dict[str, Any] = Field(default_factory=dict)

class EvalTestCase(BaseModel):
    id: str
    query: str
    expected_doc_titles: List[str]
    expected_conflict: bool = False
    expected_abstention: bool = False
    category: str

class EvalMetricResult(BaseModel):
    test_id: str
    query: str
    hit: bool
    reciprocal_rank: float
    precision_at_k: float
    retrieved_titles: List[str]
    expected_titles: List[str]
    conflict_detected: bool
    expected_conflict: bool
    abstained: bool
    expected_abstention: bool
    latency_ms: float
    groundedness_score: float

class EvalSummary(BaseModel):
    total_tests: int
    hit_rate: float # e.g. 0.95
    mrr: float # Mean Reciprocal Rank
    precision_at_3: float
    conflict_detection_accuracy: float
    abstention_accuracy: float
    avg_latency_ms: float
    avg_groundedness: float
    results: List[EvalMetricResult]
