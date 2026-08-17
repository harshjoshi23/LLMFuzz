"""
FAISS Vectorstore for RAG Pipeline
Handles embedding generation and similarity search for datasheet chunks
"""

import os
import json
import pickle
import time
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import numpy as np

try:
    import faiss
except ImportError:
    print("⚠️  FAISS not installed. Install with: pip install faiss-cpu")
    faiss = None

class VectorStore:
    """FAISS-based vectorstore.

    IMPORTANT:
    - Embedding backend is provided by the caller (client.embed_text / embed_texts).
    - This keeps embeddings 'real' and consistent with GPT4IFX auth surface.
    """

    """
    FAISS-based vectorstore for datasheet chunks
    - Embeds chunks using GPT4IFX embedding model
    - Stores embeddings in FAISS index
    - Retrieves top-K similar chunks
    - Includes citations (document, page, chunk text)
    """
    
    def __init__(
        self,
        embedding_dim: int = 1536,  # text-embedding-3-small dimensions
        index_type: str = "flat"  # "flat" for exact search, "ivf" for approximate
    ):
        """
        Initialize vectorstore
        
        Args:
            embedding_dim: Dimension of embedding vectors (1536 for text-embedding-3-small)
            index_type: FAISS index type ("flat" or "ivf")
        """
        if faiss is None:
            raise ImportError("FAISS not available. Install with: pip install faiss-cpu")
        
        self.embedding_dim = embedding_dim
        self.index_type = index_type
        
        # Initialize FAISS index
        if index_type == "flat":
            self.index = faiss.IndexFlatL2(embedding_dim)  # L2 distance (Euclidean)
        else:
            # IVF index for large datasets (approximate search)
            quantizer = faiss.IndexFlatL2(embedding_dim)
            self.index = faiss.IndexIVFFlat(quantizer, embedding_dim, 100)  # 100 clusters
        
        # Storage for chunk metadata (parallel to FAISS index)
        self.chunks = []
        self.metadata = []
        
        print(f"✅ VectorStore initialized (dim={embedding_dim}, index={index_type})")
    
    def embed_texts(
        self,
        texts: List[str],
        client,  # GPT4IFX client
        embedding_model: str = "text-embedding-3-small",
        batch_size: int = 100
    ) -> np.ndarray:
        """
        Embed texts using GPT4IFX embedding model.

        The GPT4IFX gateway enforces ~15 requests/minute for embeddings.
        We throttle per *call* (not per batch) so we never burst over the limit
        regardless of batch_size. We also clip overly long inputs to avoid the
        8192-token gateway error.

        Args:
            texts: List of text strings to embed
            client: GPT4IFX client instance
            embedding_model: Embedding model name
            batch_size: kept for backwards compatibility; only used for logging

        Returns:
            numpy array of shape (num_texts, embedding_dim)
        """
        import os

        # 15 req/min = 4.0s between calls. We use 4.2s + the client's own
        # exponential backoff to stay comfortably below the limit.
        per_call_sleep = float(os.environ.get("THESIS_EMBED_SLEEP", "4.2"))
        # Gateway caps input at 8192 tokens.
        # xlsx.txt can be very dense (little whitespace) so we use ~4 chars/token
        # with a conservative margin: 5000 tokens * 4 = 20000 chars.
        # Override with THESIS_EMBED_MAX_CHARS if needed.
        max_chars = int(os.environ.get("THESIS_EMBED_MAX_CHARS", "20000"))

        embeddings: List[List[float]] = []
        print(f"🔄 Embedding {len(texts)} texts (per_call_sleep={per_call_sleep}s)...")

        for idx, text in enumerate(texts):
            if idx > 0:
                time.sleep(per_call_sleep)

            # Skip empty inputs; avoid API 400 "input cannot be an empty string"
            if text is None or not str(text).strip():
                embeddings.append([0.0] * self.embedding_dim)
                continue

            clipped = str(text)
            if len(clipped) > max_chars:
                clipped = clipped[:max_chars]

            try:
                emb = client.embed_text(clipped, model=embedding_model)
                embeddings.append(emb)
            except Exception as e:
                print(f"⚠️  Failed to embed text idx={idx} (len={len(clipped)}): {e}")
                embeddings.append([0.0] * self.embedding_dim)

            if (idx + 1) % 25 == 0:
                print(f"   Embedded {idx + 1}/{len(texts)} texts...")

        print(f"✅ Embedding complete: {len(embeddings)} vectors")
        return np.array(embeddings, dtype=np.float32)
    
    def add_chunks(
        self,
        chunks: List[Dict],
        client,  # GPT4IFX client
        embedding_model: str = "text-embedding-3-small"
    ):
        """
        Add datasheet chunks to vectorstore
        
        Args:
            chunks: List of chunk dictionaries (from DatasheetChunker)
            client: GPT4IFX client for embedding generation
            embedding_model: Embedding model name
        """
        if not chunks:
            print("⚠️  No chunks to add")
            return
        
        # Extract texts
        texts = [chunk['text'] for chunk in chunks]
        
        # Generate embeddings
        embeddings = self.embed_texts(texts, client, embedding_model)
        
        # Add to FAISS index
        if self.index_type == "ivf" and not self.index.is_trained:
            print("🔄 Training IVF index...")
            self.index.train(embeddings)
            print("✅ IVF index trained")
        
        self.index.add(embeddings)
        
        # Store metadata
        self.chunks.extend(chunks)
        self.metadata.extend([{
            "document": chunk['document'],
            "page": chunk['page'],
            "chunk_id": chunk['chunk_id'],
            "tokens": chunk['tokens']
        } for chunk in chunks])
        
        print(f"✅ Added {len(chunks)} chunks to vectorstore (total: {self.index.ntotal})")
    
    def search(
        self,
        query: str,
        client,  # GPT4IFX client
        top_k: int = 5,
        embedding_model: str = "text-embedding-3-small",
        similarity_threshold: float = 0.3  # Lowered from 0.7 to get more results
    ) -> List[Dict]:
        """
        Search vectorstore for similar chunks
        
        Args:
            query: Search query text
            client: GPT4IFX client for query embedding
            top_k: Number of top results to return
            embedding_model: Embedding model name
            similarity_threshold: Minimum cosine similarity (0.0-1.0)
            
        Returns:
            List of result dictionaries with chunk text, metadata, and similarity score
        """
        if self.index.ntotal == 0:
            print("⚠️  Vectorstore is empty")
            return []
        
        # Embed query
        try:
            query_embedding = client.embed_text(query, model=embedding_model)
        except Exception as e:
            # Most common failure in corp networks: 403 for embeddings permission.
            # In that case, degrade gracefully by returning no RAG hits.
            # Seed phase will then proceed with empty constraints and still generate baseline seeds.
            print(f"⚠️  Query embedding failed; continuing without RAG hits: {e}")
            return []

        query_vector = np.array([query_embedding], dtype=np.float32)

        # Validate embedding dimensionality matches FAISS index.
        # FAISS will assert internally; we prefer a clear error message.
        qdim = int(query_vector.shape[1])
        idx_dim = int(getattr(self.index, "d", -1))
        if idx_dim != -1 and qdim != idx_dim:
            raise ValueError(
                "Vectorstore embedding dimension mismatch: "
                f"query_dim={qdim} but index_dim={idx_dim}. "
                "This usually means the vectorstore was built with a different embedding model. "
                "Rebuild the vectorstore with the same embedding model used at query time, "
                "or configure embedding_dim/model consistently."
            )

        # Search FAISS index
        distances, indices = self.index.search(query_vector, top_k)
        
        # Convert L2 distances to a similarity-like score.
        # NOTE: IndexFlatL2 returns squared L2 distance. If vectors are unit-normalized,
        # cosine similarity relates to squared L2 via: d^2 = 2 - 2*cos => cos = 1 - d^2/2.
        # We approximate similarity as 1 - (d2 / 2).
        similarities = 1 - (distances[0] / 2.0)
        
        # Build results
        results = []
        for idx, (index, distance, similarity) in enumerate(zip(indices[0], distances[0], similarities)):
            if index == -1:  # FAISS returns -1 for missing results
                continue
            
            if similarity < similarity_threshold:
                continue
            
            chunk = self.chunks[index]
            metadata = self.metadata[index]
            
            results.append({
                "rank": idx + 1,
                "text": chunk['text'],
                "document": metadata['document'],
                "page": metadata['page'],
                "chunk_id": metadata['chunk_id'],
                "similarity": float(similarity),
                "distance": float(distance),
                "citation": f"{metadata['document']}, Page {metadata['page']}"
            })
        
        return results
    
    def save(self, save_dir: str = "data/vectorstore"):
        """
        Save vectorstore to disk
        
        Args:
            save_dir: Directory to save index and metadata
        """
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)
        
        # Save FAISS index
        index_path = save_path / "faiss.index"
        faiss.write_index(self.index, str(index_path))
        
        # Save chunks and metadata
        chunks_path = save_path / "chunks.pkl"
        with open(chunks_path, 'wb') as f:
            pickle.dump({
                "chunks": self.chunks,
                "metadata": self.metadata,
                "embedding_dim": self.embedding_dim,
                "index_type": self.index_type
            }, f)
        
        print(f"✅ Vectorstore saved to: {save_dir}")
        print(f"   - FAISS index: {index_path}")
        print(f"   - Metadata: {chunks_path}")
    
    def load(self, save_dir: str = "data/vectorstore"):
        """
        Load vectorstore from disk
        
        Args:
            save_dir: Directory containing saved index and metadata
        """
        save_path = Path(save_dir)
        
        # Load FAISS index
        index_path = save_path / "faiss.index"
        if not index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {index_path}")
        
        self.index = faiss.read_index(str(index_path))
        
        # Load chunks and metadata
        chunks_path = save_path / "chunks.pkl"
        if not chunks_path.exists():
            raise FileNotFoundError(f"Chunks metadata not found: {chunks_path}")
        
        with open(chunks_path, 'rb') as f:
            data = pickle.load(f)
            self.chunks = data['chunks']
            self.metadata = data['metadata']
            self.embedding_dim = data['embedding_dim']
            self.index_type = data['index_type']
        
        print(f"✅ Vectorstore loaded from: {save_dir}")
        print(f"   - Total chunks: {len(self.chunks)}")
        print(f"   - Index size: {self.index.ntotal}")
    
    def get_stats(self) -> Dict:
        """Get vectorstore statistics"""
        return {
            "total_chunks": len(self.chunks),
            "index_size": self.index.ntotal,
            "embedding_dim": self.embedding_dim,
            "index_type": self.index_type,
            "documents": list(set(m['document'] for m in self.metadata))
        }


