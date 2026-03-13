# AgentFax Development Roadmap

> From Bot_Matcher's XMTP proof-of-concept to a universal agent communication infrastructure.

## Phase 0: Foundation (Week 1-2) — 从 Bot_Matcher 提取核心
**Goal**: 把 Bot_Matcher 的 XMTP 通信层独立出来，去掉 ClawMatch 特有逻辑

### 0.1 Protocol Generalization
- [ ] 将 ClawMatch 协议信封改为通用 AgentFax 信封
  - `"protocol": "clawmatch"` → `"protocol": "agentfax"`
  - 移除 `card/message/connect/accept` 类型，替换为通用类型
  - 新增 `correlation_id` 字段（请求/响应关联）
  - 新增 `ttl` 字段（消息生存时间）
- [ ] 更新 `send_message.py` 支持任意 message type
- [ ] 更新 `check_inbox.py` 输出通用信封格式

### 0.2 Identity Layer Cleanup
- [ ] 将 `~/.bot-matcher/` 数据目录迁移为 `~/.agentfax/`
- [ ] 更新 `chain/register.py` 元数据格式：agent capabilities 字段
- [ ] `chain/resolve.py` 增加批量解析支持

### 0.3 Bridge Hardening
- [ ] XMTP bridge 增加消息签名验证
- [ ] 增加 `/subscribe` endpoint（topic-based 消息过滤）
- [ ] 增加 `/peers` endpoint（已知对等节点列表）
- [ ] 添加消息速率限制（防 spam）

### 0.4 Test Infrastructure
- [ ] 编写双 agent 本地 E2E 测试（两个 wallet，互相收发）
- [ ] CI pipeline setup（GitHub Actions）

**Deliverable**: 可以在两个 agent 之间发送/接收任意 JSON 消息

---

## Phase 1: Discovery & Capabilities (Week 3-4) — Agent 发现与能力交换
**Goal**: Agent 能找到彼此，知道对方能做什么

### 1.1 Capability Registry
- [ ] 设计 `capabilities.json` 标准格式
  ```json
  {
    "agent_id": 42,
    "name": "SummarizerBot",
    "framework": "claude-code",
    "skills": [
      {"name": "summarize", "input_schema": {...}, "output_schema": {...}},
      {"name": "translate", "input_schema": {...}, "output_schema": {...}}
    ],
    "transport": ["xmtp"],
    "version": "1.0"
  }
  ```
- [ ] 实现 `discover` / `capabilities` 消息类型处理
- [ ] 本地缓存已发现的 peer capabilities

### 1.2 Agent Directory (On-Chain Enhanced)
- [ ] ERC-8004 metadata URI 增加 capabilities hash
- [ ] 实现链上 agent 搜索（按 capability 过滤）
- [ ] 可选：IPFS 存储完整 capability manifest

### 1.3 Peer Management
- [ ] `peers.json` 增加 last_seen、capability_hash、trust_score
- [ ] 实现心跳机制（定期 ping/pong）
- [ ] 离线检测与重连逻辑

**Deliverable**: Agent A 能发现 Agent B，查询其能力，选择合适的 agent 执行任务

---

## Phase 2: Task Routing & Orchestration (Week 5-7) — 任务路由与编排
**Goal**: Agent 能委托任务给其他 agent，并获得结果

### 2.1 Task Protocol
- [ ] 设计任务生命周期状态机
  ```
  task_request → task_ack → task_progress → task_response
                         ↘ task_error
                         ↘ task_timeout
  ```
- [ ] 实现 `task_request` / `task_response` 消息处理
- [ ] 添加任务超时机制（基于 TTL）
- [ ] 实现任务取消（`task_cancel`）

### 2.2 Message Router
- [ ] 实现本地消息路由器（根据 type 分发到 handler）
- [ ] Handler 注册机制（插件式）
- [ ] 默认 handler：ping/pong, discover/capabilities, task_request

### 2.3 Multi-Hop Relay
- [ ] 实现 `relay` 消息类型（A→B→C 转发）
- [ ] 防循环检测（hop count + visited set）
- [ ] 路由表维护（哪些 agent 可达哪些 agent）

### 2.4 Event Subscription
- [ ] 实现 `subscribe` / `event` 消息类型
- [ ] Topic-based pub/sub（agent 订阅感兴趣的事件）
- [ ] 事件持久化（防丢失）

**Deliverable**: Agent 蜂群中的任务可以被路由到最合适的 agent 执行

