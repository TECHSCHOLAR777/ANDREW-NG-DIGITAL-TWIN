import os
import re
import time
import argparse
from pathlib import Path
import numpy as np
from tqdm import tqdm

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# Try importing sentence_transformers
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("Warning: sentence-transformers is not installed. Please run: pip install sentence-transformers")
    SentenceTransformer = None

# ================================================================================
# Constants & Configuration
# ================================================================================

DB_PATH = Path("data/chroma_db")
CLEANED_DIR = Path("data/cleaned")
COLLECTION_NAME = "andrew_ng_digital_twin"
MODEL_NAME = "all-MiniLM-L6-v2"

# Canonical examples list - Regex patterns
CANONICAL_PATTERNS = [
    r"\blego\s+block\b", r"\blego\s+brick\b", r"\blego\b",
    r"\bcat\s+recognition\b", r"\bis\s+it\s+a\s+cat\b", r"\bnon-cat\b", r"\bcat\s+detector\b",
    r"\bhousing\s+price\b", r"\bhouse\s+price\b", r"\bhouse\s+size\b",
    r"\bspam\s+detection\b", r"\bspam\s+email\b", r"\bemail\s+classifier\b",
    r"\bwalking\s+down\s+a\s+hill\b", r"\bgradient\s+descent\b", r"\bfog\b",
    r"\bnew\s+electricity\b", r"\bintellectual\s+honesty\b",
    r"\bmars\s+overpopulation\b", r"\boverpopulation\s+on\s+mars\b",
    r"\bdata-centric\b", r"\bdata\s+centric\b",
    r"\bagentic\s+workflow\b", r"\bagentic\s+ai\b", r"\bmulti-agent\b", r"\bagentic\s+design\b",
    r"\bdon't\s+worry\b", r"\bdon't\s+worry\s+if\s+you\b", r"\bdon't\s+worry\s+about\s+it\b",
    r"\bsuperpower\b", r"\bdeep\s+learning\s+is\s+a\s+superpower\b"
]

# Compile patterns for fast search
CANONICAL_REGEX = [re.compile(p, re.IGNORECASE) for p in CANONICAL_PATTERNS]

# ================================================================================
# Helper Functions
# ================================================================================

def is_canonical_example(text: str) -> bool:
    """Checks if the chunk contains one of Andrew Ng's signature pedagogical examples or catchphrases."""
    return any(pattern.search(text) for pattern in CANONICAL_REGEX)

def determine_domain(text: str, filename: str, doc_type: str) -> str:
    """Classifies the semantic domain of a chunk based on source cues and keyword analysis."""
    text_lower = text.lower()
    filename_lower = filename.lower()
    
    # Career advice check
    if "career_in_ai" in filename_lower or "fridman" in filename_lower or "career" in text_lower:
        if doc_type in ["pdfs", "transcripts"]:
            return "career_advice"
            
    # Agentic AI check
    if "sequoia" in filename_lower or "build" in filename_lower or "agentic" in text_lower or "multi-agent" in text_lower:
        return "agentic_ai"
        
    # ML Theory check
    if "cs229" in filename_lower or "theory" in text_lower or "derivation" in text_lower or "linear regression" in text_lower:
        return "ml_theory"
        
    # Deep Learning check
    if "cs230" in filename_lower or "deep learning" in text_lower or "neural network" in text_lower:
        return "deep_learning"
        
    # Fallback by doc_type
    if doc_type == "pdfs":
        if "career" in filename_lower:
            return "career_advice"
        return "ml_theory"
    elif doc_type == "transcripts":
        return "deep_learning"
    elif doc_type == "the_batch":
        return "ai_strategy"
    elif doc_type == "blog_posts":
        return "ai_strategy"
        
    return "ai_strategy"

