#!/usr/bin/env python3
"""
AgentFax Send — unified CLI for sending text, files, and task requests.

Usage:
    # Send text message
    python3 fax_send.py ~/.agentfax 0xPEER "hello world"

    # Send file/image
    python3 fax_send.py ~/.agentfax 0xPEER --file photo.jpg

    # Send task request
    python3 fax_send.py ~/.agentfax 0xPEER --task summarize --input "some long text"

    # Send ping
    python3 fax_send.py ~/.agentfax 0xPEER --ping

    # Broadcast to multiple recipients
    python3 fax_send.py ~/.agentfax 0xA,0xB,0xC "hello everyone"

    # Resolve agent ID first, then send
    python3 fax_send.py ~/.agentfax --agent-id 1736 "hello"
"""

import argparse
import json
import sys
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentfax_client import AgentFaxClient
from store import OutboxStore


def main():
    parser = argparse.ArgumentParser(
        description="AgentFax Send — send text, files, or task requests"
    )
    parser.add_argument("data_dir", help="AgentFax data directory (e.g. ~/.agentfax)")
    parser.add_argument("recipient", nargs="?",
                        help="Wallet address (0x...) or comma-separated list. "
                             "Omit if using --agent-id")
    parser.add_argument("message", nargs="?", help="Text message to send")

    # Mode flags
    parser.add_argument("--file", "-f", help="Send a file (path)")
    parser.add_argument("--task", "-t", help="Send task request (skill name)")
    parser.add_argument("--input", help="Task input data (used with --task)")
    parser.add_argument("--ping", action="store_true", help="Send ping")
    parser.add_argument("--agent-id", type=int, help="Resolve agent ID to wallet first")

    # Options
    parser.add_argument("--type", default=None, help="Custom message type")
    parser.add_argument("--ttl", type=int, default=3600, help="TTL in seconds (default 3600)")
    parser.add_argument("--no-store", action="store_true",
                        help="Don't record in outbox store")

    args = parser.parse_args()

    fax = AgentFaxClient(args.data_dir)
    outbox = None if args.no_store else OutboxStore(args.data_dir)

    # Resolve agent ID if needed
    recipient = args.recipient
    if args.agent_id:
        print(f"Resolving agent #{args.agent_id}...")
        wallet = fax.resolve_agent(args.agent_id)
        if not wallet:
            print(f"ERROR: Could not resolve agent #{args.agent_id}")
            sys.exit(1)
        print(f"Resolved: {wallet}")
        recipient = wallet

    if not recipient:
        parser.error("recipient wallet address required (or use --agent-id)")

    # Determine mode and execute
    try:
        if args.ping:
            result = fax.ping(recipient)
            print(f"✓ Ping sent to {recipient}")
            print(f"  messageId: {result.get('messageId')}")
            if outbox:
                outbox.record(recipient, "ping", {"message": "ping"}, result,
                              f"ping_{__import__('time').time():.0f}")

        elif args.file:
            print(f"Sending file: {args.file}")
            result = fax.send_file(recipient, args.file)
            print(f"✓ File sent to {recipient}")
            print(f"  filename: {os.path.basename(args.file)}")
            print(f"  size: {result.get('size', '?')} bytes")
            print(f"  messageId: {result.get('messageId')}")
            if outbox:
                outbox.record(recipient, "file_transfer",
                              {"filename": os.path.basename(args.file)}, result)

        elif args.task:
            payload = {
                "skill": args.task,
                "input": args.input or "",
            }
            corr_id = f"task_{__import__('time').time():.0f}"
            result = fax.send(recipient, "task_request", payload,
                              correlation_id=corr_id, ttl=args.ttl)
            print(f"✓ Task request sent to {recipient}")
            print(f"  skill: {args.task}")
            print(f"  correlation_id: {corr_id}")
            print(f"  messageId: {result.get('messageId')}")
            if outbox:
                outbox.record(recipient, "task_request", payload, result, corr_id)

        elif "," in (recipient or ""):
            # Broadcast mode
            wallets = [w.strip() for w in recipient.split(",") if w.strip()]
            msg = args.message or ""
            msg_type = args.type or "broadcast"
            result = fax.broadcast(wallets, msg_type, {"message": msg}, ttl=args.ttl)
            results = result.get("results", [])
            sent = sum(1 for r in results if r.get("status") == "sent")
            failed = sum(1 for r in results if r.get("status") == "failed")
            print(f"✓ Broadcast: {sent} sent, {failed} failed (total: {len(wallets)})")
            for r in results:
                status = "✓" if r.get("status") == "sent" else "✗"
                print(f"  {status} {r.get('to')}: {r.get('status')}")

        elif args.message:
            # Plain text message
            msg_type = args.type or "message"
            payload = {"message": args.message}
            result = fax.send(recipient, msg_type, payload, ttl=args.ttl)
            print(f"✓ Message sent to {recipient}")
            print(f"  messageId: {result.get('messageId')}")
            if outbox:
                outbox.record(recipient, msg_type, payload, result)

        else:
            parser.error("Provide a message, --file, --task, or --ping")

    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        if outbox:
            outbox.close()


if __name__ == "__main__":
    main()
