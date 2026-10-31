import os
from pydantic import BaseModel

class AppConfig(BaseModel):
    app_name: str = "Nexora"
    tagline: str = "Document Intelligence & Cross-Verification Platform"
    version: str = "2.0.0"
    
    # Cloud Database Settings
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_database: str = os.getenv("MONGODB_DB", "nexora_db")
    mongodb_collection: str = os.getenv("MONGODB_COLLECTION", "knowledge_chunks")
    vector_index_name: str = os.getenv("MONGODB_VECTOR_INDEX", "vector_index")
    
    # Gemini / AI Settings
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
    
    # Tuning Parameters
    chunk_size: int = 900
    chunk_overlap: int = 150
    similarity_threshold: float = 0.45
    top_k: int = 5
    abstention_threshold: float = 0.15

config = AppConfig()
