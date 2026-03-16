#!/usr/bin/env python3
"""
AgentFax Skill Cards — view local skills and cached peer cards.

Usage:
    # List your local skill cards
    python3 fax_skills.py ~/.agentfax local

    # Show a specific local skill card
    python3 fax_skills.py ~/.agentfax local --name echo

    # List cached peer skill cards
    python3 fax_skills.py ~/.agentfax peers

    # Show cards from a specific peer
    python3 fax_skills.py ~/.agentfax peers --peer icy

    # Find who offers a specific skill
    python3 fax_skills.py ~/.agentfax find --skill data_analysis

    # Show cache stats
    python3 fax_skills.py ~/.agentfax stats
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from executor import TaskExecutor, register_builtin_skills
from skill_registry import SkillCard, PeerSkillCache


def format_card(card: dict, verbose: bool = False) -> str:
    """Format a Skill Card for display."""
    lines = []
    name = card.get("skill_name") or card.get("name", "?")
    desc = card.get("description", "")
    version = card.get("skill_version", "")
    trust = card.get("trust_requirements", {})
    pricing = card.get("pricing", {})
    tags = card.get("tags", [])

    lines.append(f"  {name} v{version}")
    if desc:
        lines.append(f"    {desc}")

    min_tier = trust.get("min_trust_tier", "?")
    privacy = trust.get("max_context_privacy_tier", "?")
    lines.append(f"    trust: min_tier={min_tier}  privacy={privacy}")

    price_model = pricing.get("model", "free")
    if price_model != "free":
        amount = pricing.get("amount", 0)
        currency = pricing.get("currency", "USD")
        lines.append(f"    pricing: {price_model} {amount} {currency}")
    else:
        lines.append(f"    pricing: free")

    if tags:
        lines.append(f"    tags: {', '.join(tags)}")

    if verbose:
        provider = card.get("provider", {})
        if provider.get("agent_id"):
            lines.append(f"    provider: {provider['agent_id']}")
        timeouts = card.get("timeouts", {})
        if timeouts:
            lines.append(f"    timeouts: task={timeouts.get('task_ttl_seconds', '?')}s  ack={timeouts.get('ack_timeout_seconds', '?')}s")
        caps = card.get("capabilities", {})
        if caps:
            cap_list = [k for k, v in caps.items() if v]
            if cap_list:
                lines.append(f"    capabilities: {', '.join(cap_list)}")
        schema_hash = card.get("schema_hash", "")
        if schema_hash:
            lines.append(f"    schema_hash: {schema_hash}")

        in_schema = card.get("input_schema", {})
        out_schema = card.get("output_schema", {})
        if in_schema:
            lines.append(f"    input:  {json.dumps(in_schema)}")
        if out_schema:
            lines.append(f"    output: {json.dumps(out_schema)}")

    return "\n".join(lines)


def cmd_local(args):
    """List local skill cards."""
    executor = TaskExecutor()
    register_builtin_skills(executor)

    if args.name:
        skill_def = executor.get_skill(args.name)
        if not skill_def:
            print(f"No local skill named '{args.name}'")
            sys.exit(1)
        card = skill_def.to_skill_card()
        if args.json:
            print(json.dumps(card.to_dict(), indent=2))
        else:
            print(format_card(card.to_dict(), verbose=True))
    else:
        cards = executor.list_skill_cards()
        print(f"Local skills ({len(cards)}):\n")
        for card in cards:
            print(format_card(card, verbose=args.verbose))
            print()


def cmd_peers(args):
    """List cached peer skill cards."""
    cache = PeerSkillCache(args.data_dir)
    try:
        if args.peer:
            cards = cache.get_cards(args.peer, include_expired=args.include_expired)
            if not cards:
                print(f"No cached cards for peer '{args.peer}'")
                return
            print(f"Skill cards from {args.peer} ({len(cards)}):\n")
            for card in cards:
                if args.json:
                    print(json.dumps(card, indent=2))
                else:
                    print(format_card(card, verbose=args.verbose))
                    print()
        else:
            peers = cache.list_all_peers()
            if not peers:
                print("No cached peer skill cards.")
                return
            for peer_id in peers:
                cards = cache.get_cards(peer_id, include_expired=args.include_expired)
                print(f"{peer_id} ({len(cards)} skills):")
                for card in cards:
                    name = card.get("skill_name") or card.get("name", "?")
                    print(f"  - {name}")
                print()
    finally:
        cache.close()


def cmd_find(args):
    """Find peers that offer a specific skill."""
    cache = PeerSkillCache(args.data_dir)
    try:
        if args.skill:
            results = cache.find_by_skill(args.skill)
        elif args.tag:
            results = cache.find_by_tag(args.tag)
        else:
            print("Specify --skill or --tag")
            sys.exit(1)

        if not results:
            print(f"No peers found.")
            return

        print(f"Found {len(results)} result(s):\n")
        for entry in results:
            peer_id = entry["peer_id"]
            card = entry["card"]
            name = card.get("skill_name") or card.get("name", "?")
            print(f"  {peer_id} → {name}")
            if args.verbose:
                print(format_card(card, verbose=True))
                print()
    finally:
        cache.close()


def cmd_stats(args):
    """Show skill card cache stats."""
    cache = PeerSkillCache(args.data_dir)
    try:
        total = cache.count()
        peers = cache.list_all_peers()
        evicted = cache.evict_expired()

        print(f"Peer Skill Card Cache:")
        print(f"  Total cards:   {total}")
        print(f"  Unique peers:  {len(peers)}")
        if evicted:
            print(f"  Evicted:       {evicted} expired")

        if peers:
            print(f"\n  Per peer:")
            for peer_id in peers:
                count = cache.count(peer_id)
                print(f"    {peer_id}: {count} cards")
    finally:
        cache.close()


def main():
    parser = argparse.ArgumentParser(
        description="AgentFax Skill Cards — view and manage skill discovery"
    )
    parser.add_argument("data_dir", help="AgentFax data directory")

    sub = parser.add_subparsers(dest="command")

    # local
    p_local = sub.add_parser("local", help="List local skill cards")
    p_local.add_argument("--name", help="Show a specific skill")
    p_local.add_argument("--json", action="store_true", help="Output as JSON")
    p_local.add_argument("--verbose", "-v", action="store_true")

    # peers
    p_peers = sub.add_parser("peers", help="List cached peer skill cards")
    p_peers.add_argument("--peer", help="Filter by peer")
    p_peers.add_argument("--json", action="store_true", help="Output as JSON")
    p_peers.add_argument("--include-expired", action="store_true")
    p_peers.add_argument("--verbose", "-v", action="store_true")

    # find
    p_find = sub.add_parser("find", help="Find peers by skill or tag")
    p_find.add_argument("--skill", help="Skill name to search")
    p_find.add_argument("--tag", help="Tag to search")
    p_find.add_argument("--verbose", "-v", action="store_true")

    # stats
    sub.add_parser("stats", help="Show cache stats")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "local":
        cmd_local(args)
    elif args.command == "peers":
        cmd_peers(args)
    elif args.command == "find":
        cmd_find(args)
    elif args.command == "stats":
        cmd_stats(args)


if __name__ == "__main__":
    main()
