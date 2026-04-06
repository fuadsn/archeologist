# Archeologist - Code Lineage Tracker

CLI tool that reconstructs function decision history via AST-aware lineage tracking. Outputs JSON with commit messages and diffs - perfect for LLM context.

## Install

```bash
pip install archeologist
```

## Usage

```bash
# Analyze a specific function
arc analyze-function path/to/file.py function_name

# Get commit history with diffs
arc history path/to/file.py

# List all functions in a file
arc list-functions path/to/file.py
```

## Output

JSON with commit hash, message, author, date, and diff:

```json
{
  "file": "src/flask/helpers.py",
  "function": "stream_with_context",
  "repo": "/path/to/repo",
  "language": "python",
  "lineage_edges": 10,
  "changes": [
    {
      "commit_hash": "abc123...",
      "commit_message": "redirect defaults to 303",
      "author": "David Lord",
      "date": "2026-01-24T16:50:54-08:00",
      "diff": "diff --git a/src/flask/helpers.py..."
    }
  ]
}
```

## Environment

```bash
# Optional: for PR details
export GITHUB_TOKEN=ghp_xxx

# Optional: for narrative synthesis
export CLAUDE_API_KEY=sk-ant-xxx
```

## Languages Supported

Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby, PHP

## Commands

- `analyze` - Analyze file lineage
- `analyze-function` - Analyze specific function
- `history` - Show commit history with diffs
- `list-functions` - List all functions in file
- `search` - Search for function across repo
- `stats` - Repository statistics