def parse_metadata_headers(content: str) -> tuple[dict, str]:
    """Parses standard metadata headers at the top of cleaned documents."""
    lines = content.splitlines()
    metadata = {}
    body_start_idx = 0
    
    for idx, line in enumerate(lines):
        if line.startswith("# Title:"):
            metadata["title"] = line.replace("# Title:", "").strip()
        elif line.startswith("# URL:"):
            metadata["url"] = line.replace("# URL:", "").strip()
        elif line.startswith("# Date:"):
            metadata["date"] = line.replace("# Date:", "").strip()
        elif line.startswith("# Domain:"):
            metadata["domain"] = line.replace("# Domain:", "").strip()
        elif line.startswith("# Is Ng Authored:"):
            metadata["is_ng_authored"] = line.replace("# Is Ng Authored:", "").strip().lower() == "true"
        elif line.startswith("# Has Editorial:"):
            metadata["has_editorial"] = line.replace("# Has Editorial:", "").strip().lower() == "true"
        elif line.startswith("# Transcript Type:"):
            metadata["transcript_type"] = line.replace("# Transcript Type:", "").strip()
        elif line.startswith("=" * 10) or line.startswith("-" * 10):
            body_start_idx = idx + 1
            break
        elif not line.startswith("#") and line.strip() != "":
            # No metadata prefix, body has started
            body_start_idx = idx
            break
            
    body_text = "\n".join(lines[body_start_idx:])
    return metadata, body_text.strip()


def infer_source_authority(doc_type: str, metadata: dict, filename: str) -> float:
    """Assigns a lightweight quality prior to help retrieval prefer Andrew's direct voice."""
    score = 0.5

    if doc_type == "pdfs":
        score = 1.0
    elif doc_type == "transcripts":
        score = 0.95
    elif doc_type == "the_batch":
        score = 0.8 if metadata.get("has_editorial") else 0.6
    elif doc_type == "blog_posts":
        score = 0.75 if metadata.get("is_ng_authored", True) else 0.35

    lowered = filename.lower()
    if any(marker in lowered for marker in ["ambassador-spotlight", "heroes-of-deep-learning", "hodl", "working-ai"]):
        score -= 0.2

    return max(0.1, min(score, 1.0))

# ================================================================================
# Custom Hybrid Length-Semantic Chunker
# ================================================================================

class HybridChunker:
    def __init__(self, model, target_len=1000, max_len=1500, min_len=200, semantic_threshold=0.40):
        self.model = model
        self.target_len = target_len
        self.max_len = max_len
        self.min_len = min_len
        self.semantic_threshold = semantic_threshold
        
    def _cosine_distance(self, emb_a, emb_b):
        """Calculates cosine distance between two embedding vectors."""
        dot = np.dot(emb_a, emb_b)
        norm_a = np.linalg.norm(emb_a)
        norm_b = np.linalg.norm(emb_b)
        if norm_a > 0 and norm_b > 0:
            sim = dot / (norm_a * norm_b)
        else:
            sim = 0.0
        return 1.0 - sim

    def chunk_document(self, text: str, filename: str) -> list[str]:
        """Chunks a document using structural breaks, sentence boundaries, and embedding-based similarity."""
        if not text:
            return []
            
        # Step 1: Structural Splitting (Paragraphs and headers)
        # We split by double newlines or structural divider lines
        blocks = re.split(r'\n\s*\n|────────────────────────────────────────', text)
        
        all_sentences = []
        sentence_block_indices = []
        
        # Step 2: Sentence Tokenization within blocks
        for block_idx, block in enumerate(blocks):
            block = block.strip()
            if not block:
                continue
                
            # Regex splits on sentences while keeping punctuation
            sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|!)\s', block)
            for sentence in sentences:
                sentence = sentence.strip()
                if sentence:
                    all_sentences.append(sentence)
                    sentence_block_indices.append(block_idx)
                    
        if not all_sentences:
            return []
            
        # Step 3: Batch Embed All Sentences of this document to make it extremely efficient
        embeddings = self.model.encode(all_sentences, convert_to_numpy=True, show_progress_bar=False)
        
        chunks = []
        current_sentences = []
        current_block = sentence_block_indices[0]
        
        for i, sentence in enumerate(all_sentences):
            # Check for structural breaks (like a markdown header or a new paragraph block shift)
            is_header = sentence.startswith("## ") or sentence.startswith("### ") or sentence.startswith("# ")
            block_shift = sentence_block_indices[i] != current_block
            
            # Estimate character length if we add the incoming sentence
            current_len = sum(len(s) + 1 for s in current_sentences)
            next_len = current_len + len(sentence)
            
            # If the current buffer has content and we hit an absolute structural break (like a header), flush immediately
            if current_sentences and is_header:
                chunks.append(" ".join(current_sentences))
                current_sentences = [sentence]
                current_block = sentence_block_indices[i]
                continue
                
            # If the current buffer is empty, start it
            if not current_sentences:
                current_sentences.append(sentence)
                current_block = sentence_block_indices[i]
                continue
                
            # Calculate running average embedding of sentences in the current buffer
            buffer_indices = list(range(i - len(current_sentences), i))
            buffer_emb = np.mean([embeddings[idx] for idx in buffer_indices], axis=0)
            next_emb = embeddings[i]
            
            # Compute semantic cosine distance
            sem_distance = self._cosine_distance(buffer_emb, next_emb)
            
            # Check sealing conditions
            # 1. Strict Max Limit: if adding sentence exceeds self.max_len
            # 2. Semantic Boundary: if target length met AND semantic distance exceeds threshold
            # 3. Structural Boundary: if target length met AND there is a paragraph block shift
            exceeds_max = next_len > self.max_len
            meets_target = current_len >= self.target_len
            semantic_shift = meets_target and sem_distance > self.semantic_threshold
            paragraph_boundary = meets_target and block_shift
            
            if exceeds_max or semantic_shift or paragraph_boundary:
                # Flush the chunk
                chunks.append(" ".join(current_sentences))
                
                # Start new chunk with an overlap of 1 sentence (if not a structural header break)
                if not is_header and len(current_sentences) > 1:
                    current_sentences = [current_sentences[-1], sentence]
                else:
                    current_sentences = [sentence]
            else:
                current_sentences.append(sentence)
                
            current_block = sentence_block_indices[i]
            
        # Flush remaining sentences
        if current_sentences:
            final_chunk = " ".join(current_sentences)
            if len(final_chunk) >= self.min_len or not chunks:
                chunks.append(final_chunk)
            else:
                # Append tiny orphan chunk to the last chunk
                chunks[-1] = chunks[-1] + " " + final_chunk
                
        return chunks

