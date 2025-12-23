# Memory Add-on Architecture for Human-Like AI Companions

This document describes a **modular, local-first memory architecture** designed as an **add-on** to an existing AI assistant system.  
The goal is to provide *human-like, persistent, structured memory* while remaining fully open-source, Dockerized, and easy to integrate.

---

## 1. Final Goal

Create a memory system that enables an AI companion to:

- Maintain **distinct Person objects** for every individual mentioned by the user
- Distinguish between **trivial, emotional, and permanent facts**
- Recall **relationships, preferences, and past events** naturally
- Scale to long conversations without blowing up context windows
- Run fully **locally** with open-source tools

This system does **not** replace your assistant — it *augments it*.

---

## 2. High-Level Architecture

```
User / UI
   │
   ▼
Existing Assistant (LLM Orchestrator)
   │
   ▼
Memory Add-on (FastAPI, Docker)
   │
   ├── Graphiti / Neo4j (Structured Knowledge Graph)
   ├── Qdrant (Vector Episodic Memory)
   ├── Persona Store (Distilled Persona Profiles)
   └── (Optional) KV Cache Store (KVZip + vLLM)
```

---

## 3. Core Components & Responsibilities

### 3.1 Memory Add-on Service (FastAPI)

**Role:** Central orchestrator

Responsibilities:
- Ingest conversations
- Extract entities, relationships, emotions, salience
- Write memory to databases
- Retrieve relevant memory for inference
- Distill persona profiles
- Expose REST API

Key endpoints:
- `POST /ingest`
- `POST /retrieve`
- `POST /distill`
- `GET /person/{id}`
- `POST /admin/prune`

---

### 3.2 Graphiti (Temporal Knowledge Graph)

**Role:** Canonical structured memory

Stores:
- Person nodes (user, friends, family, etc.)
- Relationship edges (likes, dislikes, argued_with, related_to)
- Episode nodes (conversation events)
- Temporal validity (when facts were true)

Used for:
- Relationship reasoning
- Long-term factual recall
- Conflict resolution (old vs new facts)

Backend:
- Neo4j (community edition, Docker)

---

### 3.3 Qdrant (Vector Memory)

**Role:** Episodic / fuzzy recall

Stores:
- Embedded summaries of conversation episodes
- Emotional or narrative memories

Used for:
- Semantic recall
- “That thing you mentioned before” queries
- Memory ranking with salience & recency

---

### 3.4 Persona Memory (PersonaMem-style)

**Role:** Compact, human-like user model

Stores:
- Distilled preferences
- Important life events
- Communication style
- Emotional sensitivities

Form:
- JSON summaries (300–1000 tokens)
- Optional LoRA adapters (advanced)

Updated periodically, not per message.

---

### 3.5 KV Cache Compression (Optional)

**Role:** Runtime optimization

Technology:
- KVZip / KVPress
- vLLM runtime

Purpose:
- Compress transformer KV cache
- Allow very long effective memory on limited VRAM
- Speed up session re-entry

Optional but powerful.

---

## 4. Memory Lifecycle

### 4.1 Ingestion Pipeline

1. Receive conversation turn
2. Named Entity Recognition (NER)
3. LLM extraction:
   - Triplets (subject, relation, object)
   - Emotion vector
   - Salience score (0–1)
   - Permanence label
4. Write to Graphiti
5. Embed & store in Qdrant
6. Update persona buffer if needed

---

### 4.2 Retrieval Pipeline

1. Detect mentioned persons
2. Query Graphiti for related facts
3. Query Qdrant for semantic memories
4. Rank by:
   - Semantic relevance
   - Salience
   - Recency decay
5. Inject persona summary (if relevant)
6. Assemble context block

---

### 4.3 Persona Distillation

Triggered:
- Every N sessions
- Or after M high-salience memories

Process:
- Feed memory buffer to LLM
- Output concise persona JSON
- Replace previous persona version

---

## 5. Scoring & Policies

### Salience
```
salience = 0.6 * LLM_score + 0.3 * emotion_magnitude + 0.1 * manual_flag
```

### Permanence Rules
- Deaths, births, chronic events → permanent
- Preferences → persistent but updatable
- Small talk → decays

### Recency Decay
```
weight = exp(-(now - timestamp) / T)
```

---

## 6. Docker Composition

Services:
- memory-addon (FastAPI)
- qdrant
- neo4j
- redis (background jobs)
- vllm (optional)

All services run locally via `docker-compose`.

---

## 7. Integration Contract

Your assistant only needs to:

1. Call `/retrieve` before generating a reply
2. Call `/ingest` after each turn

No internal logic changes required.

---

## 8. Success Criteria

- ≥85% correct memory recall in evaluation set
- Emotional facts always prioritized
- <200ms retrieval latency
- Runs on 12GB VRAM
- Fully local, open-source

---

## 9. Why This Works

This architecture mirrors **human cognition**:
- Graph memory = semantic knowledge
- Vector memory = episodic recall
- Persona memory = personality & identity
- KV compression = working memory

LLMs do not “think like humans” — but **they can be scaffolded to behave like they remember like humans**.

---

## 10. Next Steps

- Implement FastAPI memory service
- Integrate Graphiti & Qdrant
- Add persona distillation
- Benchmark vs PersonaMem dataset
- Experiment with KVZip

---

## 11. License & Philosophy

This system is:
- Open-source
- Local-first
- Privacy-preserving
- Extensible

You are building *not just memory* — but **continuity, trust, and identity**.
