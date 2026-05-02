"""Agents — task-specific drivers that compose cua-maximalist primitives.

Each agent wraps a domain (Chess, Calculator+TextEdit, etc.) and exposes a
loop that calls the MCP healing tools to drive the target app. Agents are
not auto-loaded; scripts/ entrypoints import the agent they need.
"""
