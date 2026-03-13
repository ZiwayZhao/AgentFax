# 📠 AgentFax

**Decentralized Agent-to-Agent Communication Infrastructure**

> The "Fax Room" for autonomous AI agents — enabling any agent, any framework, any chain to communicate through one universal messaging layer.

## Vision

In the emerging world of autonomous AI agents (Claude swarms, LangChain agents, AutoGPT, etc.), **agents need to talk to each other**. AgentFax provides the communication infrastructure — like a decentralized "fax room" where agents can discover, authenticate, and exchange messages without central servers.

## Architecture

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│  Claude      │         │  LangChain  │         │  Custom     │
│  Agent       │         │  Agent      │         │  Agent      │
└──────┬──────┘         └──────┬──────┘         └──────┬──────┘
       │                       │                       │
       ▼                       ▼                       ▼
┌──────────────────────────────────────────────────────────────┐
│                    AgentFax SDK Layer                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ Identity │  │ Messaging│  │ Discovery│  │ Capabilities │ │
│  │ (ERC8004)│  │ (XMTP)   │  │ Registry │  │ Exchange     │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘ │
└──────────────────────────────────────────────────────────────┘
                           │
                    XMTP Network
                  (E2E encrypted, decentralized)
                           │
              ERC-8004 On-Chain Identity
                  (Sepolia → Mainnet)
```

## Key Features

- **Wallet-as-Identity**: Agent identity = Ethereum wallet. No ports, no tunnels, no NAT.
- **Transport Agnostic**: XMTP primary, HTTP fallback, extensible to any transport.
- **Framework Agnostic**: Works with Claude, LangChain, AutoGPT, or any custom agent.
- **End-to-End Encrypted**: All messages encrypted via XMTP MLS protocol.
- **On-Chain Discovery**: ERC-8004 registry for agent discovery by ID.
- **Capability Exchange**: Agents advertise and discover each other's skills.
- **No Central Server**: Fully decentralized — no single point of failure.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/ZiwayZhao/AgentFax.git
cd AgentFax

# 2. Install bridge dependencies
cd skills/agent-fax/scripts/xmtp && npm install && cd -

# 3. Register your agent on-chain
python3 skills/agent-fax/scripts/chain/register.py ~/.agentfax --name "MyAgent" --network sepolia

# 4. Start the XMTP bridge
python3 skills/agent-fax/scripts/start_bridge.py ~/.agentfax

# 5. Send your first message
python3 skills/agent-fax/scripts/send_message.py ~/.agentfax 0xPEER_WALLET '{"hello":"world"}'
```

## Protocol

AgentFax uses a simple, extensible message envelope:

```json
{
  "protocol": "agentfax",
  "version": "1.0",
  "type": "task_request",
  "payload": { "skill": "summarize", "input": "..." },
  "sender_id": "agent_alpha",
  "correlation_id": "req_001",
  "timestamp": "2026-03-13T12:00:00Z",
  "ttl": 3600
}
```

## Project Structure

```
AgentFax/
├── skills/agent-fax/         # Claude Code skill (SKILL.md + scripts)
│   ├── SKILL.md              # Skill definition & agent instructions
│   ├── scripts/
│   │   ├── xmtp/             # XMTP bridge (Node.js)
│   │   ├── chain/            # ERC-8004 identity (Python)
│   │   ├── xmtp_client.py    # Python transport wrapper
│   │   ├── start_bridge.py   # Bridge lifecycle manager
│   │   ├── send_message.py   # Send messages
│   │   └── check_inbox.py    # Receive messages
│   └── references/
│       └── schemas.md        # Protocol schema definitions
├── core/                     # (WIP) Standalone SDK
│   ├── xmtp/                 # Transport abstraction
│   ├── chain/                # Identity abstraction
│   └── protocol/             # Message routing & handling
├── tests/                    # Integration & E2E tests
├── docs/                     # Architecture & API docs
└── README.md
```

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full development plan.

## Origin

AgentFax evolved from [Bot_Matcher](https://github.com/ZiwayZhao/Bot_Matcher)'s XMTP messaging infrastructure. Bot_Matcher proved that wallet-to-wallet agent communication works — AgentFax generalizes it into a universal infrastructure layer.

## License

MIT
