import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import tree_sitter_languages
from tree_sitter import Language, Parser, Tree, Node


@dataclass
class ASTNode:
    node_id: str
    name: str
    node_type: str
    content: str
    start_line: int
    end_line: int
    start_col: int
    end_col: int


LANGUAGE_MAP = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "jsx": "javascript",
    "go": "go",
    "rs": "rust",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "rb": "ruby",
    "php": "php",
    "dart": "dart",
}


FUNCTION_NODE_TYPES = {
    "python": [
        "function_definition",
        "async_function_definition",
    ],
    "javascript": [
        "function_declaration",
        "arrow_function",
        "method_definition",
    ],
    "typescript": [
        "function_declaration",
        "arrow_function",
        "method_definition",
        "function_expression",
    ],
    "go": [
        "function_declaration",
        "method_declaration",
    ],
    "rust": [
        "function_item",
        "method_definition",
    ],
    "java": [
        "method_declaration",
    ],
    "c": [
        "function_definition",
    ],
    "cpp": [
        "function_definition",
    ],
    "ruby": [
        "method",
        "def",
    ],
    "php": [
        "function_definition",
        "method_declaration",
    ],
    "dart": [
        "method_declaration",
        "function_expression",
        "constructor",
    ],
}


CLASS_NODE_TYPES = {
    "python": ["class_definition"],
    "javascript": ["class_declaration", "class"],
    "typescript": ["class_declaration", "class"],
    "go": ["type_declaration"],
    "rust": ["struct_item", "impl_item"],
    "java": ["class_declaration", "interface_declaration"],
    "c": ["struct_definition", "union_definition"],
    "cpp": ["class_specifier", "struct_specifier"],
    "ruby": ["class", "module"],
    "php": ["class_declaration", "interface_declaration", "trait_declaration"],
}


class ASTParser:
    def __init__(self):
        self.parsers: dict[str, Parser] = {}
        self._init_parsers()

    def _init_parsers(self):
        """Initialize tree-sitter parsers for all supported languages."""
        for short_lang, full_lang in LANGUAGE_MAP.items():
            if short_lang == "dart":
                self._init_dart_parser()
            else:
                try:
                    self.parsers[short_lang] = tree_sitter_languages.get_parser(
                        full_lang
                    )
                except Exception as e:
                    pass

    def _init_dart_parser(self):
        """Initialize Dart parser, installing tree-sitter-dart if needed."""
        try:
            from tree_sitter_dart import language
            from tree_sitter import Parser

            self.parsers["dart"] = Parser(language)
        except ImportError:
            import subprocess
            import sys

            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "tree-sitter-dart"],
                    stderr=subprocess.DEVNULL,
                )
                from tree_sitter_dart import language
                from tree_sitter import Parser

                self.parsers["dart"] = Parser(language)
            except Exception:
                pass

    def detect_language(self, file_path: str) -> Optional[str]:
        """Detect language from file extension."""
        ext = Path(file_path).suffix.lstrip(".")
        return LANGUAGE_MAP.get(ext)

    def parse_file(self, content: str, language: str) -> Optional[Tree]:
        """Parse file content and return AST tree."""
        lang_key = self._get_lang_key(language)
        short_key = self._get_short_key(language)
        if short_key not in self.parsers:
            return None
        try:
            return self.parsers[short_key].parse(content.encode("utf-8"))
        except Exception:
            return None

    def _get_short_key(self, language: str) -> str:
        """Get short language key for parser lookup."""
        if language in self.parsers:
            return language
        for short, full in LANGUAGE_MAP.items():
            if full == language:
                return short
        return language

    def extract_nodes(
        self, tree: Tree, language: str, node_types: Optional[list[str]] = None
    ) -> list[ASTNode]:
        """Extract all function/class nodes from AST."""
        if node_types is None:
            lang_key = self._get_lang_key(language)
            short_key = self._get_short_key(language)
            node_types = FUNCTION_NODE_TYPES.get(lang_key, []) + CLASS_NODE_TYPES.get(
                lang_key, []
            )
            if not node_types:
                node_types = FUNCTION_NODE_TYPES.get(
                    short_key, []
                ) + CLASS_NODE_TYPES.get(short_key, [])

        nodes = []
        root = tree.root_node
        self._traverse_nodes(root, node_types, nodes, language)
        return nodes

    def _get_lang_key(self, language: str) -> str:
        """Get language key for FUNCTION_NODE_TYPES lookup."""
        full_lang = LANGUAGE_MAP.get(language, language)
        return full_lang

    def _traverse_nodes(
        self, node: Node, target_types: list[str], results: list[ASTNode], language: str
    ):
        """Recursively traverse AST and collect matching nodes."""
        if node.type in target_types:
            ast_node = self._node_to_ast_node(node, language)
            if ast_node:
                results.append(ast_node)

        for child in node.children:
            self._traverse_nodes(child, target_types, results, language)

    def _node_to_ast_node(self, node: Node, language: str) -> Optional[ASTNode]:
        """Convert tree-sitter node to our ASTNode representation."""
        try:
            name = self._extract_node_name(node, language)
            if not name:
                return None

            content = (
                node.text.decode("utf-8")
                if isinstance(node.text, bytes)
                else str(node.text)
            )

            return ASTNode(
                node_id=f"{language}_{node.start_point[0]}_{node.end_point[0]}_{abs(hash(content)) % 100000:05d}",
                name=name,
                node_type=node.type,
                content=content,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                start_col=node.start_point[1],
                end_col=node.end_point[1],
            )
        except Exception:
            return None

    def _extract_node_name(self, node: Node, language: str) -> Optional[str]:
        """Extract function/class name from AST node."""
        for child in node.children:
            if child.type == "identifier":
                child_text = child.text
                if child_text:
                    return (
                        child_text.decode("utf-8")
                        if isinstance(child_text, bytes)
                        else str(child_text)
                    )
            if child.type == "name":
                child_text = child.text
                if child_text:
                    return (
                        child_text.decode("utf-8")
                        if isinstance(child_text, bytes)
                        else str(child_text)
                    )
        for child in node.children:
            name = self._extract_node_name(child, language)
            if name:
                return name
        return None

    def find_node_by_name(
        self, tree: Tree, language: str, name: str
    ) -> Optional[ASTNode]:
        """Find specific function/class by name."""
        nodes = self.extract_nodes(tree, language)
        for node in nodes:
            if node.name == name:
                return node
        return None

    def find_node_at_line(
        self, tree: Tree, language: str, line_number: int
    ) -> Optional[ASTNode]:
        """Find AST node containing a specific line number."""
        nodes = self.extract_nodes(tree, language)
        for node in nodes:
            if node.start_line <= line_number <= node.end_line:
                return node
        return None
