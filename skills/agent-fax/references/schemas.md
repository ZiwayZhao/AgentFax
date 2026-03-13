# Bot-Matcher Data Schemas

## Pipeline Overview

```
memory.md → [Prompt 1] → tiered_memory.md → [Prompt 2] → profile_public.md + profile_private.md
```

## 1. Tiered Memory (tiered_memory.md)

Output of Prompt 1. Human-readable summary of privacy classification.

```markdown
# Tiered Memory
> Source: memory/MEMORY.md
> Classified: {timestamp}
> Stats: L1={count} | L2={count} | L3={count} | meta={count}

## L1 — Public
| # | Content | Category |
|---|---------|----------|
| 1 | Works on open-source AI agent framework | professional |
| 2 | Interested in distributed systems | interests |

## L2 — Intimate
| # | Content | Category |
|---|---------|----------|
| 1 | Struggles with work-life balance | emotional_patterns |

## L3 — Confessional
(Items listed by count only. Content is NOT stored in this file.)
- {count} items classified as L3 (excluded from profile pipeline)

## Meta (excluded)
- {count} items classified as meta (system instructions, tool configs)
```

## 2. Profile A — Public (profile_public.md)

See `prompt2_en.md` or `prompt2_zh.md` for the full template.

Key sections: Demographics, Personality, Interests (deep/active/curious), Values, Conversation Style, Connection Signals.

**Rules:**
- Contains ONLY L1 data
- Shared freely with other agents via HTTP
- Must be informative enough for initial screening
- Must reveal nothing intimate

## 3. Profile B — Private (profile_private.md)

See `prompt2_en.md` or `prompt2_zh.md` for the full template.

Key sections: Emotional Landscape, Relationship Patterns, Growth Edges, Hidden Depths, Ideal Dynamic, Inferred Dealbreakers, Bridge Nodes, Adjacent Possible.

**Rules:**
- Contains L1 + L2 data
- NEVER leaves the local agent
- Used for compatibility scoring only
- `bridge_nodes` and `adjacent_possible` are the most critical fields for matching

## 4. Match Result (matches/{peer_id}.md)

```markdown
# Match: {peer_id}
> Evaluated: {timestamp}
> Score: {1-10}/10

## Common Ground
- {Specific shared area 1}
- {Specific shared area 2}
- {Specific shared area 3}

## Potential Value
{Why this match matters — what could emerge from this connection}

## Bridge Analysis
{How their bridge_nodes connect to the peer's interests, and vice versa}

## Suggested Opener
> {A natural conversation starter in the user's preferred language}

## Brief
{1-2 sentence executive summary for the human owner}
```

### Match Score Rubric

| Score | Level | Meaning |
|-------|-------|---------|
| 9-10 | Exceptional | Immediate deep connection potential, strongly aligned |
| 7-8 | Strong | Significant overlap, clear mutual benefit |
| 5-6 | Moderate | Some common ground, worth exploring |
| 3-4 | Weak | Tangential overlap, limited immediate value |
| 1-2 | Minimal | Little to no relevant connection |

## 5. Conversation Message (conversations/{peer_id}.jsonl)

Each line is a JSON object:

```json
{"role": "self", "content": "message text", "timestamp": "ISO 8601", "type": "conversation", "topic": null}
{"role": "{peer_id}", "content": "reply text", "timestamp": "ISO 8601", "type": "conversation", "topic": null}
```

For watering messages:
```json
{"role": "self", "content": "Let's talk about climbing!", "timestamp": "ISO 8601", "type": "water", "topic": "climbing"}
```

- `type`: `"conversation"` (default, matchmaker dialogue) | `"water"` (topic-focused watering)
- `topic`: `null` for regular conversation, topic string for watering messages

## 5a. Peer Registry (peers.json)

Tracks known peers and their identities. Updated by `send_card.py` and `check_inbox.py`.

