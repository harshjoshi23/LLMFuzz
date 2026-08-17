"""
Datasheet PDF Chunker
Extracts text from PDF datasheets and chunks into RAG-friendly segments
"""

import os
import re
from typing import List, Dict, Tuple
from pathlib import Path
import PyPDF2

try:
    import tiktoken
except ModuleNotFoundError:
    tiktoken = None


class _ApproxTokenizer:
    """Fallback tokenizer for dry-run/test environments without tiktoken."""

    def encode(self, text: str) -> List[int]:
        if not text:
            return []
        return list(range(max(1, (len(text) + 3) // 4)))

class DatasheetChunker:
    """
    Chunk PDF datasheets for RAG pipeline
    - Extracts text from PDFs
    - Splits into 512-token chunks with 50-token overlap
    - Preserves metadata (page number, section, document name)
    """
    
    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        encoding_name: str = "cl100k_base"
    ):
        """
        Initialize chunker
        
        Args:
            chunk_size: Target tokens per chunk (default: 512)
            chunk_overlap: Overlapping tokens between chunks (default: 50)
            encoding_name: Tiktoken encoding for token counting
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.tokenizer = tiktoken.get_encoding(encoding_name) if tiktoken is not None else _ApproxTokenizer()
        
    def extract_text_from_pdf(self, pdf_path: str) -> List[Tuple[int, str]]:
        """
        Extract text from PDF with page numbers
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of (page_number, text) tuples
        """
        pages = []
        
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                num_pages = len(pdf_reader.pages)
                
                print(f"📄 Extracting text from: {Path(pdf_path).name}")
                print(f"   Pages: {num_pages}")
                
                for page_num in range(num_pages):
                    page = pdf_reader.pages[page_num]
                    text = page.extract_text()
                    
                    if text.strip():  # Only add non-empty pages
                        pages.append((page_num + 1, text))
                
                print(f"   ✅ Extracted {len(pages)} pages with text")
                
        except Exception as e:
            print(f"   ❌ Error extracting PDF: {str(e)}")
            raise
        
        return pages
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        return len(self.tokenizer.encode(text))
    
    def split_into_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences (heuristic for technical docs)
        Handles:
        - Period followed by space and capital letter
        - Section numbers (e.g., "5.2.1 Register Map")
        - Abbreviations (e.g., "Fig.", "e.g.", "i.e.")
        """
        # Replace common abbreviations to avoid false splits
        text = text.replace("e.g.", "eg")
        text = text.replace("i.e.", "ie")
        text = text.replace("Fig.", "Fig")
        text = text.replace("Sec.", "Sec")
        
        # Split on period + space + capital letter
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
        
        # Restore abbreviations
        sentences = [s.replace("eg", "e.g.").replace("ie", "i.e.").replace("Fig", "Fig.").replace("Sec", "Sec.") 
                     for s in sentences]
        
        return sentences
    
    def create_chunks(self, pages: List[Tuple[int, str]], doc_name: str) -> List[Dict]:
        """
        Create overlapping chunks from extracted pages
        
        Args:
            pages: List of (page_number, text) tuples
            doc_name: Document name for metadata
            
        Returns:
            List of chunk dictionaries with metadata
        """
        chunks = []
        chunk_id = 0
        
        for page_num, page_text in pages:
            # Split page into sentences
            sentences = self.split_into_sentences(page_text)
            
            current_chunk = []
            current_tokens = 0
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                
                sentence_tokens = self.count_tokens(sentence)
                
                # If adding this sentence exceeds chunk_size, save current chunk
                if current_tokens + sentence_tokens > self.chunk_size and current_chunk:
                    chunk_text = " ".join(current_chunk)
                    chunks.append({
                        "chunk_id": chunk_id,
                        "text": chunk_text,
                        "tokens": current_tokens,
                        "page": page_num,
                        "document": doc_name,
                        "metadata": {
                            "source": doc_name,
                            "page": page_num,
                            "chunk_index": chunk_id
                        }
                    })
                    chunk_id += 1
                    
                    # Keep overlap tokens for next chunk
                    overlap_text = " ".join(current_chunk[-3:])  # Keep last ~3 sentences as overlap
                    overlap_tokens = self.count_tokens(overlap_text)
                    
                    if overlap_tokens <= self.chunk_overlap:
                        current_chunk = current_chunk[-3:]
                        current_tokens = overlap_tokens
                    else:
                        current_chunk = []
                        current_tokens = 0
                
                # Add sentence to current chunk
                current_chunk.append(sentence)
                current_tokens += sentence_tokens
            
            # Save remaining chunk for this page
            if current_chunk:
                chunk_text = " ".join(current_chunk)
                chunks.append({
                    "chunk_id": chunk_id,
                    "text": chunk_text,
                    "tokens": current_tokens,
                    "page": page_num,
                    "document": doc_name,
                    "metadata": {
                        "source": doc_name,
                        "page": page_num,
                        "chunk_index": chunk_id
                    }
                })
                chunk_id += 1
        
        return chunks
    
    def chunk_pdf(self, pdf_path: str) -> List[Dict]:
        """
        Complete pipeline: Extract PDF → Chunk into segments
        
        Args:
            pdf_path: Path to PDF datasheet
            
        Returns:
            List of chunk dictionaries
        """
        doc_name = Path(pdf_path).stem
        
        # Extract text from PDF
        pages = self.extract_text_from_pdf(pdf_path)
        
        # Create chunks
        chunks = self.create_chunks(pages, doc_name)
        
        # Statistics
        total_tokens = sum(c['tokens'] for c in chunks)
        avg_tokens = total_tokens / len(chunks) if chunks else 0
        
        print(f"\n📊 Chunking Statistics:")
        print(f"   Total chunks: {len(chunks)}")
        print(f"   Total tokens: {total_tokens}")
        print(f"   Avg tokens/chunk: {avg_tokens:.1f}")
        print(f"   Target chunk size: {self.chunk_size}")
        print(f"   Chunk overlap: {self.chunk_overlap}")
        
        return chunks
    
    def chunk_directory(self, directory_path: str, file_extension: str = ".pdf") -> Dict[str, List[Dict]]:
        """
        Chunk all PDFs in a directory
        
        Args:
            directory_path: Directory containing PDF datasheets
            file_extension: File extension to process (default: .pdf)
            
        Returns:
            Dict mapping document names to chunks
        """
        directory = Path(directory_path)
        pdf_files = list(directory.glob(f"*{file_extension}"))
        
        if not pdf_files:
            print(f"⚠️  No {file_extension} files found in {directory_path}")
            return {}
        
        print(f"\n🔍 Found {len(pdf_files)} PDF files:")
        for pdf in pdf_files:
            print(f"   - {pdf.name}")
        
        all_chunks = {}
        
        for pdf_path in pdf_files:
            print(f"\n{'='*60}")
            try:
                chunks = self.chunk_pdf(str(pdf_path))
                all_chunks[pdf_path.stem] = chunks
                print(f"✅ Successfully chunked: {pdf_path.name}")
            except Exception as e:
                print(f"❌ Failed to chunk {pdf_path.name}: {str(e)}")
        
        print(f"\n{'='*60}")
        print(f"📦 Total documents processed: {len(all_chunks)}")
        print(f"📦 Total chunks created: {sum(len(chunks) for chunks in all_chunks.values())}")
        
        return all_chunks


# Convenience function
def chunk_datasheets(datasheet_dir: str = "data/datasheets") -> Dict[str, List[Dict]]:
    """
    Quick chunking of all datasheets in directory
    
    Usage:
        from src.rag_pipeline.chunk_datasheets import chunk_datasheets
        chunks = chunk_datasheets("data/datasheets")
    """
    chunker = DatasheetChunker(chunk_size=512, chunk_overlap=50)
    return chunker.chunk_directory(datasheet_dir)


if __name__ == "__main__":
    # Test script
    print("="*60)
    print("Datasheet Chunker Test")
    print("="*60)
    
    # Chunk all datasheets
    # Get correct path whether run from root or src/rag_pipeline
    if os.path.exists("data/datasheets"):
        datasheet_dir = "data/datasheets"
    elif os.path.exists("../../data/datasheets"):
        datasheet_dir = "../../data/datasheets"
    else:
        print(f"❌ Directory not found: data/datasheets")
        print("Run this from project root: python src/rag_pipeline/chunk_datasheets.py")
        exit(1)
    
    chunks_by_doc = chunk_datasheets(datasheet_dir)
    
    # Show sample chunks
    print(f"\n{'='*60}")
    print("Sample Chunks:")
    print("="*60)
    
    for doc_name, chunks in chunks_by_doc.items():
        if chunks:
            print(f"\n📄 {doc_name}:")
            sample_chunk = chunks[0]
            print(f"   Chunk ID: {sample_chunk['chunk_id']}")
            print(f"   Page: {sample_chunk['page']}")
            print(f"   Tokens: {sample_chunk['tokens']}")
            print(f"   Text preview: {sample_chunk['text'][:200]}...")
