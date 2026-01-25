# Train With GPT

A simple Model Context Protocol (MCP) server implementation in Python.

## Features

This server provides a basic tool:
- **add**: Adds two numbers together

## Installation

```bash
# Install dependencies
pip install -e .
```

## Usage

### Running the server

```bash
# Run directly
python -m train_with_gpt.server

# Or use the installed script
train-with-gpt
```

### Configuration

To use this server with Claude Desktop or other MCP clients, add to your configuration:

```json
{
  "mcpServers": {
    "train-with-gpt": {
      "command": "python",
      "args": ["-m", "train_with_gpt.server"],
      "cwd": "/path/to/train-with-gpt"
    }
  }
}
```

## Development

Project structure:
```
train-with-gpt/
├── pyproject.toml
├── README.md
└── src/
    └── train_with_gpt/
        ├── __init__.py
        └── server.py
```

## Extending

To add more tools:
1. Add the tool definition in `list_tools()`
2. Add the tool handler in `call_tool()`