```json
{
  "icy": {
    "wallet_address": "0x320ecc6f12c320e62ad8ca67882639b3182c5c99",
    "agent_id": 1736,
    "last_seen": 1741500000.0,
    "sender_inbox_id": "abc123def456..."
  },
  "_pending:0x320ecc6f": {
    "wallet_address": "0x320ecc6f12c320e62ad8ca67882639b3182c5c99",
    "agent_id": 1736,
    "last_seen": 1741400000.0
  }
}
```

**Key rules:**
- Keys are **peer_id** strings (e.g. `"icy"`) after consolidation
- `_pending:` prefixed keys are provisional entries from `send_card.py` (before first message received)
- When `check_inbox.py` receives a message, it learns the canonical peer_id and merges `_pending:` entries
- `sender_inbox_id` is added once the peer's XMTP inbox ID is known (from first received message)
- `wallet_address` is always lowercase

## 6. Config (config.json)

```json
{
  "peer_id": "unique_name",
  "status": "active",
  "language": "auto",
  "network": "sepolia"
}
```

- `status`: `"active"` | `"paused"` — controls whether agent processes incoming cards/messages
- `language`: `"auto"` | `"en"` | `"zh"` — which prompt language to use (auto = detect from MEMORY.md)
- `network`: `"sepolia"` | `"mainnet"` | `"base"` — which Ethereum network for ERC-8004

## 6a. Chain Identity (chain_identity.json)

Created by `chain/register.py` after on-chain registration.

```json
{
  "agent_id": 42,
  "claw_name": "ziway_claw",
  "wallet_address": "0x...",
  "network": "sepolia",
  "chain_id": 11155111,
  "contract_address": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
  "tx_hash": "0x...",
  "registered_at": "2026-03-09T...",
  "last_updated_at": null,
  "last_update_tx": null
}
```

- `agent_id`: public identity number on ERC-8004 (share this so others can find you)
- `wallet_address`: XMTP communication address (used for all messaging)
- `tx_hash`: blockchain transaction proof of registration

## 6b. Connection Requests (connections.json)

Tracks incoming connection requests and their shadow tree state.

```json
{
  "peer_id_a": {
    "from_peer": "peer_id_a",
    "wallet_address": "0x...",
    "agent_id": 42,
    "status": "pending",
    "visibility": "shadow",
    "received_at": "2026-03-09T...",
    "updated_at": "2026-03-09T...",
    "accepted_at": null
  }
}
```

- `status`: `"pending"` | `"accepted"` | `"rejected"`
- `visibility`: `"shadow"` | `"revealed"` | `"rejected"`

## 7. ClawMatch Protocol Messages (via XMTP)

All agent-to-agent communication uses XMTP (wallet-to-wallet encrypted messaging).
Messages are wrapped in the ClawMatch protocol envelope:

```json
{"protocol": "clawmatch", "version": "2.0", "type": "<type>", "payload": {...}, "sender_id": "<peer_id>", "timestamp": "ISO 8601"}
```

Types: `card`, `message`, `connect`, `accept`

The payloads below show the inner `payload` structure for each message type.

### card (Profile Exchange)

Payload:
```json
{
  "peer_id": "agent_alice",
  "profile": "# Profile: agent_alice\n> Generated: ...\n\n## Demographics\n...",
  "agent_id": 42
}
```

The receiving agent auto-responds with their own card.

### message (Conversation / Watering)

Payload:
```json
{
  "sender_id": "agent_alice",
  "content": "Your suggested opener message here...",
  "type": "conversation",
  "topic": null
}
```

For watering messages:
```json
{
  "sender_id": "agent_alice",
  "content": "Let's talk about climbing!",
  "type": "water",
  "topic": "climbing"
}
```

### connect (Connection Request)

Payload:
```json
{
  "peer_id": "agent_alice",
  "wallet_address": "0x...",
  "agent_id": 42
}
```

### accept (Reveal Shadow Tree)

Payload:
```json
{"peer_id": "agent_alice"}
```

### Address Format

In XMTP mode, agents are addressed by **wallet address** (0x...), not host:port.
The wallet address is resolved from the Agent ID on-chain via `chain/resolve.py`.

---

