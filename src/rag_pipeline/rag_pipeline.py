"""
Complete RAG Pipeline
Integrates chunking + embedding + retrieval for datasheet-based constraint extraction
"""

import os
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.gpt4ifx_client import create_client
from src.rag_pipeline.chunk_datasheets import chunk_datasheets
from src.rag_pipeline.vectorstore import VectorStore, create_vectorstore_from_chunks


class RAGPipeline:
    """
    Complete RAG pipeline for datasheet-based fuzzing
    
    Workflow:
    1. Chunk datasheets into 512-token segments
    2. Embed chunks using GPT4IFX embedding model
    3. Store in FAISS vectorstore
    4. Retrieve relevant chunks for queries
    5. Provide citations (document, page)
    """
    
    def __init__(
        self,
        datasheet_dir: str = "data/datasheets",
        vectorstore_dir: str = "data/vectorstore",
        client = None,  # GPT4IFX client (created if None)
        allow_no_auth: bool = False,
    ):

        """
        Initialize RAG pipeline
        
        Args:
            datasheet_dir: Directory containing PDF datasheets
            vectorstore_dir: Directory to save/load vectorstore
            client: GPT4IFX client (optional, created if None)
        """
        self.datasheet_dir = datasheet_dir
        self.vectorstore_dir = vectorstore_dir
        
        # Create client if not provided
        if client is None:
            if allow_no_auth:
                self.client = None
            else:
                # CA bundle resolution: env vars first, then repo-local
                # ca-bundle.crt (laptop), then system bundle (Ubuntu/IFX).
                # We do NOT pass a non-existent path because HTTPX raises
                # SSLError that the auth chain silently swallows.
                ca_bundle = (
                    os.getenv("GPT4IFX_CA_BUNDLE")
                    or os.getenv("REQUESTS_CA_BUNDLE")
                    or os.getenv("SSL_CERT_FILE")
                )
                if not ca_bundle:
                    for cand in ("ca-bundle.crt", "/etc/ssl/certs/ca-certificates.crt"):
                        if os.path.exists(cand):
                            ca_bundle = cand
                            break
                self.client = create_client(api_key=os.getenv("GPT4IFX_API_KEY"), ca_bundle_path=ca_bundle)
        else:
            self.client = client



        
        self.vectorstore = None
        self.chunks_by_doc = None
    
    def build_index(self, force_rebuild: bool = False):
        """
        Build vectorstore index from datasheets
        
        Args:
            force_rebuild: If True, rebuild even if index exists
        """
        # Check if index already exists
        index_path = Path(self.vectorstore_dir) / "faiss.index"
        if index_path.exists() and not force_rebuild:
            print(f"✅ Index already exists: {index_path}")
            print("   Loading existing index...")
            self.load_index()
            return
        
        print("="*60)
        print("Building RAG Index")
        print("="*60)
        
        # Step 1: Chunk datasheets (PDFs)
        print("\n[1/3] Chunking datasheets...")
        self.chunks_by_doc = chunk_datasheets(self.datasheet_dir)

        if not self.chunks_by_doc:
            # Allow non-PDF corpora (README.md, docs/*.md, exported HTML) to be indexed.
            # The CLI ingestion step copies supported extensions into <index_dir>/corpus.
            # If there are no PDFs, proceed with a text-only index.
            print(f"⚠️  No PDF datasheets found in {self.datasheet_dir}; building text-only index from corpus files")
            self.chunks_by_doc = {}

        # Step 1b: Also ingest text/rst/md corpus files alongside any PDFs.
        # Previously this only ran when chunks_by_doc was empty, which meant
        # .rst/.md files were silently skipped whenever a PDF was present.
        corpus_dir = Path(self.datasheet_dir)
        text_extensions = {".md", ".txt", ".html", ".htm", ".docx", ".rst"}
        text_files = [
            f for f in sorted(corpus_dir.glob("*"))
            if f.is_file() and f.suffix.lower() in text_extensions
        ]
        if text_files:
            print(f"📄 Also indexing {len(text_files)} text/rst/md corpus files...")
            for f in text_files:
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore").strip()
                    if not text:
                        continue
                    self.chunks_by_doc[f.name] = [
                        {
                            "chunk_id": 0,
                            "document": f.name,
                            "page": 1,
                            "section": "corpus",
                            "text": text,
                            "tokens": max(1, len(text) // 4),
                        }
                    ]
                except Exception:
                    pass

        # Step 2: Create vectorstore
        print("\n[2/3] Creating vectorstore...")

        self.vectorstore = create_vectorstore_from_chunks(
            self.chunks_by_doc,
            self.client,
            self.vectorstore_dir
        )
        
        # Step 3: Save index
        print("\n[3/3] Saving index...")
        print(f"✅ Index built and saved to: {self.vectorstore_dir}")
        
        # Statistics
        stats = self.vectorstore.get_stats()
        print(f"\n📊 Index Statistics:")
        print(f"   Total chunks: {stats['total_chunks']}")
        print(f"   Documents: {len(stats['documents'])}")
        for doc in stats['documents']:
            print(f"      - {doc}")
    
    def load_index(self):
        """Load existing vectorstore from disk"""
        self.vectorstore = VectorStore(embedding_dim=1536, index_type="flat")
        self.vectorstore.load(self.vectorstore_dir)
        
        stats = self.vectorstore.get_stats()
        print(f"✅ Index loaded: {stats['total_chunks']} chunks from {len(stats['documents'])} documents")
    
    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.3,  # Lowered from 0.7 to get more results
        show_results: bool = True
    ) -> list:
        """
        Retrieve relevant datasheet chunks for query
        
        Args:
            query: Search query (e.g., "I2C timing constraints")
            top_k: Number of results to return
            similarity_threshold: Minimum similarity score
            show_results: Whether to print results
            
        Returns:
            List of result dictionaries
        """
        if self.vectorstore is None:
            raise ValueError("Vectorstore not loaded. Call build_index() or load_index() first.")

        if self.client is None:
            raise ValueError("RAGPipeline client is not configured (mock/offline mode). Cannot embed queries.")

        
        results = self.vectorstore.search(
            query=query,
            client=self.client,
            top_k=top_k,
            similarity_threshold=similarity_threshold
        )
        
        if show_results:
            print(f"\n🔍 Query: \"{query}\"")
            print(f"📊 Found {len(results)} relevant chunks:\n")
            
            for result in results:
                print(f"[{result['rank']}] Similarity: {result['similarity']:.3f}")
                print(f"    Citation: {result['citation']}")
                print(f"    Text: {result['text'][:200]}...")
                print()
        
        return results
    
    def retrieve_context(
        self,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.3  # Lowered from 0.7 to get more results
    ) -> str:
        """
        Retrieve context for LLM prompt (concatenated chunks with citations)
        
        Args:
            query: Search query
            top_k: Number of chunks to retrieve
            similarity_threshold: Minimum similarity
            
        Returns:
            Formatted context string with citations
        """
        results = self.retrieve(
            query=query,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            show_results=False
        )
        
        if not results:
            return "No relevant datasheet information found."
        
        # Format as context
        context_parts = []
        for result in results:
            context_parts.append(
                f"[Source: {result['citation']}]\n{result['text']}"
            )
        
        return "\n\n".join(context_parts)