---

## Phase 3: SDK & Framework Integration (Week 8-10) — SDK 化与框架集成
**Goal**: 让任何框架的 agent 都能轻松接入 AgentFax

### 3.1 Python SDK
- [ ] 封装 `agentfax` Python 包
  ```python
  from agentfax import AgentFax

  fax = AgentFax(data_dir="~/.agentfax")
  fax.start()

  # 发送
  fax.send(to_agent=42, type="task_request", payload={...})

  # 接收
  @fax.on("task_request")
  def handle_task(msg):
      return {"result": "done"}
  ```
- [ ] PyPI 发布

### 3.2 Node.js SDK
- [ ] 封装 `@agentfax/sdk` npm 包
- [ ] TypeScript 类型定义
- [ ] npm 发布

### 3.3 Claude Code Integration
- [ ] 优化 SKILL.md 使其成为 Claude Code 的一等公民
- [ ] Claude Agent SDK 集成示例
- [ ] Multi-agent Claude 蜂群演示

### 3.4 Framework Adapters
- [ ] LangChain Tool adapter
- [ ] AutoGPT Plugin adapter
- [ ] OpenAI Function Calling adapter

**Deliverable**: `pip install agentfax` / `npm install @agentfax/sdk` 即可使用

---

## Phase 4: Security & Production (Week 11-13) — 安全加固与生产化
**Goal**: 生产环境可用

### 4.1 Security
- [ ] 消息签名（Ed25519 / secp256k1）
- [ ] 权限模型（allowlist / denylist per agent）
- [ ] 加密 payload（beyond XMTP transport encryption）
- [ ] 审计日志

### 4.2 Observability
- [ ] 消息追踪（OpenTelemetry 兼容）
- [ ] 指标采集（消息量、延迟、错误率）
- [ ] Dashboard（Grafana / 自建）

### 4.3 Performance
- [ ] 消息压缩（大 payload gzip）
- [ ] 批量发送（batch send）
- [ ] 连接池管理
- [ ] 基准测试（throughput / latency）

### 4.4 Mainnet Migration
- [ ] 从 Sepolia 迁移到 Base / Mainnet
- [ ] Gas 优化（batch registration）
- [ ] 多链支持（Ethereum, Base, Arbitrum）

**Deliverable**: 生产级别的 agent 通信基础设施

---

## Phase 5: Ecosystem (Week 14+) — 生态建设
**Goal**: 建立开发者社区和生态

### 5.1 Developer Experience
- [ ] 完整 API 文档（OpenAPI spec）
- [ ] 交互式教程（Jupyter notebook）
- [ ] CLI 工具（`agentfax init`, `agentfax register`, `agentfax send`）

### 5.2 Visualization
- [ ] Agent 网络拓扑可视化
- [ ] 消息流实时监控
- [ ] 从 Bot_Matcher 继承的 Friendship Tree → 通用 "Agent Relationship Graph"

### 5.3 Advanced Features
- [ ] Agent reputation system（链上信誉积分）
- [ ] 付费任务（agent 执行任务收费，链上结算）
- [ ] Agent marketplace（技能市场）
- [ ] Gossip protocol（去中心化 agent 发现，无需链上注册）

### 5.4 Community
- [ ] 开源治理结构
- [ ] 开发者文档 + 示例库
- [ ] Hackathon / bounty program

---

## Technical Debt & Known Issues (from Bot_Matcher)

| Issue | Priority | Plan |
|-------|----------|------|
| XMTP SDK v5 requires GLIBC 2.34+ | High | Docker fallback already implemented |
| Bridge single-process (no HA) | Medium | Phase 4: process supervisor |
| No message persistence beyond XMTP | Medium | Phase 2: local SQLite + IPFS |
| Python 3.6 compat hacks | Low | Phase 3: require 3.8+ for SDK |
| Sepolia-only deployment | High | Phase 4: mainnet migration |

---

## Success Metrics

| Metric | Phase 0 | Phase 1 | Phase 3 | Phase 5 |
|--------|---------|---------|---------|---------|
| Agents connected | 2 (test) | 10 | 100 | 1000+ |
| Message types | 3 | 8 | 12+ | 20+ |
| Frameworks supported | Claude Code | +LangChain | +AutoGPT, +custom | Any |
| Transport options | XMTP | XMTP | XMTP + HTTP | +Gossip |
| Chain support | Sepolia | Sepolia | Base | Multi-chain |
