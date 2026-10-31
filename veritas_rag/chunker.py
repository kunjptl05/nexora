import re
import io
from typing import List, Tuple, Dict, Any
from veritas_rag.models import DocumentChunk
import uuid

class Chunker:
    def __init__(self, chunk_size: int = 450, chunk_overlap: int = 60):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(
        self, 
        doc_id: str, 
        doc_title: str, 
        content: str, 
        metadata: Dict[str, Any] = None,
        pages: List[Tuple[int, str]] = None
    ) -> List[DocumentChunk]:
        """
        Splits text by markdown sections, paragraphs, and sentence boundaries.
        Preserves section titles, paragraph context, and exact page numbers.
        """
        if metadata is None:
            metadata = {}

        chunks: List[DocumentChunk] = []

        # If explicit page data from PDF is available, chunk page by page
        if pages:
            for page_num, page_text in pages:
                if not page_text.strip():
                    continue
                page_meta = {**metadata, "page_number": page_num}
                sections = self._split_by_sections(page_text)
                for section_title, section_text in sections:
                    paragraphs = [p.strip() for p in section_text.split('\n\n') if p.strip()]
                    current_chunk = ""
                    for para in paragraphs:
                        if len(current_chunk) + len(para) < self.chunk_size:
                            current_chunk += ("\n\n" + para if current_chunk else para)
                        else:
                            if current_chunk:
                                chunks.append(DocumentChunk(
                                    id=f"chk_{uuid.uuid4().hex[:8]}",
                                    doc_id=doc_id,
                                    doc_title=doc_title,
                                    section=section_title,
                                    page_number=page_num,
                                    content=current_chunk.strip(),
                                    metadata={**page_meta, "section": section_title, "page": page_num}
                                ))
                                overlap_start = max(0, len(current_chunk) - self.chunk_overlap)
                                current_chunk = current_chunk[overlap_start:].strip() + "\n\n" + para
                            else:
                                sub_chunks = self._split_large_paragraph(para, self.chunk_size, self.chunk_overlap)
                                for sc in sub_chunks:
                                    chunks.append(DocumentChunk(
                                        id=f"chk_{uuid.uuid4().hex[:8]}",
                                        doc_id=doc_id,
                                        doc_title=doc_title,
                                        section=section_title,
                                        page_number=page_num,
                                        content=sc.strip(),
                                        metadata={**page_meta, "section": section_title, "page": page_num}
                                    ))
                                current_chunk = ""
                    if current_chunk.strip():
                        chunks.append(DocumentChunk(
                            id=f"chk_{uuid.uuid4().hex[:8]}",
                            doc_id=doc_id,
                            doc_title=doc_title,
                            section=section_title,
                            page_number=page_num,
                            content=current_chunk.strip(),
                            metadata={**page_meta, "section": section_title, "page": page_num}
                        ))
            if chunks:
                return chunks
        
        # Detect sections if markdown headers are present
        sections = self._split_by_sections(content)
        
        for section_title, section_text in sections:
            # Further split section into paragraphs
            paragraphs = [p.strip() for p in section_text.split('\n\n') if p.strip()]
            
            current_chunk = ""
            current_page = metadata.get("page_number", 1)
            
            for para in paragraphs:
                # Check page marker
                page_match = re.search(r'\[Page\s+(\d+)\]', para, re.IGNORECASE)
                if page_match:
                    try:
                        current_page = int(page_match.group(1))
                    except ValueError:
                        pass
                
                if len(current_chunk) + len(para) < self.chunk_size:
                    current_chunk += ("\n\n" + para if current_chunk else para)
                else:
                    if current_chunk:
                        chunk_obj = DocumentChunk(
                            id=f"chk_{uuid.uuid4().hex[:8]}",
                            doc_id=doc_id,
                            doc_title=doc_title,
                            section=section_title,
                            page_number=current_page,
                            content=current_chunk.strip(),
                            metadata={**metadata, "section": section_title, "page": current_page}
                        )
                        chunks.append(chunk_obj)
                        
                        # Retain overlap from end of current chunk
                        overlap_start = max(0, len(current_chunk) - self.chunk_overlap)
                        overlap_text = current_chunk[overlap_start:].strip()
                        current_chunk = overlap_text + "\n\n" + para
                    else:
                        # Single paragraph exceeds chunk size, split by sentences
                        sub_chunks = self._split_large_paragraph(para, self.chunk_size, self.chunk_overlap)
                        for sc in sub_chunks:
                            chunk_obj = DocumentChunk(
                                id=f"chk_{uuid.uuid4().hex[:8]}",
                                doc_id=doc_id,
                                doc_title=doc_title,
                                section=section_title,
                                page_number=current_page,
                                content=sc.strip(),
                                metadata={**metadata, "section": section_title, "page": current_page}
                            )
                            chunks.append(chunk_obj)
                        current_chunk = ""

            if current_chunk.strip():
                chunk_obj = DocumentChunk(
                    id=f"chk_{uuid.uuid4().hex[:8]}",
                    doc_id=doc_id,
                    doc_title=doc_title,
                    section=section_title,
                    page_number=current_page,
                    content=current_chunk.strip(),
                    metadata={**metadata, "section": section_title, "page": current_page}
                )
                chunks.append(chunk_obj)

        return chunks

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> Tuple[str, List[Tuple[int, str]]]:
        """
        Extracts text from PDF bytes using pypdf.
        Returns combined text and page-by-page mapping.
        """
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages_content = []
        full_text = []

        for idx, page in enumerate(reader.pages):
            page_num = idx + 1
            txt = page.extract_text() or ""
            clean_txt = f"[Page {page_num}]\n" + txt.strip()
            pages_content.append((page_num, txt))
            full_text.append(clean_txt)

        return "\n\n".join(full_text), pages_content

    def _split_by_sections(self, content: str) -> List[Tuple[str, str]]:
        lines = content.split('\n')
        sections = []
        current_title = "Overview"
        current_lines = []

        for line in lines:
            header_match = re.match(r'^(#{1,4})\s+(.+)$', line.strip())
            if header_match:
                if current_lines:
                    sections.append((current_title, "\n".join(current_lines)))
                    current_lines = []
                current_title = header_match.group(2).strip()
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_title, "\n".join(current_lines)))

        return sections if sections else [("Overview", content)]

    def _split_large_paragraph(self, text: str, size: int, overlap: int) -> List[str]:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = []
        curr = ""
        for s in sentences:
            if len(curr) + len(s) < size:
                curr += (" " + s if curr else s)
            else:
                if curr:
                    result.append(curr)
                    curr = s
                else:
                    # Very long sentence, slice it
                    result.append(s[:size])
                    curr = s[size:]
        if curr:
            result.append(curr)
        return result

chunker = Chunker()
