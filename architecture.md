# Technical Architecture: Andrew Ng Digital Twin

I built this project to act as a digital twin of Andrew Ng, teaching machine learning concepts using CS229 notes and DeepLearning.ai materials. Instead of building a generic RAG chatbot, I wanted a system that actually tracks a dynamic memory graph of the student as we chat, identifying their focus areas, struggles, and progress.

---

## 1. System Design and Choices

When designing this, I focused on five main requirements:
*   **Persona consistency:** The prompts force the LLM to use Andrew's actual teaching style (using examples before definitions, concrete physical analogies, and practical, encouraging language).
*   **Fact grounding:** Every response is grounded in lecture notes and transcripts, not the general knowledge of the model.
*   **Dynamic memory:** Instead of using static text files or dumping raw chat history into the context, the system maps out relationships (like concepts the student understands or struggles with) in a database graph.
*   **Hybrid search:** I combined vector search and traditional keyword search inside a single database function using Reciprocal Rank Fusion (RRF).
*   **No startup lag:** The first query was originally timing out because the embedding model loaded lazily. I fixed this by preloading the model into memory during the FastAPI server startup.

---

## 2. Core Components and Flow

Here is how a message travels from the browser, through the search and generation pipelines, and updates the memory graph in the background:

```mermaid
flowchart TD
    %% Main Flow
    UserQuery[User Query] -->|Sends Tenant ID & Gemini Key| API[FastAPI Backend]
    
    subgraph Processing [Runtime Pipeline]
        API --> Embed[Generate Embedding\nLocal all-mpnet-base-v2]
        
        %% Retrieval paths
        Embed -->|Vector + Keyword Search| DBChunks[(Postgres: knowledge_chunks)]
        DBChunks -->|Reciprocal Rank Fusion| Ground[Grounding Context]
        
        %% Graph Memory paths
        Embed -->|Vector Search Nodes| Anchor[Identify Anchor Nodes]
        Anchor -->|2-Hop BFS Traversal| Traversal[Recursive CTE Traversal]
        Traversal -->|Sub-graph Nodes & Edges| GraphMem[Memory Context]
        
        Ground --> Compiler[Prompt Compiler]
        GraphMem --> Compiler
        
        Compiler --> Gemini[Call Gemini API]
        Gemini --> Response[Send Response to Frontend]
    end

    %% Background tasks
    Response -->|Start Async Task| Worker[Background Worker]
    Worker -->|Extract Triplets| GeminiExtract[Gemini Extraction]
    GeminiExtract -->|Resolve Aliases| DBGraph[(Postgres: entity_nodes & relation_edges)]
```

---

## 3. Database Schema

I chose PostgreSQL with the pgvector extension as my only data store. I wanted to avoid the complexity of running separate database engines for vector search and structured relational tables.

```mermaid
erDiagram
    tenants ||--o{ entity_nodes : "owns"
    tenants ||--o{ entity_aliases : "owns"
    tenants ||--o{ relation_edges : "owns"
    tenants ||--o{ knowledge_chunks : "owns"
    tenants ||--o{ conversation_turns : "owns"

    entity_nodes ||--o{ entity_aliases : "maps to"
    entity_nodes ||--o{ relation_edges : "subject"
    entity_nodes ||--o{ relation_edges : "object"
```

### Table Breakdown
*   **tenants:** The root of the session. The frontend generates a new UUID for the tenant on every page load to prevent different sessions from seeing stale memory. If you click "Reset learning memory", it deletes the tenant, and Postgres automatically wipes out all related data via cascade deletions.
*   **entity_nodes:** Stores concepts, people, projects, and papers. Includes a 768-dimensional embedding of the concept name to allow vector matching.
*   **entity_aliases:** Used for entity resolution. Maps short forms or alternate spellings (like "NNs" or "backprop") to their canonical concepts.
*   **relation_edges:** Links concepts together (like "Student struggles_with Gradient Descent") along with numeric weights.
*   **knowledge_chunks:** Holds the raw text of lecture notes, newsletters, and transcripts, combined with vector embeddings and full-text search documents.
*   **conversation_turns:** Logs the dialogue history.

---

## 4. Dual-Path Retrieval and Reciprocal Rank Fusion (RRF)