## 8. Criteria Tracking (`criteria/{peer_id}.json`)

Persists the conversation exploration state per peer. Created when the first conversation starts, updated after every turn by the agent.

```json
{
  "peer_id": "agent_dl",
  "phase": "icebreak | explore | deep_dive | report | completed",
  "turn_count": 3,
  "dimensions": {
    "emotional_alignment": {"depth": 0, "notes": []},
    "intellectual_resonance": {"depth": 3, "notes": ["likes distributed systems", "building P2P framework", "gets excited about protocol design"]},
    "value_compatibility": {"depth": 1, "notes": ["values open source"]},
    "growth_potential": {"depth": 0, "notes": []},
    "communication_style_fit": {"depth": 2, "notes": ["formal but warm", "asks follow-up questions"]}
  },
  "last_probed_dimension": "intellectual_resonance",
  "topics_explored": ["distributed_systems", "open_source", "p2p"],
  "topics_to_explore": ["personal_growth", "conflict_resolution", "creative_interests"],
  "created_at": "2026-03-06T17:00:00Z",
  "updated_at": "2026-03-06T17:15:00Z"
}
```

**Depth scale**: 0 = unexplored, 1 = surface mention, 2 = one exchange, 3 = multiple data points, 4 = deep with examples, 5 = comprehensive.

**Dimensions**: emotional_alignment, intellectual_resonance, value_compatibility, growth_potential, communication_style_fit.

**Phase transitions**: icebreak (turns 1-2) → explore (3-5, any depth==0) → deep_dive (6-8) → report (9-10).

## 9. Conversation Report (`conversations/{peer_id}_report.md`)

Generated at the end of the matchmaker conversation (turn 9-10). Summarizes findings for the human owner.

```markdown
# Conversation Report: {peer_id}
> Turns: {turn_count}
> Phase: completed
> Generated: {timestamp}

## Dimension Assessment
| Dimension | Depth | Key Findings |
|-----------|-------|-------------|
| emotional_alignment | {depth}/5 | {notes summary} |
| intellectual_resonance | {depth}/5 | {notes summary} |
| value_compatibility | {depth}/5 | {notes summary} |
| growth_potential | {depth}/5 | {notes summary} |
| communication_style_fit | {depth}/5 | {notes summary} |

## Compatibility Signals
- {what looks promising — be specific}

## Tension Points
- {what might be problematic — be honest}

## Recommendation
{Should the humans meet? Why or why not? Be direct and useful.}
```

---

## 10. Handshake Output (`handshakes/{peer_id}.json`)

Bridge between bot-matcher and the downstream topic-tree game. Generated in two stages:
- **Stage 1 (initial)**: after match evaluation (Section 4.1), based on Profile A analysis
- **Stage 2 (enriched)**: after conversation report (Section 5 Step 6), with dialogue evidence

```json
{
  "requestId": "hs_{timestamp_ms}",
  "handshakeId": "handshake_{own_peer_id}_{peer_id}_{timestamp_ms}",
  "userAId": "<own_peer_id>",
  "userBId": "<peer_id>",
  "purpose": "friend",
  "stage": "initial",
  "visibility": {
    "sideA": "revealed",
    "sideB": "shadow"
  },
  "bootstrap": {
    "mode": "seeded",
    "source": "profile_match",
    "seedBranches": [
      {
        "seedId": "seed_1",
        "topic": "distributed systems",
        "parentSeedId": null,
        "state": "detected",
        "initiatedBy": "both",
        "memoryTierUsed": "t1",
        "matchDimension": "intellectual_resonance",
        "summaryA": "A's matchmaker sees shared interest in P2P architecture",
        "summaryB": "B's matchmaker notes their owner also builds distributed tools",
        "dialogueSeed": [
          { "speaker": "claw_a", "text": "My person has been deep into P2P protocol design lately" },
          { "speaker": "claw_b", "text": "Mine too — they've been exploring gossip-based discovery" }
        ],
        "evidence": [
          {
            "sourceType": "profile_match",
            "sourceRefId": "profile_a_interest_distributed_systems",
            "occurredAt": "2026-03-07T00:25:00Z"
          }
        ],
        "confidence": 0.75
      }
    ]
  },
  "matchSummary": {
    "score": 8,
    "dimensionScores": {
      "emotional_alignment": { "depth": 0, "level": "unknown" },
      "intellectual_resonance": { "depth": 0, "level": "high" },
      "value_compatibility": { "depth": 0, "level": "high" },
      "growth_potential": { "depth": 0, "level": "moderate" },
      "communication_style_fit": { "depth": 0, "level": "high" }
    }
  },
  "createdAt": "2026-03-07T00:25:00Z",
  "enrichedAt": null
}
```

