#!/usr/bin/env python3
"""MCP Server for Code Archeologist.

Implements JSON-RPC 2.0 with MCP protocol features:
- Initialize handshake
- Tool schema declarations
- Progress notifications
- Batch requests
- Caching for performance
- Structured error handling
- Config via environment variables
"""

import json
import sys
import os
import time
import logging
from pathlib import Path
from typing import Any, Optional
from functools import lru_cache

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import importlib

git_walker = importlib.import_module("src.git.walker")
ast_parser = importlib.import_module("src.ast.parser")
ast_lineage = importlib.import_module("src.ast.lineage")
github_fetcher = importlib.import_module("src.github.fetcher")
db_database = importlib.import_module("src.db.database")

GitWalker = git_walker.GitWalker
ASTParser = ast_parser.ASTParser
LineageTracker = ast_lineage.LineageTracker
PRFetcher = github_fetcher.PRFetcher
Database = db_database.Database

logger = logging.getLogger("archeologist")

ARC_DB_PATH = os.environ.get("ARC_DB_PATH", "/tmp/archeologist.db")
ARC_MAX_COMMITS = int(os.environ.get("ARC_MAX_COMMITS", "100"))
ARC_LOG_LEVEL = os.environ.get("ARC_LOG_LEVEL", "INFO")
ARC_CACHE_TTL = int(os.environ.get("ARC_CACHE_TTL", "300"))
ARC_VERBOSE = os.environ.get("ARC_VERBOSE", "").lower() in ("1", "true", "yes")


def setup_logging():
    """Configure logging based on environment."""
    level = (
        logging.DEBUG
        if ARC_VERBOSE
        else getattr(logging, ARC_LOG_LEVEL.upper(), logging.INFO)
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        if ARC_VERBOSE
        else "%(levelname)s: %(message)s",
    )


setup_logging()


class ASTCache:
    """LRU cache for parsed AST results."""

    def __init__(self, maxsize: int = 100, ttl: int = 300):
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache: dict = {}
        self._timestamps: dict = {}

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self._cache:
            if time.time() - self._timestamps[key] < self.ttl:
                logger.debug(f"AST cache hit: {key}")
                return self._cache[key]
            else:
                del self._cache[key]
                del self._timestamps[key]
                logger.debug(f"AST cache expired: {key}")
        return None

    def set(self, key: str, value: Any):
        """Set cached value."""
        if len(self._cache) >= self.maxsize:
            oldest = min(self._timestamps, key=self._timestamps.get)
            del self._cache[oldest]
            del self._timestamps[oldest]
        self._cache[key] = value
        self._timestamps[key] = time.time()
        logger.debug(f"AST cache set: {key}")

    def clear(self):
        """Clear all cached values."""
        self._cache.clear()
        self._timestamps.clear()


ast_cache = ASTCache(ttl=ARC_CACHE_TTL)


TOOL_SCHEMAS = {
    "analyze_function": {
        "description": "Analyze a function's decision history across git commits",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "function_name": {
                    "type": "string",
                    "description": "Name of the function to analyze",
                },
                "max_commits": {
                    "type": "integer",
                    "description": "Max commits to analyze",
                    "default": 100,
                },
                "repo_name": {
                    "type": "string",
                    "description": "GitHub repo (owner/repo) for PR integration",
                },
            },
            "required": ["file_path", "function_name"],
        },
    },
    "analyze_file": {
        "description": "Analyze a file's overall lineage across commits",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "max_commits": {
                    "type": "integer",
                    "description": "Max commits to analyze",
                    "default": 100,
                },
            },
            "required": ["file_path"],
        },
    },
    "list_functions": {
        "description": "List all functions/classes in a file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
            },
            "required": ["file_path"],
        },
    },
    "get_commits": {
        "description": "Get commit history for a file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "max_count": {
                    "type": "integer",
                    "description": "Max commits to return",
                    "default": 50,
                },
            },
            "required": ["file_path"],
        },
    },
    "get_file_moves": {
        "description": "Trace file renames/moves through history",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Current file path"},
            },
            "required": ["file_path"],
        },
    },
    "search_functions": {
        "description": "Search for functions across all files in repo",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {
                    "type": "string",
                    "description": "Path to git repository",
                },
                "function_name": {
                    "type": "string",
                    "description": "Function name to search for",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Max files to search",
                    "default": 20,
                },
            },
            "required": ["repo_path", "function_name"],
        },
    },
}


