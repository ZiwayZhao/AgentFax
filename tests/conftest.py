"""Shared fixtures for AgentFax tests."""

import os
import sys
import tempfile
import shutil
import pytest

# Add scripts dir to path so we can import modules directly
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "skills", "agent-fax", "scripts"
)
sys.path.insert(0, SCRIPTS_DIR)


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory mimicking ~/.agentfax."""
    data_dir = str(tmp_path / "agentfax")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


@pytest.fixture
def sample_message():
    """A valid AgentFax protocol message."""
    from datetime import datetime, timezone

    return {
        "protocol": "agentfax",
        "version": "1.0",
        "type": "ping",
        "sender_id": "test_peer",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": "corr_001",
        "ttl": 3600,
        "payload": {"message": "hello"},
        "_xmtp_sender_wallet": "0xTEST_WALLET",
        "_xmtp_id": "msg_001",
    }


@pytest.fixture
def sample_task_request():
    """A valid task_request message."""
    from datetime import datetime, timezone

    return {
        "protocol": "agentfax",
        "version": "1.0",
        "type": "task_request",
        "sender_id": "test_peer",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "correlation_id": "corr_task_001",
        "ttl": 3600,
        "payload": {
            "task_id": "task_001",
            "skill": "echo",
            "input": {"text": "hello world"},
        },
        "_xmtp_sender_wallet": "0xTASK_WALLET",
        "_xmtp_id": "msg_task_001",
    }


@pytest.fixture
def make_message():
    """Factory fixture for creating messages with custom fields."""
    from datetime import datetime, timezone

    def _make(msg_type="ping", sender_id="test_peer", payload=None,
              ttl=3600, correlation_id=None, wallet="0xTEST"):
        return {
            "protocol": "agentfax",
            "version": "1.0",
            "type": msg_type,
            "sender_id": sender_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id or f"corr_{msg_type}",
            "ttl": ttl,
            "payload": payload or {},
            "_xmtp_sender_wallet": wallet,
            "_xmtp_id": f"msg_{msg_type}_{sender_id}",
        }
    return _make