def main():
    """Test RAG pipeline"""
    print("="*60)
    print("RAG Pipeline Test")
    print("="*60)

    # Check API key/token availability (supports permanent token flow too)
    if not (os.getenv("GPT4IFX_API_KEY") or (os.getenv("LLAMA_USER") and os.getenv("LLAMA_PASSWORD"))):
        print("\n⚠️  No GPT4IFX credentials configured.")
        print("   Use ONE of the following:")
        print("   - export LLAMA_USER=...; export LLAMA_PASSWORD=...   (recommended)")
        print("   - export GPT4IFX_API_KEY=...                         (temporary token)")
        return

    # Initialize pipeline

    rag = RAGPipeline(
        datasheet_dir="data/datasheets",
        vectorstore_dir="data/vectorstore"
    )
    
    # Build index (or load if exists)
    rag.build_index(force_rebuild=False)
    
    # Test queries
    test_queries = [
        "I2C slave address configuration",
        "PMBus command register addresses",
        "ADC voltage measurement range",
        "Timing constraints for I2C communication",
        "Hot-swap controller protection features"
    ]
    
    print("\n" + "="*60)
    print("Testing Retrieval")
    print("="*60)
    
    for query in test_queries:
        results = rag.retrieve(query, top_k=3, similarity_threshold=0.6)
        
        if results:
            print(f"\n✅ Query: \"{query}\"")
            print(f"   Top result: {results[0]['citation']} (similarity: {results[0]['similarity']:.3f})")
        else:
            print(f"\n⚠️  Query: \"{query}\" - No results above threshold")
    
    print("\n" + "="*60)
    print("✅ RAG Pipeline Test Complete")
    print("="*60)


if __name__ == "__main__":
    main()
