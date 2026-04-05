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
