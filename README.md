# Archeologist - Semantic Lineage Graph Generator

Post-incident archaeology tool that reconstructs function decision history via deterministic AST-aware lineage tracking.

## CLI Usage

```bash
# Install
pip install -e .

# Analyze entire file
arc analyze path/to/file.py

# Analyze specific function  
arc analyze-function path/to/file.py function_name
```

## Configuration

Set environment variables:

```bash
export GITHUB_TOKEN=ghp_xxx
export CLAUDE_API_KEY=sk-ant-xxx
```

Or copy `.env.example` to `.env` and fill in your values.

## Architecture

Three-phase pipeline:
1. **Semantic Lineage Tracking** - GitWalker + ASTParser + LineageTracker
2. **Contextual Slicing** - PRFetcher + Geographic filter
3. **Narrative Synthesis** - LiteLLM → 5-sentence brief
