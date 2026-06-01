import sys
import argparse
from pathlib import Path
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

# ================================================================================
# Constants & Configuration
# ================================================================================

DB_PATH = Path("data/chroma_db")
COLLECTION_NAME = "andrew_ng_digital_twin"
MODEL_NAME = "all-MiniLM-L6-v2"

# ANSI color codes for premium CLI styling
class colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

# ================================================================================
# CLI Query Runner
# ================================================================================

def run_query():
    parser = argparse.ArgumentParser(description="Andrew Ng Digital Twin - Query RAG Vector Store")
    parser.add_argument("query", type=str, nargs="?", help="The search query string")
    parser.add_argument("--n_results", type=int, default=5, help="Number of retrieved chunks (default: 5)")
    parser.add_argument("--domain", type=str, default=None, help="Filter by domain (ml_theory, deep_learning, career_advice, ai_strategy, agentic_ai)")
    parser.add_argument("--doc_type", type=str, default=None, help="Filter by document type (pdfs, transcripts, the_batch, blog_posts)")
    parser.add_argument("--canonical", action="store_true", help="Retrieve only canonical analogies")
    args = parser.parse_args()
    
    # Check if database exists
    if not DB_PATH.exists():
        print(f"{colors.RED}❌ Error: Chroma DB not found at {DB_PATH.absolute()}{colors.END}")
        print("Please run data ingestion first: python scripts/ingest_data.py")
        sys.exit(1)
        
    # Initialize Chroma client
    chroma_client = chromadb.PersistentClient(path=str(DB_PATH))
    embedding_function = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)
    
    try:
        collection = chroma_client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=embedding_function
        )
    except Exception as e:
        print(f"{colors.RED}❌ Error loading collection '{COLLECTION_NAME}': {e}{colors.END}")
        print("Please make sure you have ingested data successfully.")
        sys.exit(1)
        
    # Interactive mode if query is not provided as CLI argument
    if not args.query:
        print("\n" + "=" * 80)
        print(f"{colors.BOLD}{colors.CYAN}🎓 ANDREW NG DIGITAL TWIN - RAG RETRIEVAL DIAGNOSTIC TOOL{colors.END}")
        print("=" * 80)
        print(f"🧬 Model: {colors.BOLD}{MODEL_NAME}{colors.END} | DB: {colors.BOLD}{DB_PATH.name}/{COLLECTION_NAME}{colors.END}")
        print("Type your query below. Press Ctrl+C or type 'exit' to quit.\n")
        
        while True:
            try:
                query_text = input(f"{colors.BOLD}Enter query > {colors.END}").strip()
                if not query_text:
                    continue
                if query_text.lower() in ["exit", "quit", "q"]:
                    print("Goodbye!")
                    break
                perform_search(collection, query_text, args.n_results, args.domain, args.doc_type, args.canonical)
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
    else:
        perform_search(collection, args.query, args.n_results, args.domain, args.doc_type, args.canonical)

def perform_search(collection, query_text: str, n_results: int, domain_filter=None, doc_type_filter=None, canonical_filter=False):
    """Encodes the query, performs local vector retrieval, and displays results in a beautiful boxed CLI format."""
    print(f"\n🔍 Searching for: {colors.BOLD}'{query_text}'{colors.END}...")
    
    # Build metadata filter if specified
    where_filter = {}
    filters = []
    
    if domain_filter:
        filters.append({"domain": domain_filter})
    if doc_type_filter:
        filters.append({"doc_type": doc_type_filter})
    if canonical_filter:
        filters.append({"canonical_example": True})
        
    if len(filters) == 1:
        where_filter = filters[0]
    elif len(filters) > 1:
        where_filter = {"$and": filters}
    else:
        where_filter = None
        
    # Query collection
    try:
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where_filter
        )
    except Exception as e:
        print(f"{colors.RED}❌ Search error: {e}{colors.END}")
        return
        
    # Check if we got results
    if not results or not results["documents"] or len(results["documents"][0]) == 0:
        print(f"{colors.YELLOW}⚠️ No matching context found.{colors.END}\n")
        return
        
    # Display results
    docs = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]
    ids = results["ids"][0]
    
    print(f"📊 Retrieved {len(docs)} matching segments:")
    print("-" * 80)
    
    for idx, (doc, meta, dist, chunk_id) in enumerate(zip(docs, metadatas, distances, ids)):
        # Chroma returns cosine distance; let's convert to Cosine Similarity for intuitive reading
        # Similarity = 1.0 - Distance
        similarity = 1.0 - dist
        
        # Color rating based on similarity
        if similarity >= 0.7:
            sim_color = colors.GREEN
        elif similarity >= 0.5:
            sim_color = colors.YELLOW
        else:
            sim_color = colors.BLUE
            
        is_canonical = meta.get("canonical_example", False)
        canonical_badge = f" {colors.BOLD}{colors.RED}[🔥 CANONICAL ANALOGY]{colors.END}" if is_canonical else ""
        
        print(f"\n{colors.BOLD}MATCH #{idx + 1}{colors.END} (ID: {chunk_id})")
        print(f"├── Similarity: {sim_color}{similarity:.4f} (Cosine Similarity){colors.END}{canonical_badge}")
        print(f"├── Source:     {colors.CYAN}{meta.get('source')}{colors.END} ({colors.BOLD}{meta.get('doc_type')}{colors.END})")
        print(f"├── Title:      {colors.BOLD}{meta.get('title')}{colors.END}")
        print(f"├── Domain:     {colors.YELLOW}{meta.get('domain')}{colors.END} | Date: {meta.get('date', 'unknown')}")
        if meta.get("url") != "unknown":
            print(f"├── URL:        {colors.UNDERLINE}{meta.get('url')}{colors.END}")
            
        # Draw beautiful box containing chunk content
        print(f"┌" + "─" * 78 + "┐")
        for line in doc.splitlines():
            line = line.strip()
            if not line:
                continue
            # Wrap long lines in console nicely to maintain box integrity
            while len(line) > 74:
                split_idx = line[:74].rfind(" ")
                if split_idx == -1 or split_idx < 40:
                    split_idx = 74
                print(f"│  {line[:split_idx]:<74}  │")
                line = line[split_idx:].strip()
            print(f"│  {line:<74}  │")
        print(f"└" + "─" * 78 + "┘")
        
    print("\n" + "=" * 80 + "\n")

if __name__ == "__main__":
    run_query()
