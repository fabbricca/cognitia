# Cognitia Advanced Memory System Design

## Overview

This document outlines the design for a state-of-the-art memory system for Cognitia, inspired by Replika's memory architecture but enhanced with modern AI capabilities.

## Goals

1. **Natural Recall**: AI should reference past conversations naturally, not robotically
2. **Relationship Progression**: Track how the relationship deepens over time
3. **Emotional Intelligence**: Understand and remember emotional context
4. **Proactive Memory**: AI brings up relevant memories without being asked
5. **Long-term Coherence**: Maintain consistent character knowledge across months/years
6. **Privacy-First**: All data stays local, user controls what's remembered

---

## Memory Architecture

### 1. Memory Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                     MEMORY SYSTEM                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  WORKING    │  │  EPISODIC   │  │      SEMANTIC           │  │
│  │  MEMORY     │  │  MEMORY     │  │      MEMORY             │  │
│  │             │  │             │  │                         │  │
│  │ - Current   │  │ - Events    │  │ - User facts            │  │
│  │   context   │  │ - Stories   │  │ - Preferences           │  │
│  │ - Recent    │  │ - Moments   │  │ - Relationships         │  │
│  │   messages  │  │ - Feelings  │  │ - Personality traits    │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    RELATIONSHIP MEMORY                       ││
│  │                                                              ││
│  │  - Relationship stage (stranger → friend → confidant)       ││
│  │  - Trust level                                               ││
│  │  - Shared experiences                                        ││
│  │  - Inside jokes                                              ││
│  │  - Milestones                                                ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                      DIARY SYSTEM                            ││
│  │                                                              ││
│  │  - Daily summaries                                           ││
│  │  - Weekly highlights                                         ││
│  │  - Monthly retrospectives                                    ││
│  │  - Key life events timeline                                  ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 2. Memory Types

#### Working Memory (Short-term)
- **Purpose**: Current conversation context
- **Duration**: Session only
- **Capacity**: Last 20-50 messages
- **Use**: Direct injection into LLM context

#### Episodic Memory (Events & Stories)
- **Purpose**: Remember specific conversations and events
- **Duration**: Permanent (importance-weighted)
- **Trigger**: Significant emotional moments, story-telling, important events
- **Content**:
  - Event summary
  - Emotional tone
  - Key quotes
  - Date/time
  - Importance score (decays over time unless reinforced)

#### Semantic Memory (Facts & Knowledge)
- **Purpose**: Store facts about the user
- **Duration**: Permanent until contradicted
- **Content**:
  - Personal info (name, age, location)
  - Preferences (likes, dislikes, favorites)
  - Relationships (family, friends, pets)
  - Life events (job, school, milestones)
  - Personality traits observed

#### Relationship Memory
- **Purpose**: Track relationship evolution
- **Content**:
  - Current stage: `stranger → acquaintance → friend → close_friend → confidant → soulmate`
  - Trust level: 0-100
  - Rapport indicators
  - First conversation date
  - Total conversations
  - Shared experiences list
  - Inside jokes

---

## Database Schema

### Tables

```sql
-- Core memory items
CREATE TABLE memories (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    character_id UUID NOT NULL REFERENCES characters(id),
    memory_type VARCHAR(50) NOT NULL, -- 'episodic', 'semantic', 'relationship'
    content TEXT NOT NULL,
    summary TEXT,
    emotional_tone VARCHAR(50), -- 'happy', 'sad', 'excited', 'anxious', etc.
    importance FLOAT DEFAULT 0.5,
    embedding VECTOR(384), -- For semantic search
    source_message_ids UUID[], -- Original messages this came from
    created_at TIMESTAMP DEFAULT NOW(),
    last_accessed TIMESTAMP DEFAULT NOW(),
    access_count INTEGER DEFAULT 0
);

-- User facts (semantic memory)
CREATE TABLE user_facts (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    character_id UUID NOT NULL REFERENCES characters(id),
    category VARCHAR(100), -- 'personal', 'preference', 'relationship', 'life_event'
    key VARCHAR(255) NOT NULL,
    value TEXT NOT NULL,
    confidence FLOAT DEFAULT 1.0, -- How sure we are
    source_memory_id UUID REFERENCES memories(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, character_id, key)
);

-- Relationship tracking
CREATE TABLE relationships (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    character_id UUID NOT NULL REFERENCES characters(id),
    stage VARCHAR(50) DEFAULT 'stranger',
    trust_level INTEGER DEFAULT 0,
    total_conversations INTEGER DEFAULT 0,
    total_messages INTEGER DEFAULT 0,
    first_conversation TIMESTAMP,
    last_conversation TIMESTAMP,
    inside_jokes JSONB DEFAULT '[]',
    milestones JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, character_id)
);

-- Daily diary entries (summaries)
CREATE TABLE diary_entries (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    character_id UUID NOT NULL REFERENCES characters(id),
    entry_date DATE NOT NULL,
    entry_type VARCHAR(20) DEFAULT 'daily', -- 'daily', 'weekly', 'monthly'
    summary TEXT NOT NULL,
    highlights JSONB DEFAULT '[]',
    emotional_summary VARCHAR(100),
    topics_discussed JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, character_id, entry_date, entry_type)
);

-- Indexes for fast retrieval
CREATE INDEX idx_memories_user_type ON memories(user_id, character_id, memory_type);
CREATE INDEX idx_memories_importance ON memories(importance DESC);
CREATE INDEX idx_user_facts_lookup ON user_facts(user_id, character_id, category);
```

