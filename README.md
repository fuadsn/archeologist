# Archeologist - Semantic Lineage Graph Generator

Post-incident archaeology tool that reconstructs function decision history via deterministic AST-aware lineage tracking.

## CLI Usage

```bash
# Install
pip install -e .

# Analyze file (auto-detects git repo)
arc analyze path/to/file.py

# Analyze specific function  
arc analyze-function path/to/file.py function_name

# With GitHub PR integration
arc analyze-function path/to/file.py function_name --repo owner/repo

# With LLM narrative synthesis
export CLAUDE_API_KEY=sk-ant-xxx
arc analyze-function path/to/file.py function_name
```

## Configuration

Set environment variables:

```bash
export GITHUB_TOKEN=ghp_xxx
export CLAUDE_API_KEY=sk-ant-xxx
export GIT_REPO_PATH=/path/to/local/repo
```

## Architecture

Three-phase pipeline:

1. **Semantic Lineage Tracking**
   - GitWalker traverses history (--no-renames flag)
   - ASTParser extracts function boundaries (Python, JS, TS, Go, Rust, Java, C, C++, Ruby, PHP)
   - LineageTracker links nodes via four-tier hierarchy

2. **Contextual Slicing**
   - PRFetcher pulls associated PRs
   - Geographic filter maps review comments to AST node line ranges

3. **Narrative Synthesis**
   - LiteLLM abstracts LLM calls (Claude, local models)
   - Outputs 5-sentence brief explaining decisions

## MCP Server

The tool exposes an MCP-compatible JSON-RPC 2.0 server over stdio:

```bash
# Run MCP server
arc-mcp

# Or run directly
python -m src.mcp.server
```

### Available Methods

```json
// List functions in a file
{"jsonrpc": "2.0", "id": 1, "method": "list_functions", "params": {"file_path": "/path/to/file.py"}}

// Analyze a specific function
{"jsonrpc": "2.0", "id": 2, "method": "analyze_function", "params": {"file_path": "/path/to/file.py", "function_name": "foo"}}

// Analyze a file's overall lineage
{"jsonrpc": "2.0", "id": 3, "method": "analyze_file", "params": {"file_path": "/path/to/file.py"}}
```

## Example

```bash
# Analyze the `authenticate` function in a FastAPI project
GIT_REPO_PATH=/Users/fuads/fastapi arc analyze-function app/auth.py authenticate --repo fastapi/fastapi
```

Output:
```
Analyzing function authenticate in app/auth.py...
Found 12 lineage edges for authenticate
Summary: Found 12 historical versions of this code. Change types: physical: 8, identity: 4
```

With LLM synthesis:
```
The authenticate function evolved through 12 commits over 18 months. 
Initial implementation used simple token validation, replaced in PR #2341 
with OAuth2 Bearer token parsing after security audit. Several performance 
optimizations were attempted (PRs #1892, #2103) but reverted due to race 
conditions. The current implementation handles both JWT and opaque tokens 
with a unified interface, consolidating three previous approaches.
```

## Testing

```bash
pytest tests/
```

## Roadmap

- [x] Graph construction (GitWalker, ASTParser, LineageTracker)
- [x] Contextual slicing (PRFetcher, GeographicFilter)
- [x] CLI commands with local git repo auto-detection
- [x] 10 language support (Python, JS, TS, Go, Rust, Java, C, C++, Ruby, PHP)
- [x] Real-world testing on Flask repo
- [x] MCP server (JSON-RPC 2.0 over stdio, works with Python 3.9)

## License

MIT
