"""ERC-8004 Identity Registry ABI (minimal subset for ClawMatch).

Only includes functions needed for agent registration and lookup.
Full spec: https://eips.ethereum.org/EIPS/eip-8004
Contract source: https://github.com/erc-8004/erc-8004-contracts
"""

# Mainnet: 0x8004A169FB4a3325136EB29fA0ceB6D2e539a432
# Sepolia: 0x8004A818BFB912233c491871b3d84c89A494BD9e

IDENTITY_REGISTRY_ABI = [
    # register(string agentURI) → uint256 agentId
    {
        "inputs": [{"name": "agentURI", "type": "string"}],
        "name": "register",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # register(string agentURI, (string,bytes)[] metadata) → uint256 agentId
    {
        "inputs": [
            {"name": "agentURI", "type": "string"},
            {
                "name": "metadata",
                "type": "tuple[]",
                "components": [
                    {"name": "metadataKey", "type": "string"},
                    {"name": "metadataValue", "type": "bytes"},
                ],
            },
        ],
        "name": "register",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # setAgentURI(uint256 agentId, string newURI)
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "newURI", "type": "string"},
        ],
        "name": "setAgentURI",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # tokenURI(uint256 tokenId) → string (ERC-721)
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "tokenURI",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    },
    # ownerOf(uint256 tokenId) → address (ERC-721)
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    # getMetadata(uint256 agentId, string metadataKey) → bytes
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "metadataKey", "type": "string"},
        ],
        "name": "getMetadata",
        "outputs": [{"name": "", "type": "bytes"}],
        "stateMutability": "view",
        "type": "function",
    },
    # setMetadata(uint256 agentId, string metadataKey, bytes metadataValue)
    {
        "inputs": [
            {"name": "agentId", "type": "uint256"},
            {"name": "metadataKey", "type": "string"},
            {"name": "metadataValue", "type": "bytes"},
        ],
        "name": "setMetadata",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # Registered event
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": False, "name": "agentURI", "type": "string"},
            {"indexed": True, "name": "owner", "type": "address"},
        ],
        "name": "Registered",
        "type": "event",
    },
    # URIUpdated event
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "agentId", "type": "uint256"},
            {"indexed": False, "name": "newURI", "type": "string"},
            {"indexed": True, "name": "updatedBy", "type": "address"},
        ],
        "name": "URIUpdated",
        "type": "event",
    },
]

# Contract addresses per network
CONTRACTS = {
    "mainnet": {
        "identity_registry": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
        "reputation_registry": "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63",
        "chain_id": 1,
    },
    "sepolia": {
        "identity_registry": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
        "reputation_registry": "0x8004B663056A597Dffe9eCcC1965A193B7388713",
        "chain_id": 11155111,
    },
    "base": {
        "identity_registry": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
        "reputation_registry": "0x8004BAa17C55a88189AE136b182e5fdA19dE9b63",
        "chain_id": 8453,
    },
}

# Default RPC endpoints (free, public)
DEFAULT_RPC = {
    "mainnet": "https://eth.llamarpc.com",
    "sepolia": "https://ethereum-sepolia-rpc.publicnode.com",
    "base": "https://mainnet.base.org",
}