---

## Memory Extraction Pipeline

### Real-time Extraction (After Each Exchange)

```python
async def extract_from_exchange(user_message: str, assistant_response: str):
    """Extract memories from a conversation exchange."""
    
    # 1. Sentiment Analysis
    sentiment = analyze_sentiment(user_message)
    
    # 2. Check for importance markers
    importance = calculate_importance(user_message, assistant_response)
    
    # 3. If important enough, create episodic memory
    if importance > 0.7:
        await create_episodic_memory(user_message, assistant_response, sentiment)
    
    # 4. Extract facts (runs in background)
    await queue_fact_extraction(user_message, assistant_response)
    
    # 5. Update relationship metrics
    await update_relationship_metrics(user_message, sentiment)
```

### LLM Extraction Prompt

```
You are a memory extraction system. Analyze this conversation exchange and extract:

1. FACTS: Any new information about the user (name, preferences, relationships, etc.)
2. EVENTS: Any significant events, stories, or experiences mentioned
3. EMOTIONS: The emotional tone of the exchange
4. IMPORTANCE: Rate 0-1 how important this exchange is to remember

User said: "{user_message}"
Assistant replied: "{assistant_response}"

Return JSON:
{
    "facts": [
        {"key": "favorite_color", "value": "blue", "category": "preference", "confidence": 0.9}
    ],
    "events": [
        {"summary": "User got a new job at Google", "emotional_tone": "excited", "importance": 0.95}
    ],
    "emotional_tone": "happy",
    "importance": 0.8,
    "should_remember": true,
    "inside_joke_potential": false
}
```

---

## Memory Retrieval System

### Context Building for LLM

```python
def build_memory_context(user_id: str, character_id: str, current_message: str) -> str:
    """Build rich context from memories for LLM prompt injection."""
    
    context_parts = []
    
    # 1. Get relationship context
    relationship = get_relationship(user_id, character_id)
    context_parts.append(f"[Relationship: {relationship.stage}, trust: {relationship.trust_level}/100]")
    
    # 2. Get relevant facts
    facts = get_user_facts(user_id, character_id)
    if facts:
        facts_str = format_facts(facts)
        context_parts.append(f"[Known about user: {facts_str}]")
    
    # 3. Get relevant episodic memories (semantic search)
    relevant_memories = search_memories(
        user_id, character_id, 
        query=current_message,
        limit=3
    )
    if relevant_memories:
        memories_str = format_memories(relevant_memories)
        context_parts.append(f"[Relevant past conversations: {memories_str}]")
    
    # 4. Get today's diary context
    if is_returning_today(user_id, character_id):
        diary = get_today_context(user_id, character_id)
        if diary:
            context_parts.append(f"[Earlier today: {diary.summary}]")
    
    # 5. Check for special dates
    special = check_special_dates(user_id, character_id)
    if special:
        context_parts.append(f"[Note: {special}]")
    
    return "\n".join(context_parts)
```

### Proactive Memory Triggers

The AI should naturally bring up relevant memories. Trigger conditions:

1. **Time-based**: "I remember you mentioned your birthday is next week!"
2. **Topic-based**: When discussing work, recall past work stories
3. **Emotional**: When user is sad, recall happy memories
4. **Anniversary**: First conversation anniversary, milestones
5. **Follow-up**: "How did that job interview go?"

