import re
import io
import hashlib
from typing import List, Tuple, Dict, Any, Optional
from veritas_rag.models import DocumentChunk
from veritas_rag.config import config


class Chunker:
    def __init__(self, chunk_size: int = 900, chunk_overlap: int = 150):
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
        Chunk IDs are deterministic (SHA-1 based). [Page N] markers are stripped
        from chunk text. start_char/end_char offsets relative to full content.
        """
        if metadata is None:
            metadata = {}

        chunks: List[DocumentChunk] = []

        # If explicit page data from PDF is available, chunk page by page
        if pages:
            chunk_index = 0
            for page_num, page_text in pages:
                if not page_text.strip():
                    continue
                page_meta = {**metadata, "page_number": page_num}
                sections = self._split_by_sections(page_text)
                for section_title, section_text in sections:
                    paragraphs = [p.strip() for p in section_text.split('\n\n') if p.strip()]
                    current_chunk = ""
                    for para in paragraphs:
                        # Strip [Page N] markers before storing
                        clean_para = re.sub(r'\[Page\s+\d+\]\s*', '', para, flags=re.IGNORECASE).strip()
                        if not clean_para:
                            continue
                        if len(current_chunk) + len(clean_para) < self.chunk_size:
                            current_chunk += ("\n\n" + clean_para if current_chunk else clean_para)
                        else:
                            if current_chunk:
                                chunks.append(self._make_chunk(
                                    doc_id, doc_title, section_title, page_num,
                                    current_chunk.strip(), page_meta, chunk_index
                                ))
                                chunk_index += 1
                                overlap = self._word_boundary_overlap(current_chunk, self.chunk_overlap)
                                current_chunk = overlap + "\n\n" + clean_para
                                # Re-split if still over size
                                if len(current_chunk) > self.chunk_size:
                                    for sc, ci in self._split_large_paragraph_indexed(
                                        current_chunk, self.chunk_size, self.chunk_overlap, chunk_index
                                    ):
                                        chunks.append(self._make_chunk(
                                            doc_id, doc_title, section_title, page_num,
                                            sc.strip(), page_meta, ci
                                        ))
                                        chunk_index = ci + 1
                                    current_chunk = ""
                            else:
                                for sc, ci in self._split_large_paragraph_indexed(
                                    clean_para, self.chunk_size, self.chunk_overlap, chunk_index
                                ):
                                    chunks.append(self._make_chunk(
                                        doc_id, doc_title, section_title, page_num,
                                        sc.strip(), page_meta, ci
                                    ))
                                    chunk_index = ci + 1
                                current_chunk = ""
                    if current_chunk.strip():
                        chunks.append(self._make_chunk(
                            doc_id, doc_title, section_title, page_num,
                            current_chunk.strip(), page_meta, chunk_index
                        ))
                        chunk_index += 1
            if chunks:
                return chunks

        # Plain text / markdown path
        sections = self._split_by_sections(content)
        chunk_index = 0
        char_offset = 0

        for section_title, section_text in sections:
            paragraphs = [p.strip() for p in section_text.split('\n\n') if p.strip()]
            current_chunk = ""
            current_page = metadata.get("page_number", 1)

            for para in paragraphs:
                # Extract [Page N] marker before stripping
                page_match = re.search(r'\[Page\s+(\d+)\]', para, re.IGNORECASE)
                if page_match:
                    try:
                        current_page = int(page_match.group(1))
                    except ValueError:
                        pass
                clean_para = re.sub(r'\[Page\s+\d+\]\s*', '', para, flags=re.IGNORECASE).strip()
                if not clean_para:
                    continue

                if len(current_chunk) + len(clean_para) < self.chunk_size:
                    current_chunk += ("\n\n" + clean_para if current_chunk else clean_para)
                else:
                    if current_chunk:
                        start_char = char_offset
                        end_char = start_char + len(current_chunk)
                        chunks.append(self._make_chunk(
                            doc_id, doc_title, section_title, current_page,
                            current_chunk.strip(), {**metadata, "section": section_title, "page": current_page},
                            chunk_index, start_char, end_char
                        ))
                        chunk_index += 1
                        char_offset = end_char

                        overlap = self._word_boundary_overlap(current_chunk, self.chunk_overlap)
                        current_chunk = overlap + "\n\n" + clean_para

                        # Re-split if still over size
                        if len(current_chunk) > self.chunk_size:
                            for sc, ci in self._split_large_paragraph_indexed(
                                current_chunk, self.chunk_size, self.chunk_overlap, chunk_index
                            ):
                                s_c = char_offset
                                e_c = s_c + len(sc)
                                chunks.append(self._make_chunk(
                                    doc_id, doc_title, section_title, current_page,
                                    sc.strip(),
                                    {**metadata, "section": section_title, "page": current_page},
                                    ci, s_c, e_c
                                ))
                                chunk_index = ci + 1
                                char_offset = e_c
                            current_chunk = ""
                    else:
                        for sc, ci in self._split_large_paragraph_indexed(
                            clean_para, self.chunk_size, self.chunk_overlap, chunk_index
                        ):
                            s_c = char_offset
                            e_c = s_c + len(sc)
                            chunks.append(self._make_chunk(
                                doc_id, doc_title, section_title, current_page,
                                sc.strip(),
                                {**metadata, "section": section_title, "page": current_page},
                                ci, s_c, e_c
                            ))
                            chunk_index = ci + 1
                            char_offset = e_c
                        current_chunk = ""

            if current_chunk.strip():
                start_char = char_offset
                end_char = start_char + len(current_chunk)
                chunks.append(self._make_chunk(
                    doc_id, doc_title, section_title, current_page,
                    current_chunk.strip(),
                    {**metadata, "section": section_title, "page": current_page},
                    chunk_index, start_char, end_char
                ))
                chunk_index += 1
                char_offset = end_char

        return chunks

    def _make_chunk(
        self,
        doc_id: str,
        doc_title: str,
        section: str,
        page_number: int,
        content: str,
        metadata: Dict[str, Any],
        chunk_index: int,
        start_char: int = 0,
        end_char: int = 0
    ) -> DocumentChunk:
        """Creates a DocumentChunk with a deterministic SHA-1 ID."""
        # Deterministic ID: SHA-1 of (doc_id, index, first 50 chars of content)
        id_source = f"{doc_id}_{chunk_index}_{content[:50]}"
        chunk_id = "chk_" + hashlib.sha1(id_source.encode("utf-8")).hexdigest()[:12]

        return DocumentChunk(
            id=chunk_id,
            doc_id=doc_id,
            doc_title=doc_title,
            section=section,
            page_number=page_number,
            content=content,
            metadata={**metadata, "start_char": start_char, "end_char": end_char or (start_char + len(content))}
        )

    def get_embedding_text(self, chunk: DocumentChunk) -> str:
        """Returns context-enriched text for embedding (title + section prefix)."""
        return f"{chunk.doc_title} > {chunk.section or 'Overview'}\n{chunk.content}"

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> Tuple[str, List[Tuple[int, str]]]:
        """
        Extracts text from PDF bytes using pypdf.
        Returns combined text and page-by-page mapping.
        Does NOT embed [Page N] markers in the returned page text.
        """
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages_content = []
        full_text_parts = []

        for idx, page in enumerate(reader.pages):
            page_num = idx + 1
            txt = page.extract_text() or ""
            pages_content.append((page_num, txt.strip()))
            full_text_parts.append(f"[Page {page_num}]\n" + txt.strip())

        return "\n\n".join(full_text_parts), pages_content

    def _split_by_sections(self, content: str) -> List[Tuple[str, str]]:
        lines = content.split("\n")
        sections: List[Tuple[str, str]] = []
        current_title = "Overview"
        current_lines: List[str] = []
        known_sections = {
            "candidate details", "hsc details", "admission details", "documents",
            "declaration", "executive summary", "technical specifications",
            "technical specifications & efficiency", "storage overview",
            "roundtrip efficiency & metrics", "degradation rates & lifecycle",
            "capital expenditure trends", "warranty and guarantee standards",
            "financial subsidies & rebates", "grid interconnection requirements"
        }

        def flush_section() -> None:
            nonlocal current_lines
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
                current_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                current_lines.append(line)
                continue

            markdown_heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
            prefix_heading = re.match(
                r"^([A-Za-z][A-Za-z0-9 &/().-]{2,70})\s*[:：]\s*(.*)$", stripped
            )
            prefix_name = (
                prefix_heading.group(1).strip().casefold()
                if prefix_heading else ""
            )
            if markdown_heading:
                flush_section()
                current_title = markdown_heading.group(2).strip()
                continue
            if prefix_heading and prefix_name in known_sections:
                flush_section()
                current_title = prefix_heading.group(1).strip()
                remainder = prefix_heading.group(2).strip()
                if remainder:
                    current_lines.append(remainder)
                continue
            if stripped.isupper() and len(stripped) <= 80 and len(re.findall(r"[A-Z]", stripped)) >= 5:
                flush_section()
                current_title = stripped.title()
                continue

            current_lines.append(line)

        flush_section()
        return sections if sections else [("Overview", content)]

    def _word_boundary_overlap(self, text: str, overlap_size: int) -> str:
        """Returns the last `overlap_size` chars cut at a word/sentence boundary."""
        if len(text) <= overlap_size:
            return text
        slice_start = len(text) - overlap_size
        # Try to find a sentence boundary
        search_region = text[slice_start:]
        sent_match = re.search(r'(?<=[.!?])\s+', search_region)
        if sent_match:
            return search_region[sent_match.end():]
        # Fallback: word boundary
        word_match = re.search(r'\s+', search_region)
        if word_match:
            return search_region[word_match.end():]
        return search_region

    def _split_large_paragraph_indexed(
        self, text: str, size: int, overlap: int, start_index: int
    ) -> List[Tuple[str, int]]:
        """Splits a large paragraph into sized chunks, returns (text, chunk_index) pairs."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = []
        curr = ""
        idx = start_index
        for s in sentences:
            if len(curr) + len(s) < size:
                curr += (" " + s if curr else s)
            else:
                if curr:
                    result.append((curr, idx))
                    idx += 1
                    # overlap at sentence boundary
                    overlap_text = self._word_boundary_overlap(curr, overlap)
                    curr = overlap_text + " " + s if overlap_text else s
                else:
                    # Very long sentence: slice at word boundary
                    while len(s) > size:
                        word_cut = s[:size].rfind(' ')
                        cut = word_cut if word_cut > 0 else size
                        result.append((s[:cut], idx))
                        idx += 1
                        s = s[cut:].lstrip()
                    curr = s
        if curr:
            result.append((curr, idx))
        return result

    def _split_large_paragraph(self, text: str, size: int, overlap: int) -> List[str]:
        """Legacy helper retained for backward compatibility."""
        return [t for t, _ in self._split_large_paragraph_indexed(text, size, overlap, 0)]


chunker = Chunker(chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap)