# Convenience function
def create_vectorstore_from_chunks(
    chunks_by_doc: Dict[str, List[Dict]],
    client,  # GPT4IFX client
    save_dir: str = "data/vectorstore"
) -> VectorStore:
    """
    Create vectorstore from chunked datasheets
    
    Args:
        chunks_by_doc: Dictionary mapping document names to chunks
        client: GPT4IFX client for embedding generation
        save_dir: Directory to save vectorstore
        
    Returns:
        VectorStore instance
    """
    # Flatten all chunks
    all_chunks = []
    for doc_name, chunks in chunks_by_doc.items():
        all_chunks.extend(chunks)
    
    # Create vectorstore
    vectorstore = VectorStore(embedding_dim=1536, index_type="flat")
    vectorstore.add_chunks(all_chunks, client)
    
    # Save to disk
    vectorstore.save(save_dir)
    
    return vectorstore


if __name__ == "__main__":
    # Test script (requires API key)
    print("="*60)
    print("VectorStore Test")
    print("="*60)
    
    # Check if we can run (needs GPT4IFX credentials)
    has_creds = bool(os.getenv("GPT4IFX_API_KEY") or (os.getenv("LLAMA_USER") and os.getenv("LLAMA_PASSWORD")))
    if not has_creds:
        print("\n⚠️  No GPT4IFX credentials configured!")
        print("Use ONE of:")
        print("  - export LLAMA_USER=...; export LLAMA_PASSWORD=...   (recommended)")
        print("  - export GPT4IFX_API_KEY=...                         (temporary token)")
        print("\nFor now, showing vectorstore structure without embeddings...")

        
        # Show structure
        vs = VectorStore(embedding_dim=1536, index_type="flat")
        print(f"\n✅ VectorStore created:")
        print(f"   Embedding dim: {vs.embedding_dim}")
        print(f"   Index type: {vs.index_type}")
        print(f"   Index size: {vs.index.ntotal}")
    else:
        print("\n✅ API key found - full test would run here")
        print("   (Skipping to avoid API calls in test mode)")
