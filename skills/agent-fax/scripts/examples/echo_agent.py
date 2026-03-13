#!/usr/bin/env python3
"""
AgentFax Echo Agent — minimal example of a collaborating agent.

This is the simplest possible AgentFax agent:
1. Starts the daemon with echo/reverse/word_count skills
2. Automatically responds to task_requests by executing the skill
3. Sends task_response back to the requester

Usage:
    python3 examples/echo_agent.py ~/.agentfax

    # Then from another agent:
    python3 fax_send.py ~/.agentfax 0xTHIS_AGENT --task echo --input "hello world"

How it works:
    1. Daemon polls bridge every 2 seconds
    2. When a task_request arrives with skill="echo":
       - task_handler.py accepts and executes it via executor.py
       - executor.py calls the registered echo function
       - task_handler.py sends task_response with the result
    3. The requester receives: {"echo": {"text": "hello world"}}
"""

import os
import signal
import sys

# Add scripts dir to path
scripts_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, scripts_dir)

from daemon import AgentFaxDaemon, setup_logging


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 echo_agent.py <data_dir>")
        print()
        print("Starts an AgentFax daemon with built-in skills:")
        print("  - echo: returns input unchanged")
        print("  - reverse: reverses text")
        print("  - word_count: counts words")
        print("  - ping_skill: liveness check")
        print()
        print("Example:")
        print("  python3 echo_agent.py ~/.agentfax")
        sys.exit(1)

    data_dir = sys.argv[1]
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    logger = setup_logging(data_dir, verbose=verbose)
    logger.info("Starting Echo Agent...")

    daemon = AgentFaxDaemon(data_dir, poll_interval=2.0)

    # You can register additional custom skills here:
    # @daemon.executor.skill("my_custom_skill")
    # def my_skill(input_data):
    #     return {"result": "processed"}

    print(f"Echo Agent ready!")
    print(f"  Agent: {daemon.client._sender_id}")
    print(f"  Skills: {', '.join(daemon.executor.skill_names)}")
    print(f"  Handlers: {', '.join(daemon.router.registered_types)}")
    print(f"Press Ctrl+C to stop.")
    print()

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print("\nShutting down...")
        daemon.stop()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    daemon.run()


if __name__ == "__main__":
    main()
