#!/usr/bin/env python3
"""
AgentFax Inbox — view and manage received messages.

Usage:
    # Show all new messages
    python3 fax_inbox.py ~/.agentfax

    # Show messages filtered by type
    python3 fax_inbox.py ~/.agentfax --type ping

    # Show messages from specific sender
    python3 fax_inbox.py ~/.agentfax --from icy

    # Pull fresh messages from bridge and store them
    python3 fax_inbox.py ~/.agentfax --pull

    # Show outbox (sent messages)
    python3 fax_inbox.py ~/.agentfax --outbox

    # Show message counts
    python3 fax_inbox.py ~/.agentfax --stats
"""

import argparse
import json
import sys
import os

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agentfax_client import AgentFaxClient
from store import InboxStore, OutboxStore


def format_message(msg: dict, verbose: bool = False) -> str:
    """Format a message for display."""
    lines = []
    msg_type = msg.get("msg_type") or msg.get("type", "?")
    sender = msg.get("sender_id", "?")
    received = msg.get("received_at", "?")
    status = msg.get("status", "?")
    corr = msg.get("correlation_id", "-")

    lines.append(f"  [{msg_type}] from={sender}  status={status}  corr={corr}")
    lines.append(f"    received: {received}")

    payload = msg.get("payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            pass

    if isinstance(payload, dict):
        # Show key payload fields
        if payload.get("message"):
            lines.append(f"    message: {payload['message']}")
        if payload.get("skill"):
            lines.append(f"    skill: {payload['skill']}")
        if payload.get("filename"):
            lines.append(f"    file: {payload['filename']}")
        if payload.get("content_type") and payload["content_type"] != "text":
            lines.append(f"    content_type: {payload['content_type']}")
        if verbose:
            lines.append(f"    payload: {json.dumps(payload, ensure_ascii=False)}")
    else:
        lines.append(f"    content: {payload}")

    return "\n".join(lines)


def format_outbox_message(msg: dict) -> str:
    """Format an outbox message for display."""
    lines = []
    msg_type = msg.get("msg_type", "?")
    recipient = msg.get("recipient_wallet", "?")
    sent_at = msg.get("sent_at", "?")
    status = msg.get("status", "?")
    corr = msg.get("correlation_id", "-")

    lines.append(f"  [{msg_type}] to={recipient[:10]}...  status={status}  corr={corr}")
    lines.append(f"    sent: {sent_at}")

    payload = msg.get("payload", {})
    if isinstance(payload, dict) and payload.get("message"):
        lines.append(f"    message: {payload['message']}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="AgentFax Inbox — view and manage messages"
    )
    parser.add_argument("data_dir", help="AgentFax data directory (e.g. ~/.agentfax)")

    # Filter options
    parser.add_argument("--type", "-t", help="Filter by message type")
    parser.add_argument("--from", dest="sender", help="Filter by sender name")
    parser.add_argument("--status", "-s", default=None,
                        help="Filter by status (new, processing, processed, failed)")
    parser.add_argument("--since", help="Only messages after ISO timestamp")
    parser.add_argument("--limit", "-n", type=int, default=20,
                        help="Max messages to show (default 20)")

    # Actions
    parser.add_argument("--pull", action="store_true",
                        help="Pull fresh messages from bridge into store")
    parser.add_argument("--outbox", action="store_true",
                        help="Show sent messages instead")
    parser.add_argument("--stats", action="store_true",
                        help="Show message statistics")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show full payload")

    args = parser.parse_args()

    inbox = InboxStore(args.data_dir)

    try:
        # Pull fresh messages from bridge
        if args.pull:
            fax = AgentFaxClient(args.data_dir)
            messages = fax.receive(clear=True)
            saved = 0
            for msg in messages:
                if inbox.save(msg):
                    saved += 1
            print(f"Pulled {len(messages)} messages, {saved} new saved.")
            print()

        if args.stats:
            total = inbox.count()
            new = inbox.count("new")
            processing = inbox.count("processing")
            processed = inbox.count("processed")
            failed = inbox.count("failed")

            print("─── Inbox Stats ───")
            print(f"  Total:      {total}")
            print(f"  New:        {new}")
            print(f"  Processing: {processing}")
            print(f"  Processed:  {processed}")
            print(f"  Failed:     {failed}")

            outbox = OutboxStore(args.data_dir)
            out_total = outbox.count()
            out_sent = outbox.count("sent")
            out_acked = outbox.count("acked")
            print(f"\n─── Outbox Stats ───")
            print(f"  Total:  {out_total}")
            print(f"  Sent:   {out_sent}")
            print(f"  Acked:  {out_acked}")
            outbox.close()
            return

        if args.outbox:
            outbox = OutboxStore(args.data_dir)
            messages = outbox.query(limit=args.limit)
            if not messages:
                print("No sent messages.")
            else:
                print(f"─── Outbox ({len(messages)} messages) ───")
                for msg in messages:
                    print(format_outbox_message(msg))
                    print()
            outbox.close()
            return

        # Query inbox
        messages = inbox.query(
            status=args.status,
            msg_type=args.type,
            sender_id=args.sender,
            since=args.since,
            limit=args.limit,
        )

        if not messages:
            filter_desc = []
            if args.status:
                filter_desc.append(f"status={args.status}")
            if args.type:
                filter_desc.append(f"type={args.type}")
            if args.sender:
                filter_desc.append(f"from={args.sender}")
            extra = f" (filters: {', '.join(filter_desc)})" if filter_desc else ""
            print(f"No messages in inbox{extra}.")
        else:
            print(f"─── Inbox ({len(messages)} messages) ───")
            for msg in messages:
                print(format_message(msg, verbose=args.verbose))
                print()

    finally:
        inbox.close()


if __name__ == "__main__":
    main()
