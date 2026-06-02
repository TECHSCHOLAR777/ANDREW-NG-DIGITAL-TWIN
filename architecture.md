# Andrew Ng Digital Twin — Architecture Documentation

This document explains the technical architecture of the Andrew Ng Digital Twin, details the design decisions that distinguish it from standard RAG chatbots, and outlines the information flow through the system.

---

## 1. Core Architectural Goals

The twin is designed around the five grading pillars of the assignment:
- **Persona Consistency**: Rigidly adhering to Andrew Ng's teaching mechanics (e.g., example before definition, physical analogies, structured enumeration).
- **Technical Accuracy**: Grounding responses in a verified corpus (CS229 notes, *Machine Learning Yearning*, etc.) rather than parametric knowledge.
- **Memory Quality**: Storing both short-term conversational context and long-term user context across sessions.
- **RAG Quality**: Implementing a hybrid, reranked search system that favors Andrew's canonical ML examples.
- **User Experience (UX)**: Minimizing query latency and providing a premium, informative dashboard.

---

## 2. Component Diagram

The following diagram illustrates the flow of information during both **Ingestion** (offline) and **Runtime** (online):

```mermaid
flowchart TD
    %% Ingestion Pipeline
    subgraph Ingestion Pipeline (Offline)
        A[Raw Corpus: CS229 · MLY · Transcripts · The Batch] --> B[Text Cleaning & Formatting]
        B --> C[Concept-Unit Chunker]
        C --> D[Metadata Enrichment\nDomain · Date · Canonical Flag]
        D --> E[SentenceTransformer Embeddings]
        E --> F[(Chroma DB Collection)]
        D --> G[(BM25 Keyword Index)]
    end

    %% Runtime Pipeline
    subgraph Runtime Pipeline (Online)
        H[User Query] --> I[Dual-Path Retrieval]
        F -->|Vector Query| I
        G -->|Keyword Query| I
        I --> J[Reciprocal Rank Fusion\nFuses Vector + BM25 ids]
        J --> K[Cross-Encoder Reranking\nms-marco-MiniLM]
        K --> L[Source Quality Boost\nWeight PDF > Transcript > Blog]
        L --> M{Canonical Flag Check?}
        M -->|Yes| N[Example-Anchor Signal\nForce Lego/Housing prices analogy]
        M -->|No| O[Standard Context]

        %% Memory Retrieval
        P[(episodic_memory.json)] -->|Vector & Keyword Recall| Q[Long-Term Recall]
        R[(user_profile.json)] -->|Active Profile Fetch| S[Student Profile]
        
        %% Prompt Compiler
        N --> T[System Prompt Assembly]
        O --> T
        Q --> T
        S --> T
        U[Session History\nLast 8 turns] --> T

        %% Generation & Guardrails
        T --> V[Gemini 2.5 Flash Call\n1 Turn = 1 Sync API call]
        V --> W[Local Post-Processing\nTemporal Hedging]
        W --> X[Final Dialogue Output]

        %% Background Memory System
        X --> Y[Async Memory Agent\nNon-blocking Daemon Thread]
        H --> Y
        Y --> Z[Gemini Profiler Extract]
        Z -->|Update Deltas| R
        Z -->|Append Entry| P
    end
```

---

## 3. Grounding Corpus Ingestion

The ingestion pipeline transforms raw pedagogical assets into structured search indices:
1. **Raw Source Pack**: Standardized texts including CS229 Lecture Notes (Stanford 2022), *Machine Learning Yearning* (deeplearning.ai 2018), "The Batch" newsletters, and Coursera/Stanford AI lecture transcripts.
2. **Text Cleaning**: Cleans LaTeX mathematical syntax, strips page headers, normalizes unicode, and removes filler expressions.
3. **Concept-Unit Chunking**: Traditional sliding-window chunking breaks technical examples mid-sentence. Instead, the ingestor chunks at **conceptual boundaries** (e.g., CS229 section headers, *Machine Learning Yearning* chapters).
4. **Metadata Enrichment**:
   - `domain`: Categorized into `ml_theory`, `deep_learning`, `ai_strategy`, `career_advice`, or `agentic_ai`.
   - `canonical_example`: Set to `True` if the chunk references one of Andrew's signature teaching props (e.g., Lego bricks, housing prices, spam filtering, darts on a target, Mars overpopulation).

---

## 4. Hybrid Retrieval & Reranking

At runtime, the retrieval stage merges structural and semantic search strategies to optimize accuracy:
1. **Dual-Path Retrieval**: 
   - **Semantic Path**: Queries the local Chroma DB vector store using a SentenceTransformer model (`all-MiniLM-L6-v2`).
   - **Lexical Path**: Queries a local BM25 keyword index over the raw documents. This is vital because signature terms like "sigmoid" or "theta" can be underweighted by dense vectors.
2. **Reciprocal Rank Fusion (RRF)**: Merges the ranked list of document IDs from both search paths, producing a unified candidate set.
3. **Cross-Encoder Reranking**: Evaluates the top candidates using a cross-encoder model (`ms-marco-MiniLM-L6-v2`) to rank them by semantic relevance to the query.
4. **Source Quality Boosting**: Adjusts ranking scores by weighting official textbooks and lecture notes over transcripts and newsletters.
5. **Canonical Analogies Flag**: If a selected chunk contains a signature analogy, an explicit flag is appended to the system prompt directing the LLM to incorporate it.

---

## 5. Two-Tiered Memory System

The digital twin models a real educator who understands and tracks their student's progress over time:

### Tier 1: Stored Student Profile (`user_profile.json`)
Keeps track of high-level student properties:
- **Identity & Domain**: Professional role (e.g., student, PM, executive) and industry field.
- **Math Comfort**: Categorized into *High (Rigorous)*, *Medium*, or *Conceptual (Low Math)* based on the level of technical detail in prior queries.
- **Strategic Goals**: User ambitions divided into short-term objectives and long-term goals.
- **Rapport Details**: Student name, location, and notable remarks.
- **Focus Areas**: Confusion points or topics to revisit, identified during conversations.

### Tier 2: Episodic Memory Store (`episodic_memory.json`)
Maintains a log of past interactions:
- Each entry documents a specific topic, summary of what the student learned, and an importance weight.
- When the student asks questions that require context from prior chats (e.g., "what did we discuss last time?", "who am I?"), these memories are fetched and formatted into the system prompt.

---

## 6. Prompt Assembly & Guardrails

The system prompt is compiled dynamically on every user turn:
- **System Instructions**: Andrew Ng's persona contract, speech mechanics rules, and constraints (first-person voice, strict 150-word response limit, pedagogy-first, practical optimism).
- **Grounding Context**: Reranked search chunks formatted with citation blocks.
- **Session Memory**: A sliding window of the last 8 message turns.
- **Student Profile**: Extracted details from `user_profile.json`.
- **Episodic Memory**: Relevant bullet points recalled from `episodic_memory.json`.

---

## 7. Latency and Token Optimization

To prevent rate limits (HTTP 429) and keep latency under 1 second, the engine is highly optimized:
1. **Resource Preloading**: Embeddings, BM25 indices, and Cross-Encoder models are loaded into memory during the setup screen on startup.
2. **Cached Singletons**: The embedding function is initialized once and reused.
3. **API-Call Minimization**: Bypasses secondary query-expansion and style-checking LLM calls. Each conversational turn performs exactly **one synchronous LLM call** for generation.
4. **Asynchronous Memory Updates**: Profile extraction and episodic storage run on a background daemon thread, allowing the app to return the response immediately without waiting for memory processing.
