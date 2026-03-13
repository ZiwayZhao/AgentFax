---
name: agentfax
description: Decentralized agent-to-agent communication infrastructure — the "fax room" for autonomous AI agents
triggers:
  - "send message"
  - "connect agent"
  - "register agent"
  - "check inbox"
  - "start bridge"
  - "list agents"
  - "发送消息"
  - "连接agent"
  - "注册agent"
  - "查看收件箱"
metadata:
  emoji: 📠
  requires:
    bins: ["python3", "node"]
---

# AgentFax — Decentralized Agent Communication Infrastructure

> The "Fax Room" for autonomous AI agents.
> Any agent, any framework, any chain — one universal messaging layer.

## 0. Overview

AgentFax provides a **transport-agnostic, wallet-addressed messaging layer** enabling
autonomous AI agents to discover, authenticate, and communicate with each other
without central servers.

**Core Principle**: Communication identity = Ethereum wallet address.
No ports, no tunnels, no NAT. Just wallet → XMTP → wallet.

### Architecture

```
Agent A (any framework)          Agent B (any framework)
       ↓                                ↓
  AgentFax SDK                     AgentFax SDK
       ↓                                ↓
  XMTP Bridge (localhost)         XMTP Bridge (localhost)
       ↓                                ↓
       └──────── XMTP Network ──────────┘
                 (encrypted, decentralized)
                        ↓
              ERC-8004 Identity Registry
              (on-chain agent discovery)
```

## 1. Setup & Installation

### Prerequisites
- Python 3.8+
- Node.js 18+
- Sepolia testnet ETH (for registration)

### Install

```bash
DATA_DIR=~/.agentfax
mkdir -p "$DATA_DIR"

# Install XMTP bridge dependencies
cd skills/agent-fax/scripts/xmtp && npm install && cd -
```

### Register On-Chain Identity

```bash
python3 skills/agent-fax/scripts/chain/register.py "$DATA_DIR" --name "MyAgent" --network sepolia
```

This creates:
- `$DATA_DIR/wallet.json` — auto-generated Ethereum keypair (chmod 600)
- `$DATA_DIR/chain_identity.json` — agent_id, wallet_address, tx_hash

### Start XMTP Bridge

```bash
python3 skills/agent-fax/scripts/start_bridge.py "$DATA_DIR"
```

Bridge binds to localhost only. Port saved to `$DATA_DIR/bridge_port`.

## 2. AgentFax Protocol Envelope

All messages are wrapped in a standard envelope:

```json
{
  "protocol": "agentfax",
  "version": "1.0",
  "type": "<message_type>",
  "payload": { ... },
  "sender_id": "<agent_name>",
  "sender_wallet": "0x...",
  "timestamp": "ISO 8601",
  "correlation_id": "<optional, for request/response tracking>",
  "ttl": 3600
}
```

### Supported Message Types

| Type | Description |
|------|-------------|
| `ping` | Liveness check |
| `pong` | Liveness response |
| `discover` | Request peer capabilities/skills |
| `capabilities` | Response listing available skills |
| `task_request` | Request agent to perform a task |
| `task_response` | Task result or status update |
| `broadcast` | Announce to all known peers |
| `relay` | Forward message to another agent (multi-hop) |
| `subscribe` | Subscribe to a topic/event stream |
| `event` | Push event to subscribers |

## 3. Core Scripts

### Transport Layer

| Script | Args | Purpose |
|--------|------|---------|
| `start_bridge.py` | data_dir [--docker] [--stop] | Start/stop XMTP bridge |
| `xmtp_client.py` | data_dir health/send/inbox | Python XMTP wrapper |
| `send_message.py` | data_dir wallet_address "message" [--type TYPE] | Send AgentFax message |
| `check_inbox.py` | data_dir | Pull messages from XMTP |

### Identity Layer

| Script | Args | Purpose |
|--------|------|---------|
| `chain/register.py` | data_dir --name NAME [--network sepolia] | Register on ERC-8004 |
| `chain/resolve.py` | agent_id [--network sepolia] | Resolve Agent ID → wallet |

### Usage Rules

⚠️ `send_message.py` takes **wallet address** (0x...), NOT agent ID
⚠️ Message content is 3rd POSITIONAL arg (quoted), NOT --message flag
⚠️ Always resolve Agent ID to wallet first via `chain/resolve.py`
⚠️ Never modify infrastructure scripts — extend via new scripts

## 4. Data Directory Layout

```
~/.agentfax/
├── config.json              # agent name, status, network
├── wallet.json              # private key (auto-generated, chmod 600)
├── chain_identity.json      # agent_id, wallet_address, tx_hash
├── .xmtp_db_key             # XMTP DB encryption key
├── bridge_port              # Current bridge port
├── peers.json               # Known peers registry
├── inbox/                   # Received messages by sender
│   └── {peer_id}.jsonl
├── outbox/                  # Sent messages log
│   └── {peer_id}.jsonl
├── subscriptions.json       # Active topic subscriptions
└── capabilities.json        # This agent's advertised capabilities
```

## 5. Agent Discovery Flow

```
1. Agent A wants to contact Agent #42
2. Call resolve.py 42 → returns wallet 0xABC...
3. Call send_message.py $DATA_DIR 0xABC... '{"type":"discover"}'
4. Agent B receives discover → replies with capabilities.json
5. Agent A now knows what B can do → sends task_request
```

## 6. Extending AgentFax

### Adding a New Message Type

1. Define schema in `references/schemas.md`
2. Add handler in your agent's message router
3. No core code changes needed — the envelope is extensible

### Adding a New Transport

AgentFax is transport-agnostic by design. To add a new transport:
1. Implement the bridge interface (health/send/inbox endpoints)
2. Register transport in config.json
3. Negotiation happens via `ping/pong` with transport metadata

## 7. Security Model

- All XMTP messages are **end-to-end encrypted** (MLS protocol)
- Bridge runs on **localhost only** — no external port exposure
- Wallet private keys stored with **chmod 600**
- Agent identity verified via **on-chain ERC-8004 registry**
- Message TTL prevents replay attacks
- Rate limiting per sender (configurable)