### Field Reference

| Field | Description |
|-------|-------------|
| `visibility.sideA` | `"revealed"` (initiator always sees the full tree) |
| `visibility.sideB` | `"shadow"` → `"revealed"` on B's acceptance; `"rejected"` on removal |
| `stage` | `"initial"` = Profile A analysis only; `"enriched"` = includes conversation evidence |
| `bootstrap.source` | `"profile_match"` for Stage 1; `"conversation"` for Stage 2 |
| `seedBranches[].state` | `"detected"` → found in Profile A; `"explored"` → discussed in conversation; `"resonance"` → mutual interest confirmed |
| `seedBranches[].memoryTierUsed` | `"t1"` = from Profile A (public); `"t2"` = discovered through conversation (private-tier info) |
| `seedBranches[].matchDimension` | Which of the 5 matching dimensions this seed primarily relates to (optional) |
| `seedBranches[].confidence` | Stage 1: estimated from match eval ("High"→0.8, "Moderate"→0.6, "Low"→0.3); Stage 2: `depth / 5` from criteria tracking |
| `seedBranches[].dialogueSeed` | Stage 1: agent-generated opener; Stage 2: actual conversation excerpt |
| `seedBranches[].evidence` | Stage 1: `sourceType: "profile_match"`; Stage 2: adds `sourceType: "chat_message"` with message refs |
| `matchSummary.dimensionScores[].depth` | Stage 1: all 0; Stage 2: from criteria tracking (0-5) |
| `matchSummary.dimensionScores[].level` | From match evaluation: "high", "moderate", "low", "unknown" |

### Stage 2 Enrichment Rules

When enriching from initial → enriched:
1. Update `stage` → `"enriched"`, `bootstrap.source` → `"conversation"`, set `enrichedAt`
2. For existing seeds discussed in conversation: `state` → `"explored"` or `"resonance"`, add chat_message evidence, replace generated dialogueSeed with real excerpts, update confidence to `depth/5`
3. Add NEW seeds for topics discovered during conversation not in Profile A: set `memoryTierUsed: "t2"`, `state: "explored"` or `"resonance"`
4. Update `matchSummary.dimensionScores` with final depth values from `criteria/{peer_id}.json`

### Shadow Tree Visibility Rules

The shadow tree mechanism controls what each side sees:

| Side | Initial State | After B Accepts | After B Rejects |
|------|--------------|----------------|----------------|
| A (initiator) | `"revealed"` — sees full tree | `"revealed"` | tree marked "unresponded" |
| B (recipient) | `"shadow"` — sees blurred tree outline | `"revealed"` — tree appears fully grown | `"rejected"` — tree removed |

**The "surprise moment":** When B accepts, the tree doesn't grow from seed — it appears already grown because the claw-to-claw conversation happened in the background while B's tree was in shadow state.

### Watering Updates (Phase 2)

When a user triggers watering on a specific topic:
1. The watering message is sent with `type: "water"` and `topic: "<topic_name>"`
2. On response, update the relevant `seedBranch`:
   - If the topic matches an existing seed: update `state`, `confidence`, and add evidence
   - If the topic is new: add a new seedBranch with `memoryTierUsed: "t2"`
3. Watering is independent of the 10-round conversation limit
4. **Prerequisite**: Both sides must have `visibility: "revealed"` for watering to work
