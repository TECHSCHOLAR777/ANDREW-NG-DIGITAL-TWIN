# Andrew Ng Digital Twin — RAG Companion

An interactive, premium-grade Streamlit dialogue application that emulates Andrew Ng's voice, pedagogical style, and ML expertise. Grounded in a 1.71-million-word corpus of CS229 lecture notes, *Machine Learning Yearning*, "The Batch" newsletters, and lecture transcripts, this system demonstrates advanced Retrieval-Augmented Generation (RAG) and persistent memory.

---

## 🚀 Key Features

1. **Authentic Persona Emulation**: Implements Andrew's signature verbal habits, pedagogical moves (e.g., example before definition), T-shaped knowledge framework, and optimistic outlook. Speaks in first-person ("I", "we", "my") with a natural, conversational tone.
2. **Strict Word-Count Constraint**: Enforces a concise **150-word limit** per response (unless details/proofs are explicitly requested) to keep dialogue focused and optimize Gemini API token usage.
3. **Dual-Path Hybrid Retrieval**: Integrates Chroma DB vector search (`all-MiniLM-L6-v2`) with a BM25 lexical keyword index, merging results via Reciprocal Rank Fusion (RRF) and reranking via Cross-Encoder (`ms-marco-MiniLM-L6-v2`) to capture precise terminology and canonical analogies.
4. **Two-Tiered Persistent Memory**:
   - **Student Profile**: Persists student properties (identity, goals, mathematical comfort level, rapport details, focus areas/confusion points) in `user_profile.json`.
   - **Episodic Recall**: Stores key takeaways and summaries from past interactions in `episodic_memory.json` to enable context recall across distinct sessions.
5. **Timeline Awareness & Hedging**: Detects when queries refer to developments after 2026 and prepends an honest, temporal-hedging disclaimer explaining that the agent is reasoning from established frameworks rather than direct corpus grounding.
6. **Optimized for Low Latency**: Caches heavy models and indices during app preloading, runs memory updates asynchronously on background daemon threads, and executes exactly **one synchronous Gemini API call** per turn to avoid rate limit (HTTP 429) errors.
7. **Premium Glassmorphism Dashboard**: Split-column workspace displaying a ChatGPT-style conversation window on the left, and a real-time **Memory Inspector** card system showing what Andrew currently remembers about you on the right.

---

## 📂 Repository Structure

```
├── data/
│   ├── chroma_db/       # Chroma vector store sqlite files
│   ├── cleaned/         # Ingested and cleaned markdown files
│   ├── memory/          # JSON files for user_profile and episodic_memory
│   ├── metadata/        # Ingested documents metadata map
│   ├── raw/             # Raw PDFs and transcripts (source corpus)
│   └── sessions/        # Chat session histories stored as JSON
├── scripts/
│   ├── app.py           # Streamlit application entrypoint & UI
│   ├── clean_text.py    # Preprocessing script for data cleaning
│   ├── ingest_data.py   # RAG ingestion, chunking, and embedding pipeline
│   ├── persona_engine.py# Core RAG, prompt assembly, and memory runtime
│   ├── query_rag.py     # Local retrieval diagnostic tool (CLI)
│   └── collect_*.py     # Scrapers and crawlers for primary sources
├── README.md            # Setup and design documentation
├── architecture.md      # Mermaid diagrams and system architecture breakdown
├── persona_contract.md  # The 10 mandatory rules and anti-patterns
└── requirements.txt     # Project python dependencies
```

---

## 🛠️ Installation & Setup

### 1. Clone the Repository & Install Dependencies
Ensure you have Python 3.10+ installed. Install the required libraries:
```bash
pip install -r requirements.txt
```

### 2. Configure API Keys
Create a `.env` file in the root directory. You can specify a single key or multiple keys to enable automatic round-robin key rotation on rate limits:
```env
# Single Key
GEMINI_API_KEY=your_gemini_api_key_here

# Or Multiple Keys for Rate-Limit Rotation
GEMINI_API_KEY_1=key_one
GEMINI_API_KEY_2=key_two
```

### 3. Populating the Grounding Database (Optional)
The Chroma database is pre-populated (~138MB database size grounding 530+ files). If you wish to re-ingest or add new files, place raw PDFs/transcripts in `data/raw/` and run:
```bash
python scripts/ingest_data.py
```

---

## 🖥️ Running the Application

Launch the Streamlit interactive dashboard:
```bash
streamlit run scripts/app.py
```

On first startup, the app displays a setup screen while it preloads embedding models and builds the BM25 index. Once complete, you are redirected to the chat workspace.

---

## 🧠 Memory Schema Description

### 1. Student Profile (`data/memory/user_profile.json`)
Maintains structured, evolving traits extracted from conversation:
- `student_profile`: Tracks `identity` (e.g., Undergraduate, Product Manager), `industry_domain`, and `mathematical_comfort_level` (High, Medium, Conceptual).
- `career_and_business_goals`: Tracks `short_term` and `long_term` professional ambitions.
- `misconceptions_and_focus_areas`: A list of concepts the student struggled with or needs to review.
- `learning_preferences`: Tracks `explanation_style` (e.g., heavily analogy-driven).
- `personal_rapport`: Stores student `name`, `location`, and a list of `notable_remarks`.
- `topics_discussed_timeline`: Logs keywords of discussed topics over sessions.

### 2. Episodic Memory (`data/memory/episodic_memory.json`)
Maintains unstructured cross-session summaries:
```json
{
  "memory": "The student is deploying an SQLite-backed RAG database.",
  "topic": "RAG Database",
  "memory_type": "project_context",
  "tags": ["rag", "sqlite", "database"],
  "importance": 2,
  "timestamp": "2026-06-02T12:00:00"
}
```

---

## 🎓 Evaluation & Persona Compliance

The twin's outputs can be checked against the **three diagnostic tests** from the strategy guide:
- **The Prop Test**: Explain neural networks. (Pass if it opens with Lego bricks within the first two sentences).
- **The Canonical Example Test**: Explain linear regression. (Pass if it predictions housing prices as the anchor example).
- **The Career Voice Test**: Ask how to get started in ML. (Pass if it acknowledges feelings, provides numbered concrete steps, and urges building over pure reading).