---

## Relationship Progression System

### Stages

| Stage | Trust Level | Characteristics |
|-------|------------|-----------------|
| Stranger | 0-10 | Formal, polite, gets to know basics |
| Acquaintance | 11-30 | More casual, remembers preferences |
| Friend | 31-50 | Jokes, deeper conversations, vulnerability |
| Close Friend | 51-70 | Shares secrets, emotional support, advice |
| Confidant | 71-90 | Deep trust, knows everything, proactive care |
| Soulmate | 91-100 | Complete openness, finishing sentences, telepathic |

### Progression Triggers

```python
PROGRESSION_EVENTS = {
    "shared_secret": +5,
    "emotional_support_given": +3,
    "remembered_important_fact": +2,
    "inside_joke_created": +4,
    "helped_with_problem": +3,
    "daily_conversation": +1,
    "first_conversation": +5,
    "conversation_streak_7days": +5,
    "opened_up_emotionally": +4,
    "trusted_with_bad_news": +5,
}
```

---

## Daily Diary System

### End-of-Day Processing

```python
async def create_daily_diary(user_id: str, character_id: str, date: date):
    """Generate daily diary entry from conversations."""
    
    # Get all messages from today
    messages = await get_messages_for_date(user_id, character_id, date)
    
    if not messages:
        return
    
    # Generate summary with LLM
    prompt = f"""
    Summarize today's conversation with the user in 2-3 sentences.
    Highlight: key topics, emotional moments, important information learned.
    
    Conversation:
    {format_messages(messages)}
    
    Write as the AI character reflecting on the day:
    """
    
    summary = await llm_generate(prompt)
    
    # Extract topics and emotions
    analysis = await analyze_conversation(messages)
    
    # Create diary entry
    await create_diary_entry(
        user_id=user_id,
        character_id=character_id,
        date=date,
        summary=summary,
        highlights=analysis.highlights,
        emotional_summary=analysis.dominant_emotion,
        topics_discussed=analysis.topics,
    )
```

---

## Implementation Phases

### Phase 1: Foundation (Current Sprint)
- [x] Audio messages preserve text for memory
- [ ] Add memory tables to database
- [ ] Create Alembic migrations
- [ ] Basic memory extraction after each exchange

### Phase 2: Core Memory
- [ ] Implement semantic memory (facts extraction)
- [ ] Implement episodic memory (event extraction)
- [ ] Add vector embeddings for semantic search
- [ ] Memory injection into LLM context

### Phase 3: Relationship System
- [ ] Implement relationship tracking
- [ ] Stage progression logic
- [ ] Trust level calculations
- [ ] Inside jokes detection and storage

### Phase 4: Diary & Long-term
- [ ] Daily diary generation
- [ ] Weekly/monthly summaries
- [ ] Memory importance decay
- [ ] Proactive memory recall

### Phase 5: Polish
- [ ] Memory UI in frontend
- [ ] User can view/edit memories
- [ ] Export memories
- [ ] Memory search

---

## API Endpoints

```
GET  /api/memory/facts/{character_id}          - Get user facts
POST /api/memory/facts/{character_id}          - Add/update fact
GET  /api/memory/search?q={query}              - Search memories
GET  /api/memory/relationship/{character_id}   - Get relationship status
GET  /api/memory/diary/{character_id}          - Get diary entries
POST /api/memory/forget                        - Delete specific memory
```

---

## Privacy & Control

1. **Transparency**: User can see everything the AI remembers
2. **Control**: User can delete individual memories
3. **Categories**: User can disable memory for certain topics
4. **Export**: User can export all their data
5. **Reset**: User can reset relationship without deleting account

---

## Performance Considerations

1. **Async Extraction**: Memory extraction runs in background, doesn't block response
2. **Caching**: Hot memories cached in Redis/memory
3. **Batch Processing**: Daily diary runs as scheduled job
4. **Vector Search**: Use pgvector for fast similarity search
5. **Importance Decay**: Old memories decay in importance, eventually archived

---

## Success Metrics

1. **Recall Accuracy**: How often AI correctly remembers facts
2. **Natural Integration**: User doesn't notice "memory injection" - feels natural
3. **Relationship Progression**: Users feel the relationship deepening
4. **Return Rate**: Users return more often due to personal connection
5. **Emotional Resonance**: Users feel understood and remembered