class MCPMethods:
    """Expose archeologist methods as MCP tools."""

    def __init__(self):
        self.git_token = os.environ.get("GITHUB_TOKEN")
        self.db_path = ARC_DB_PATH
        self.max_commits = ARC_MAX_COMMITS
        self._db: Optional[Database] = None

    @property
    def db(self) -> Database:
        if self._db is None:
            self._db = Database(self.db_path)
            logger.debug(f"Database initialized: {self.db_path}")
        return self._db

    def send_progress(self, progress: float, message: str = "") -> dict:
        """Send progress notification."""
        return {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {
                "progress": progress,
                "message": message,
            },
        }

    def get_config(self) -> dict:
        """Return server configuration."""
        return {
            "db_path": self.db_path,
            "max_commits": self.max_commits,
            "cache_ttl": ARC_CACHE_TTL,
            "verbose": ARC_VERBOSE,
        }

    def initialize(self, client_info: dict = None) -> dict:
        """Handle MCP initialize handshake."""
        logger.info(f"Initialized with client: {client_info}")
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": True,
                "resources": True,
                "logging": True,
            },
            "serverInfo": {
                "name": "archeologist",
                "version": "0.1.0",
            },
            "serverConfig": self.get_config(),
            "clientInfo": client_info,
        }

    def list_tools(self) -> dict:
        """Return available tools."""
        return {
            "tools": [{"name": name, **schema} for name, schema in TOOL_SCHEMAS.items()]
        }

    def list_resources(self) -> dict:
        """Return available resources (cached files)."""
        resources = []
        try:
            edges = self.db.get_lineage_edges()
            for edge in edges[:50]:
                resources.append(
                    {
                        "uri": f"lineage://edge/{edge['parent_node_id']}/{edge['child_node_id']}",
                        "name": f"Lineage edge: {edge['change_type']}",
                        "mimeType": "application/json",
                    }
                )
        except Exception as e:
            logger.debug(f"Could not list resources: {e}")

        return {"resources": resources}

    def read_resource(self, uri: str) -> dict:
        """Read a specific resource."""
        if uri.startswith("lineage://edge/"):
            parts = uri.replace("lineage://edge/", "").split("/")
            if len(parts) >= 2:
                parent_id, child_id = parts[0], parts[1]
                chain = self.db.get_lineage_chain(child_id)
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "application/json",
                            "text": json.dumps(chain),
                        }
                    ]
                }

        return {"error": f"Unknown resource: {uri}"}

    def log_message(self, level: str, message: str) -> dict:
        """Handle logging from client."""
        log_levels = {
            "debug": logger.debug,
            "info": logger.info,
            "warning": logger.warning,
            "error": logger.error,
        }
        log_fn = log_levels.get(level, logger.info)
        log_fn(message)
        return {"success": True}

    def call_tool(self, name: str, arguments: dict = None) -> dict:
        """Call a tool by name."""
        if name not in TOOL_SCHEMAS:
            return {"error": f"Unknown tool: {name}"}

        args = arguments or {}
        method = getattr(self, name, None)
        if not method:
            return {"error": f"Method not found: {name}"}

        try:
            return {"content": [{"type": "text", "text": str(method(**args))}]}
        except Exception as e:
            return {"error": str(e)}

    def analyze_function(
        self,
        file_path: str,
        function_name: str,
        max_commits: int = 100,
        repo_name: str = "",
    ) -> dict:
        """Analyze a function's lineage."""
        if not os.path.isabs(file_path):
            return {"error": "Please provide absolute path to file"}

        repo_path = self._find_git_repo(file_path)
        if not repo_path:
            return {"error": "No git repo found"}

        git = GitWalker(repo_path)
        ast = ASTParser()
        tracker = LineageTracker(git, ast)

        language = ast.detect_language(file_path) or "python"
        relative_path = Path(file_path).relative_to(repo_path)

        edges = tracker.track_lineage(
            str(relative_path), function_name, language, max_commits
        )

        pr_fetcher = PRFetcher(self.git_token) if self.git_token else None
        pr_info = []
        for edge in edges[:5]:
            if pr_fetcher and repo_name:
                pr = pr_fetcher.get_pr_from_commit(
                    repo_name, edge.commit_hash, edge.commit_message
                )
                if pr:
                    pr_info.append(f"PR #{pr.number}: {pr.title}")

        result = {
            "function": function_name,
            "file": file_path,
            "repo": repo_path,
            "language": language,
            "lineage_edges": len(edges),
            "changes": [
                {
                    "type": e.change_type,
                    "confidence": round(e.confidence, 2),
                    "commit": e.commit_hash[:8] if e.commit_hash else "",
                    "message": (e.commit_message or "").split("\n")[0],
                }
                for e in edges[:10]
            ],
            "prs": pr_info,
        }

        for edge in edges[:10]:
            self.db.insert_lineage_edge(
                {
                    "parent_node_id": edge.parent_node_id,
                    "child_node_id": edge.child_node_id,
                    "change_type": edge.change_type,
                    "confidence": edge.confidence,
                    "commit_hash": edge.commit_hash,
                    "commit_message": edge.commit_message,
                    "author": edge.author,
                    "date": edge.date,
                }
            )

        return result

    def analyze_file(
        self,
        file_path: str,
        max_commits: int = 100,
    ) -> dict:
        """Analyze a file's overall lineage."""
        if not os.path.isabs(file_path):
            return {"error": "Please provide absolute path to file"}

        repo_path = self._find_git_repo(file_path)
        if not repo_path:
            return {"error": "No git repo found"}

        git = GitWalker(repo_path)
        ast = ASTParser()
        tracker = LineageTracker(git, ast)

        language = ast.detect_language(file_path) or "python"
        relative_path = Path(file_path).relative_to(repo_path)
        file_name = Path(file_path).stem

        edges = tracker.track_lineage(
            str(relative_path), file_name, language, max_commits
        )

        return {
            "file": file_path,
            "repo": repo_path,
            "language": language,
            "lineage_edges": len(edges),
            "changes": [
                {
                    "type": e.change_type,
                    "confidence": round(e.confidence, 2),
                    "commit": e.commit_hash[:8] if e.commit_hash else "",
                }
                for e in edges[:10]
            ],
            "summary": f"Found {len(edges)} historical versions across {len(set(e.commit_hash[:8] for e in edges if e.commit_hash))} commits",
        }

    def list_functions(self, file_path: str) -> dict:
        """List all functions in a file."""
        if not os.path.isabs(file_path):
            return {"error": "Please provide absolute path to file"}

        if not os.path.exists(file_path):
            return {"error": "File not found"}

        cache_key = f"parse:{file_path}"
        cached = ast_cache.get(cache_key)
        if cached:
            tree, language = cached
            ast = ASTParser()
        else:
            ast = ASTParser()
            language = ast.detect_language(file_path) or "python"

            with open(file_path, "r") as f:
                content = f.read()

            tree = ast.parse_file(content, language)
            if not tree:
                return {"error": "Failed to parse file"}

            ast_cache.set(cache_key, (tree, language))

        nodes = ast.extract_nodes(tree, language)

        functions = []
        classes = []
        for n in nodes:
            if n.node_type in (
                "function_definition",
                "function_declaration",
                "function_item",
                "method",
                "def",
            ):
                functions.append(
                    {"name": n.name, "line": n.start_line, "end_line": n.end_line}
                )
            elif n.node_type in ("class_definition", "class_declaration", "class"):
                classes.append(
                    {"name": n.name, "line": n.start_line, "end_line": n.end_line}
                )

        return {
            "file": file_path,
            "language": language,
            "functions": functions,
            "classes": classes,
            "total": len(functions) + len(classes),
        }

    def get_commits(self, file_path: str, max_count: int = 50) -> dict:
        """Get commit history for a file."""
        if not os.path.isabs(file_path):
            return {"error": "Please provide absolute path to file"}

        repo_path = self._find_git_repo(file_path)
        if not repo_path:
            return {"error": "No git repo found"}

        git = GitWalker(repo_path)
        relative_path = Path(file_path).relative_to(repo_path)

        commits = git.get_commits_for_file(str(relative_path), max_count)

        return {
            "file": file_path,
            "repo": repo_path,
            "commits": [
                {
                    "hash": c.hash[:8],
                    "full_hash": c.hash,
                    "author": c.author,
                    "date": c.date,
                    "message": c.message.split("\n")[0],
                }
                for c in commits
            ],
            "count": len(commits),
        }

    def get_file_moves(self, file_path: str) -> dict:
        """Trace file renames through history."""
        if not os.path.isabs(file_path):
            return {"error": "Please provide absolute path to file"}

        repo_path = self._find_git_repo(file_path)
        if not repo_path:
            return {"error": "No git repo found"}

        git = GitWalker(repo_path)
        relative_path = Path(file_path).relative_to(repo_path)

        moves = git.get_file_moves(str(relative_path))

        return {
            "current_path": file_path,
            "repo": repo_path,
            "moves": [
                {
                    "old_path": m.old_path,
                    "new_path": m.new_path,
                    "commit": m.commit_hash[:8],
                }
                for m in moves
            ],
            "count": len(moves),
        }

    def search_functions(
        self,
        repo_path: str,
        function_name: str,
        max_files: int = 20,
    ) -> dict:
        """Search for a function across files in a repo."""
        if not os.path.isdir(repo_path):
            return {"error": "Invalid repository path"}

        git = GitWalker(repo_path)
        ast = ASTParser()

        results = []
        extensions = {
            ".py",
            ".js",
            ".ts",
            ".go",
            ".rs",
            ".java",
            ".c",
            ".cpp",
            ".rb",
            ".php",
        }

        for path in Path(repo_path).rglob("*"):
            if path.suffix not in extensions or len(results) >= max_files:
                continue
            try:
                content = path.read_text()
                tree = ast.parse_file(
                    content, ast.detect_language(str(path)) or "python"
                )
                if tree:
                    nodes = ast.extract_nodes(
                        tree, ast.detect_language(str(path)) or "python"
                    )
                    for node in nodes:
                        if node.name == function_name:
                            results.append(
                                {
                                    "file": str(path.relative_to(repo_path)),
                                    "line": node.start_line,
                                    "type": node.node_type,
                                }
                            )
            except Exception:
                continue

        return {
            "function": function_name,
            "repo": repo_path,
            "matches": results,
            "count": len(results),
        }

    def _find_git_repo(self, file_path: str) -> str:
        """Find git repo root."""
        current = Path(file_path)
        while current != current.parent:
            if (current / ".git").exists():
                return str(current)
            current = current.parent
        return ""


