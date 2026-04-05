# Archeologist - Semantic Lineage Graph Generator

Post-incident archaeology tool that reconstructs function decision history via deterministic AST-aware lineage tracking.

## CLI Usage

```bash
# Install
pip install -e .

# Analyze file
arc analyze path/to/file.py --repo owner/repo

# Analyze specific function  
arc analyze-function path/to/file.py function_name --repo owner/repo
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
   - ASTParser extracts function boundaries (Python, JS, TS, Go, Rust)
   - LineageTracker links nodes via four-tier hierarchy

2. **Contextual Slicing**
   - PRFetcher pulls associated PRs
   - Geographic filter maps review comments to AST node line ranges

3. **Narrative Synthesis**
   - LiteLLM abstracts LLM calls (Claude, local models)
   - Outputs 5-sentence brief explaining decisions

## MCP Server

The tool can be exposed as an MCP server for AI agents. After installing:

```bash
# Run MCP server (when MCP SDK available for Python 3.9)
arc-mcp
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

- [x] Day 1: Graph construction (GitWalker, ASTParser, LineageTracker)
- [x] Day 2: Contextual slicing (PRFetcher, GeographicFilter)
- [ ] Day 3: MCP server for AI agent integration
- [ ] Real-world validation on open source repos

## License

MIT
