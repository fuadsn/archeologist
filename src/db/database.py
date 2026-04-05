import sqlite3
from pathlib import Path
from typing import Optional
from contextlib import contextmanager


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS commits (
    hash TEXT PRIMARY KEY,
    author TEXT,
    author_email TEXT,
    date TEXT,
    message TEXT,
    parent_hashes TEXT
);

CREATE TABLE IF NOT EXISTS ast_nodes (
    node_id TEXT PRIMARY KEY,
    commit_hash TEXT,
    file_path TEXT,
    language TEXT,
    name TEXT,
    node_type TEXT,
    content TEXT,
    start_line INTEGER,
    end_line INTEGER,
    FOREIGN KEY (commit_hash) REFERENCES commits(hash)
);

CREATE TABLE IF NOT EXISTS lineage_edges (
    parent_node_id TEXT,
    child_node_id TEXT,
    change_type TEXT,
    confidence REAL,
    commit_hash TEXT,
    commit_message TEXT,
    author TEXT,
    date TEXT,
    FOREIGN KEY (parent_node_id) REFERENCES ast_nodes(node_id),
    FOREIGN KEY (child_node_id) REFERENCES ast_nodes(node_id),
    PRIMARY KEY (parent_node_id, child_node_id)
);

CREATE TABLE IF NOT EXISTS prs (
    pr_number INTEGER,
    repo_name TEXT,
    title TEXT,
    body TEXT,
    author TEXT,
    created_at TEXT,
    merged_at TEXT,
    is_reverted BOOLEAN,
    PRIMARY KEY (pr_number, repo_name)
);

CREATE TABLE IF NOT EXISTS localized_comments (
    comment_id TEXT PRIMARY KEY,
    pr_number INTEGER,
    node_id TEXT,
    body TEXT,
    author TEXT,
    created_at TEXT,
    FOREIGN KEY (node_id) REFERENCES ast_nodes(node_id)
);

CREATE TABLE IF NOT EXISTS file_moves (
    old_path TEXT,
    new_path TEXT,
    commit_hash TEXT,
    PRIMARY KEY (old_path, commit_hash)
);

CREATE INDEX IF NOT EXISTS idx_ast_nodes_commit ON ast_nodes(commit_hash);
CREATE INDEX IF NOT EXISTS idx_ast_nodes_file ON ast_nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_ast_nodes_name ON ast_nodes(name);
CREATE INDEX IF NOT EXISTS idx_lineage_parent ON lineage_edges(parent_node_id);
CREATE INDEX IF NOT EXISTS idx_lineage_child ON lineage_edges(child_node_id);
CREATE INDEX IF NOT EXISTS idx_comments_node ON localized_comments(node_id);
"""


class Database:
    def __init__(self, db_path: str = "archeologist.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def insert_commit(self, commit_data: dict):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO commits 
                   (hash, author, author_email, date, message, parent_hashes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    commit_data["hash"],
                    commit_data["author"],
                    commit_data["author_email"],
                    commit_data["date"],
                    commit_data["message"],
                    ",".join(commit_data.get("parent_hashes", [])),
                ),
            )
            conn.commit()

    def insert_ast_node(self, node_data: dict):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO ast_nodes 
                   (node_id, commit_hash, file_path, language, name, node_type, content, start_line, end_line)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node_data["node_id"],
                    node_data["commit_hash"],
                    node_data["file_path"],
                    node_data["language"],
                    node_data["name"],
                    node_data["node_type"],
                    node_data["content"],
                    node_data["start_line"],
                    node_data["end_line"],
                ),
            )
            conn.commit()

    def insert_lineage_edge(self, edge_data: dict):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO lineage_edges 
                   (parent_node_id, child_node_id, change_type, confidence, commit_hash, commit_message, author, date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    edge_data["parent_node_id"],
                    edge_data["child_node_id"],
                    edge_data["change_type"],
                    edge_data["confidence"],
                    edge_data.get("commit_hash", ""),
                    edge_data.get("commit_message", ""),
                    edge_data.get("author", ""),
                    edge_data.get("date", ""),
                ),
            )
            conn.commit()

    def insert_pr(self, pr_data: dict):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO prs 
                   (pr_number, repo_name, title, body, author, created_at, merged_at, is_reverted)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pr_data["pr_number"],
                    pr_data["repo_name"],
                    pr_data["title"],
                    pr_data["body"],
                    pr_data["author"],
                    pr_data["created_at"],
                    pr_data["merged_at"],
                    pr_data["is_reverted"],
                ),
            )
            conn.commit()

    def insert_localized_comment(self, comment_data: dict):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO localized_comments 
                   (comment_id, pr_number, node_id, body, author, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    comment_data["comment_id"],
                    comment_data["pr_number"],
                    comment_data["node_id"],
                    comment_data["body"],
                    comment_data["author"],
                    comment_data["created_at"],
                ),
            )
            conn.commit()

    def insert_file_move(self, move_data: dict):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO file_moves 
                   (old_path, new_path, commit_hash)
                   VALUES (?, ?, ?)""",
                (
                    move_data["old_path"],
                    move_data["new_path"],
                    move_data["commit_hash"],
                ),
            )
            conn.commit()

    def get_lineage_chain(self, node_id: str) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                """WITH RECURSIVE lineage AS (
                    SELECT parent_node_id, child_node_id, change_type, confidence, 1 as depth
                    FROM lineage_edges WHERE child_node_id = ?
                    UNION ALL
                    SELECT le.parent_node_id, le.child_node_id, le.change_type, le.confidence, l.depth + 1
                    FROM lineage_edges le
                    JOIN lineage l ON le.child_node_id = l.parent_node_id
                    WHERE l.depth < 50
                )
                SELECT * FROM lineage""",
                (node_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_ast_node(self, node_id: str) -> Optional[dict]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM ast_nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_comments_for_node(self, node_id: str) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM localized_comments WHERE node_id = ?", (node_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_pr(self, pr_number: int, repo_name: str) -> Optional[dict]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM prs WHERE pr_number = ? AND repo_name = ?",
                (pr_number, repo_name),
            ).fetchone()
            return dict(row) if row else None

    def get_localized_comments_for_node(self, node_id: str) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM localized_comments WHERE node_id = ?", (node_id,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_lineage_edges(self) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM lineage_edges").fetchall()
            return [dict(row) for row in rows]

    def clear_all(self):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM localized_comments")
            conn.execute("DELETE FROM prs")
            conn.execute("DELETE FROM lineage_edges")
            conn.execute("DELETE FROM ast_nodes")
            conn.execute("DELETE FROM commits")
            conn.execute("DELETE FROM file_moves")
            conn.commit()