Instead of using standard vector search alone, which can easily miss exact technical keywords like "sigmoid" or "LSTMs", I built a hybrid search inside a database function called `hybrid_chunk_retrieval`. 

It runs two parallel searches:
1.  **Vector Search:** Finds chunks using cosine distance on the embeddings.
2.  **Keyword Search:** Uses native PostgreSQL full-text search with a fallback query structure.

Since vector scores and keyword matches use different scales, I merge their rankings using Reciprocal Rank Fusion:

$$RRF(d) = \frac{0.65}{60 + Rank_{vec}(d)} + \frac{0.35}{60 + Rank_{fts}(d)}$$

I multiply the resulting score by an *authority prior* based on the source document type. Stanford lecture notes get a 1.0 multiplier, papers get 0.8, QA documents get 0.6, and newsletters get 0.5. This ensures official teaching materials are ranked higher than quick newsletter summaries.

```mermaid
flowchart LR
    Query[User Query] --> Embed[Get Embedding]
    Query --> Text[Raw Text Query]
    
    Embed -->|pgvector Cosine Sim| Path1[(Vector Rank)]
    Text -->|TSVector Match| Path2[(FTS Rank)]
    
    Path1 --> RRF[RRF Fusion Engine]
    Path2 --> RRF
    
    RRF --> Prior[Apply Source Authority Prior\nLecture > Paper > Newsletter]
    Prior --> TopK[Return Grounding Chunks]
```

---

## 5. Knowledge Graph Memory Traversal

When the user asks a question, the backend retrieves a relevant sub-graph of their learning history using a Postgres function called `vector_anchored_subgraph`:

1.  **Find Anchors:** The system runs a vector search on `entity_nodes` to find the concepts closest to the user's query.
2.  **BFS Traversal:** Using a recursive Common Table Expression (CTE), it performs a 2-hop traversal along the `relation_edges` starting from those anchor nodes.
3.  **Path Weight Decay:** The weight of relationships decays by 0.85 with each hop, and a visited-array prevents loops.
4.  **Prompt Format:** The retrieved nodes and edges are written into the prompt context so Gemini knows what the student has mastered, struggled with, or discussed recently.

```mermaid
flowchart TD
    QE[Query Embedding] -->|Vector Similarity| Anchor1[Anchor Node A]
    QE -->|Vector Similarity| Anchor2[Anchor Node B]
    
    subgraph Hop0 [Hop 0: Anchor Nodes]
        Anchor1
        Anchor2
    end
    
    subgraph Hop1 [Hop 1: Neighbors]
        Anchor1 -->|struggles_with| NodeC[Concept C\nWeight: 0.85]
        Anchor2 -->|mastered| NodeD[Concept D\nWeight: 0.85]
    end
    
    subgraph Hop2 [Hop 2: Extended Context]
        NodeC -->|requires| NodeE[Concept E\nWeight: 0.72]
    end
    
    Hop2 --> BuildPrompt[Format Sub-graph as Text Context]
```

---

## 6. Background Extraction and Entity Resolution

To keep responses fast, the memory graph updates asynchronously. Once the backend sends the AI's reply to the browser, it spawns a background worker to extract new triplets and update the database:

1.  **Extract Triplets:** The background task sends the conversation turn to Gemini, extracting triplets like `(student, struggles_with, learning rate)`.
2.  **Fuzzy Alias Check:** Before inserting a new concept, it calls the database function `resolve_entity`. This function normalizes the term and checks for:
    *   Exact alias matches.
    *   Trigram fuzzy alias matches (with a similarity threshold above 0.6).
    *   Direct case-insensitive matches with canonical concept names.
3.  **Upsert:** If a match is found, it updates the existing node and links the relationship to it. If not, it creates a new concept node and registers the new aliases.

```mermaid
flowchart TD
    Task[Background Task] -->|Get Concept Text| Resolve[resolve_entity]
    Resolve --> Check1{Exact Alias?}
    Check1 -->|Yes| Match[Link to Existing Node]
    Check1 -->|No| Check2{Trigram Fuzzy Similarity > 0.6?}
    Check2 -->|Yes| Match
    Check2 -->|No| Check3{Direct Canonical Match?}
    Check3 -->|Yes| Match
    Check3 -->|No| NewNode[Create New Canonical Node]
```