class MCPServer:
    """MCP Server with JSON-RPC 2.0 protocol."""

    def __init__(self):
        self.methods = MCPMethods()
        self.initialized = False

    def handle_request(self, request: dict) -> Optional[dict]:
        """Handle a single JSON-RPC request."""
        if request.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32600, "message": "Invalid JSON-RPC"},
            }

        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            self.initialized = True
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": self.methods.initialize(params),
            }

        if not self.initialized and method != "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32001, "message": "Server not initialized"},
            }

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": self.methods.list_tools()}

        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": self.methods.call_tool(
                    params.get("name"), params.get("arguments")
                ),
            }

        method_func = getattr(self.methods, method, None)
        if not method_func:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        try:
            if isinstance(params, dict):
                result = method_func(**params)
            else:
                result = method_func()
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }

    def run(self):
        """Run server over stdio."""
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                request = json.loads(line.strip())

                if "batch" in request:
                    responses = []
                    for req in request["batch"]:
                        resp = self.handle_request(req)
                        if resp:
                            responses.append(resp)
                    if responses:
                        print(json.dumps(responses), flush=True)
                else:
                    response = self.handle_request(request)
                    if response:
                        print(json.dumps(response), flush=True)

            except json.JSONDecodeError:
                print(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "error": {"code": -32700, "message": "Parse error"},
                        }
                    ),
                    flush=True,
                )
            except KeyboardInterrupt:
                break
            except Exception:
                pass


if __name__ == "__main__":
    server = MCPServer()
    server.run()


def main():
    """Entry point for arc-mcp command."""
    server = MCPServer()
    server.run()