# ================================================================================
# Ingestion Runner
# ================================================================================

def run_ingestion():
    parser = argparse.ArgumentParser(description="Andrew Ng Digital Twin - Ingest Data to local Chroma DB")
    parser.add_argument("--reset", action="store_true", help="Reset vector store before ingesting")
    args = parser.parse_args()
    
    print("\n" + "=" * 80)
    print("🚀 STARTING PHASE 2: LOCAL RAG INGESTION & VECTOR STORAGE")
    print("=" * 80)
    
    # 1. Initialize sentence transformer model
    print(f"🧬 Loading local embedding model '{MODEL_NAME}'...")
    if SentenceTransformer is None:
        raise RuntimeError("Please install sentence-transformers using `pip install sentence-transformers` first.")
    
    model = SentenceTransformer(MODEL_NAME)
    print("✅ Model loaded successfully!")
    
    # 2. Initialize Chroma persistent database
    print(f"📂 Instantiating local database client at {DB_PATH.absolute()}...")
    chroma_client = chromadb.PersistentClient(path=str(DB_PATH))
    
    # Check if reset requested
    if args.reset:
        print("🗑️ Resetting collection as requested...")
        try:
            chroma_client.delete_collection(COLLECTION_NAME)
            print("Collection deleted successfully!")
        except Exception:
            print("Collection did not exist yet, skipping deletion.")
            
    # Setup embedding function wrapper for Chroma
    embedding_function = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)
    
    collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_function,
        metadata={"hnsw:space": "cosine"}  # Use cosine similarity
    )
    
    # Initialize chunker
    chunker = HybridChunker(
        model=model,
        target_len=1000,
        max_len=1500,
        min_len=200,
        semantic_threshold=0.40
    )
    
    # 3. Gather cleaned files
    print("\n🔍 Scanning data/cleaned directory for files...")
    all_files = []
    for root, _, files in os.walk(CLEANED_DIR):
        for f in files:
            if f.endswith(".txt"):
                all_files.append(Path(root) / f)
                
    total_files = len(all_files)
    print(f"📊 Found {total_files} cleaned files to process.")
    
    if total_files == 0:
        print("❌ Error: No cleaned text files found in data/cleaned/. Please run data collection first.")
        return
        
    # Stats tracking variables
    stats = {
        "pdfs": {"docs": 0, "chunks": 0},
        "transcripts": {"docs": 0, "chunks": 0},
        "the_batch": {"docs": 0, "chunks": 0},
        "blog_posts": {"docs": 0, "chunks": 0},
        "total_chunks": 0,
        "canonical_chunks": 0
    }
    
    # 4. Ingestion Process & CLI Progress Bar
    print("\n📦 Loading and chunking files into Chroma DB...")
    
    # Setup progress bar
    progress_bar = tqdm(
        all_files, 
        desc="Ingesting", 
        unit="file",
        dynamic_ncols=True,
        bar_format="{desc}: {percentage:3.0f}% |{bar:25}| [{n_fmt}/{total_fmt}] Ingesting: {postfix} | Elapsed: {elapsed} | Remaining: {remaining}"
    )
    
    for file_path in progress_bar:
        # Get category based on folder
        doc_type = file_path.parent.name
        if doc_type not in stats:
            # Fallback if structural hierarchy varies
            doc_type = "blog_posts"
            
        stats[doc_type]["docs"] += 1
        basename = file_path.name
        
        # Display current file on progress bar
        progress_bar.set_postfix_str(basename)
        
        # Read file
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Parse metadata and clean body
        doc_metadata, body_text = parse_metadata_headers(content)
        
        # Generate semantic chunks
        try:
            chunks = chunker.chunk_document(body_text, basename)
        except Exception as e:
            # Fallback if semantic split fails (e.g. out of memory on huge math file)
            print(f"\n⚠️ Warning: Chunker error in {basename} ({e}). Falling back to simple structural chunking.")
            chunks = [body_text[i:i+1200] for i in range(0, len(body_text), 1000)]
            
        if not chunks:
            continue
            
        # Prepare metadata, ids, and content lists for Chroma batch add
        documents = []
        metadatas = []
        ids = []
        
        for idx, chunk in enumerate(chunks):
            chunk_clean = chunk.strip()
            if not chunk_clean:
                continue
                
            # Classify domains
            domain = doc_metadata.get("domain")
            if not domain:
                domain = determine_domain(chunk_clean, basename, doc_type)
                
            is_canonical = is_canonical_example(chunk_clean)
            
            # Enrich metadata schema
            chunk_metadata = {
                "source": basename,
                "doc_type": doc_type,
                "title": doc_metadata.get("title", basename.replace(".txt", "").replace("_", " ").title()),
                "domain": domain,
                "canonical_example": is_canonical,
                "date": doc_metadata.get("date", "unknown"),
                "url": doc_metadata.get("url", "unknown"),
                "source_authority": infer_source_authority(doc_type, doc_metadata, basename),
                "is_ng_authored": bool(doc_metadata.get("is_ng_authored", True)),
                "has_editorial": bool(doc_metadata.get("has_editorial", False)),
                "transcript_type": doc_metadata.get("transcript_type", "unknown"),
            }
            
            documents.append(chunk_clean)
            metadatas.append(chunk_metadata)
            ids.append(f"{basename}_chunk_{idx}")
            
            # Increment statistics
            stats[doc_type]["chunks"] += 1
            stats["total_chunks"] += 1
            if is_canonical:
                stats["canonical_chunks"] += 1
                
        # Bulk add current file's chunks to Chroma DB
        if documents:
            collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            
    progress_bar.close()
    
    # ================================================================================
    # Ingestion Report Summary
    # ================================================================================
    
    print("\n" + "=" * 80)
    print("🏆 LOCAL INGESTION PIPELINE SUMMARY REPORT")
    print("=" * 80)
    
    # Beautiful CLI statistics box
    print(f"📂 Database Path:            {DB_PATH.absolute()}")
    print(f"🧬 Model Used:               {MODEL_NAME} (384 dimensions, Cosine space)")
    print(f"📊 Total Chunks Ingested:    {stats['total_chunks']:,}")
    print(f"🔥 Signature Analogies Tagged: {stats['canonical_chunks']:,} ({stats['canonical_chunks']/max(1, stats['total_chunks'])*100:.1f}% of corpus)")
    print("-" * 80)
    
    print(f"📁 PDF Documents:            {stats['pdfs']['docs']:,} docs | {stats['pdfs']['chunks']:,} chunks")
    print(f"📁 Video Transcripts:        {stats['transcripts']['docs']:,} docs | {stats['transcripts']['chunks']:,} chunks")
    print(f"📁 The Batch Issues:         {stats['the_batch']['docs']:,} docs | {stats['the_batch']['chunks']:,} chunks")
    print(f"📁 Blog Posts:               {stats['blog_posts']['docs']:,} docs | {stats['blog_posts']['chunks']:,} chunks")
    print("=" * 80)
    print("\n🎉 Phase 2 Ingestion Completed! The Digital Twin local brain is ready.")
    print("👉 Verify using: python scripts/query_rag.py\n")

if __name__ == "__main__":
    run_ingestion()
