#!/usr/bin/env python3
"""Test script for train-with-gpt MCP server."""

import asyncio
import sys
from train_with_gpt.server import call_tool


async def test_connect():
    """Test connect_strava tool."""
    print("Testing connect_strava...")
    print("-" * 50)
    print("This will open your browser for authentication.")
    print("Press Ctrl+C to cancel.")
    print("-" * 50)
    
    try:
        result = await call_tool("connect_strava", {})
        for content in result:
            print(content.text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()


async def test_get_last_week():
    """Test get_last_week_activities tool."""
    print("\nTesting get_last_week_activities...")
    print("-" * 50)
    
    try:
        result = await call_tool("get_last_week_activities", {})
        for content in result:
            print(content.text)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()


async def main():
    """Run tests based on argument."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_tools.py connect     - Test Strava connection")
        print("  python test_tools.py activities  - Test fetching activities")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "connect":
        await test_connect()
    elif command == "activities":
        await test_get_last_week()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
