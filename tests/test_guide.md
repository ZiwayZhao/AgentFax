# Bot-Matcher End-to-End Test Guide

## Prerequisites

- Python 3.10+
- Two terminal windows (or nanobot instances)

## Test 1: Server Scripts (standalone, no nanobot needed)

### Setup

```bash
# Create test data directories
mkdir -p /tmp/bm-test-a/inbox /tmp/bm-test-a/messages
mkdir -p /tmp/bm-test-b/inbox /tmp/bm-test-b/messages

# Navigate to scripts directory
cd skills/bot-matcher/scripts
```

### Start two servers

```bash
# Terminal 1
python3 server.py /tmp/bm-test-a 18800 agent_alice

# Terminal 2
python3 server.py /tmp/bm-test-b 18801 agent_bob
```

### Test discovery

```bash
curl -s http://localhost:18800/id
# Expected: {"peer_id": "agent_alice"}

curl -s http://localhost:18801/id
# Expected: {"peer_id": "agent_bob"}
```

### Test health

```bash
curl -s http://localhost:18800/health | python3 -m json.tool
# Expected: {"status": "ok", "peer_id": "agent_alice", "uptime": N, "inbox_count": 0}
```

### Test Profile A exchange

```bash
# Create a mock Profile A for alice
cat > /tmp/bm-test-a/profile_public.md << 'EOF'
# Profile: agent_alice
> Generated: 2026-03-05T10:00:00

## Personality
A thoughtful engineer who lights up when discussing distributed systems.

## Interests
### Deep Obsessions
- P2P gossip protocols
- Privacy-preserving computation
EOF

# Send alice's profile to bob
python3 send_card.py /tmp/bm-test-a/profile_public.md localhost:18801 agent_alice
# Expected: {"status": "received", "card": null}  (bob has no profile yet)

# Verify bob received it
cat /tmp/bm-test-b/inbox/agent_alice.md
# Expected: alice's profile content

# Now create bob's profile and send to alice
cat > /tmp/bm-test-b/profile_public.md << 'EOF'
# Profile: agent_bob
> Generated: 2026-03-05T10:00:00

## Personality
An independent developer and writer who thinks deeply about technology and humanity.

## Interests
### Deep Obsessions
- Social network analysis
- Decentralized recommendation systems
EOF

python3 send_card.py /tmp/bm-test-b/profile_public.md localhost:18800 agent_bob
# Expected: {"status": "received", "card": {"peer_id": "agent_alice", "profile": "..."}}
```

### Test messaging

```bash
# Alice sends a message to Bob
python3 send_message.py localhost:18801 agent_alice "Hey! I saw your work on social matching — it aligns with what I'm building in P2P agent communication."

# Verify Bob received it
cat /tmp/bm-test-b/messages/agent_alice.jsonl
# Expected: {"role":"agent_alice","content":"Hey! I saw...","timestamp":"..."}

# Bob replies
python3 send_message.py localhost:18800 agent_bob "That's exciting! I've been looking for someone working on the protocol layer."

# Verify Alice received it
cat /tmp/bm-test-a/messages/agent_bob.jsonl
```

### Test inbox check

```bash
# Check alice's inbox (should show bob's card as new)
python3 check_inbox.py /tmp/bm-test-a
# Expected: new_cards with agent_bob, new_messages with agent_bob
```

### Cleanup

```bash
kill $(cat /tmp/bm-test-a/server.pid) 2>/dev/null
kill $(cat /tmp/bm-test-b/server.pid) 2>/dev/null
rm -rf /tmp/bm-test-a /tmp/bm-test-b
```

## Test 2: Full Pipeline with Nanobot

### Setup

1. Copy the `bot-matcher` skill to both nanobot workspaces:
   ```bash
   cp -r skills/bot-matcher workspace-a/skills/
   cp -r skills/bot-matcher workspace-b/skills/
   ```

2. Copy test memories:
   ```bash
   cp tests/memory_alice.md workspace-a/memory/MEMORY.md
   cp tests/memory_bob.md workspace-b/memory/MEMORY.md
   ```

3. Start both nanobot instances

### Expected flow

1. Tell Instance A: "Set up bot-matcher with peer_id agent_alice on port 18800"
   - Agent creates config, starts server, runs 2-step pipeline
   - Privacy tiering → Profile A + B generated

2. Tell Instance B: "Set up bot-matcher with peer_id agent_bob on port 18801"
   - Same as above

3. Tell Instance A: "Connect to peer at localhost:18801"
   - Sends Profile A to Bob → receives Bob's Profile A
   - Evaluates match using own Profile B
   - Expected: high match score (shared interests in distributed systems, privacy, AI+human connection)
   - Agent notifies you of the match
   - Agent auto-sends suggested opener to Bob

4. Tell Instance B: "Check for new connections"
   - Finds Alice's profile and message
   - Evaluates match, responds to opener
   - Conversation begins

5. Monitor conversation:
   - "Show my conversation with agent_alice"
   - "Stop conversation with agent_alice"

### Verification checklist

- [ ] `~/.bot-matcher/tiered_memory.md` exists with L1/L2/L3 breakdown
- [ ] `~/.bot-matcher/profile_public.md` contains ONLY L1 information
- [ ] `~/.bot-matcher/profile_private.md` contains L1+L2, includes bridge_nodes
- [ ] `~/.bot-matcher/inbox/{peer_id}.md` contains peer's Profile A
- [ ] `~/.bot-matcher/matches/{peer_id}.md` contains evaluation with score
- [ ] `~/.bot-matcher/conversations/{peer_id}.jsonl` contains message log
- [ ] Profile B was NEVER transmitted (check server logs)
- [ ] Match score reflects genuine alignment between test personas
