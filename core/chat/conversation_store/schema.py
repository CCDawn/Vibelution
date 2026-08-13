"""Schema contract for the Agent/session SQLite control plane.

The package holds Agent/config/session directory control metadata.
Turn journal remains the durable transcript; no live repository API writes
turns or turn_items.  Every control write must go through the single writer
coordinator; this module only owns deterministic schema declarations and
migration checksums.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

SCHEMA_VERSION = 3


@dataclass(frozen=True)
class Migration:
    version: int
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        payload = "\n;\n".join(statement.strip() for statement in self.statements)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_SCHEMA_V1_STATEMENTS = (
    """
    CREATE TABLE schema_migrations (
      version INTEGER PRIMARY KEY,
      applied_at_ms INTEGER NOT NULL,
      checksum TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE conversation_store_meta (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      schema_version INTEGER NOT NULL,
      created_at_ms INTEGER NOT NULL,
      updated_at_ms INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE agents (
      agent_id TEXT PRIMARY KEY,
      display_name TEXT NOT NULL,
      kind TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',
      current_config_revision_id TEXT,
      created_at_ms INTEGER NOT NULL,
      updated_at_ms INTEGER NOT NULL,
      archived_at_ms INTEGER,
      FOREIGN KEY (agent_id, current_config_revision_id)
        REFERENCES agent_config_revisions(agent_id, revision_id)
        DEFERRABLE INITIALLY DEFERRED
    )
    """,
    """
    CREATE TABLE agent_config_revisions (
      revision_id TEXT PRIMARY KEY,
      agent_id TEXT NOT NULL,
      config_hash TEXT NOT NULL,
      config_json TEXT NOT NULL,
      source TEXT NOT NULL,
      created_at_ms INTEGER NOT NULL,
      UNIQUE (agent_id, revision_id),
      UNIQUE (agent_id, config_hash),
      FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE sessions (
      session_id TEXT PRIMARY KEY,
      agent_id TEXT NOT NULL,
      parent_session_id TEXT,
      agent_config_revision_id TEXT NOT NULL,
      title TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'ready',
      recency_at_ms INTEGER NOT NULL,
      updated_at_ms INTEGER NOT NULL,
      next_turn_sequence INTEGER NOT NULL DEFAULT 0 CHECK (next_turn_sequence >= 0),
      next_item_sequence INTEGER NOT NULL DEFAULT 0 CHECK (next_item_sequence >= 0),
      created_at_ms INTEGER NOT NULL,
      archived_at_ms INTEGER,
      UNIQUE (agent_id, session_id),
      FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE RESTRICT,
      FOREIGN KEY (agent_id, agent_config_revision_id)
        REFERENCES agent_config_revisions(agent_id, revision_id) ON DELETE RESTRICT,
      FOREIGN KEY (agent_id, parent_session_id)
        REFERENCES sessions(agent_id, session_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE turns (
      turn_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      client_submission_id TEXT,
      sequence INTEGER NOT NULL CHECK (sequence >= 1),
      status TEXT NOT NULL DEFAULT 'running',
      started_at_ms INTEGER NOT NULL,
      completed_at_ms INTEGER,
      updated_at_ms INTEGER NOT NULL,
      UNIQUE (session_id, sequence),
      FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE UNIQUE INDEX idx_turns_submission
    ON turns(session_id, client_submission_id)
    WHERE client_submission_id IS NOT NULL
    """,
    """
    CREATE TABLE turn_items (
      item_id TEXT PRIMARY KEY,
      turn_id TEXT NOT NULL,
      call_id TEXT,
      sequence INTEGER NOT NULL CHECK (sequence >= 1),
      revision INTEGER NOT NULL CHECK (revision >= 1),
      kind TEXT NOT NULL,
      status TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      created_at_ms INTEGER NOT NULL,
      updated_at_ms INTEGER NOT NULL,
      UNIQUE (turn_id, sequence),
      FOREIGN KEY (turn_id) REFERENCES turns(turn_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE turn_item_chunks (
      item_id TEXT NOT NULL,
      chunk_sequence INTEGER NOT NULL CHECK (chunk_sequence >= 1),
      revision INTEGER NOT NULL CHECK (revision >= 1),
      content TEXT NOT NULL,
      created_at_ms INTEGER NOT NULL,
      PRIMARY KEY (item_id, chunk_sequence),
      FOREIGN KEY (item_id) REFERENCES turn_items(item_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE checkpoints (
      checkpoint_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      turn_id TEXT,
      parent_checkpoint_id TEXT,
      trigger TEXT NOT NULL,
      snapshot_json TEXT NOT NULL,
      created_at_ms INTEGER NOT NULL,
      FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
      FOREIGN KEY (turn_id) REFERENCES turns(turn_id) ON DELETE SET NULL,
      FOREIGN KEY (parent_checkpoint_id)
        REFERENCES checkpoints(checkpoint_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE INDEX idx_sessions_agent_recency
    ON sessions(agent_id, archived_at_ms, recency_at_ms DESC, session_id DESC)
    """,
    """
    CREATE INDEX idx_sessions_parent
    ON sessions(parent_session_id, recency_at_ms DESC)
    """,
    """
    CREATE INDEX idx_turns_session_sequence
    ON turns(session_id, sequence DESC)
    """,
    """
    CREATE INDEX idx_items_turn_sequence
    ON turn_items(turn_id, sequence ASC, revision DESC)
    """,
    """
    CREATE INDEX idx_items_call
    ON turn_items(turn_id, call_id)
    WHERE call_id IS NOT NULL
    """,
    """
    CREATE INDEX idx_checkpoints_session_created
    ON checkpoints(session_id, created_at_ms DESC, checkpoint_id DESC)
    """,
)


# Version 2 deliberately adds only control-plane state.  The legacy transcript
# tables remain readable for an isolated migration, but no live repository API
# is allowed to write or read turns/items from SQLite.  Journal remains the
# only durable conversation and tool-event source.
_SCHEMA_V2_STATEMENTS = (
    """
    CREATE TABLE session_edges (
      source_session_id TEXT NOT NULL,
      target_session_id TEXT NOT NULL,
      relation_kind TEXT NOT NULL
        CHECK (relation_kind IN ('parent', 'fork', 'handoff')),
      created_at_ms INTEGER NOT NULL,
      PRIMARY KEY (source_session_id, target_session_id, relation_kind),
      FOREIGN KEY (source_session_id) REFERENCES sessions(session_id) ON DELETE RESTRICT,
      FOREIGN KEY (target_session_id) REFERENCES sessions(session_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE session_admissions (
      session_id TEXT NOT NULL,
      client_submission_id TEXT NOT NULL,
      turn_id TEXT NOT NULL,
      agent_id TEXT NOT NULL,
      agent_config_revision_id TEXT NOT NULL,
      state TEXT NOT NULL
        CHECK (state IN ('reserved', 'journaled', 'projected', 'rejected', 'expired')),
      journal_sequence INTEGER,
      journal_event_id TEXT,
      projected_sequence INTEGER,
      rejection_reason TEXT,
      created_at_ms INTEGER NOT NULL,
      updated_at_ms INTEGER NOT NULL,
      expires_at_ms INTEGER,
      PRIMARY KEY (session_id, client_submission_id),
      UNIQUE (turn_id),
      FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE RESTRICT,
      FOREIGN KEY (agent_id, agent_config_revision_id)
        REFERENCES agent_config_revisions(agent_id, revision_id) ON DELETE RESTRICT
    )
    """,
    """
    CREATE TABLE session_projection_offsets (
      session_id TEXT PRIMARY KEY,
      journal_sequence INTEGER NOT NULL CHECK (journal_sequence >= 0),
      updated_at_ms INTEGER NOT NULL,
      FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX idx_session_admissions_state_updated
    ON session_admissions(state, updated_at_ms, session_id)
    """,
    """
    CREATE INDEX idx_session_admissions_session_updated
    ON session_admissions(session_id, updated_at_ms DESC)
    """,
)

# Version 3 is the live session directory control plane.  It does not import
# historical transcripts; list/filter/pagination read these columns instead of
# scanning chat_state.json or turn_journal.jsonl.
_SCHEMA_V3_STATEMENTS = (
    """
    ALTER TABLE sessions ADD COLUMN session_kind TEXT NOT NULL DEFAULT 'main'
    """,
    """
    ALTER TABLE sessions ADD COLUMN session_role TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE sessions ADD COLUMN conversation_index_kind TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE sessions ADD COLUMN conversation_index_visibility TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE sessions ADD COLUMN hidden_from_index INTEGER NOT NULL DEFAULT 0
      CHECK (hidden_from_index IN (0, 1))
    """,
    """
    ALTER TABLE sessions ADD COLUMN team_id TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE sessions ADD COLUMN last_preview TEXT NOT NULL DEFAULT ''
    """,
    """
    ALTER TABLE sessions ADD COLUMN last_preview_at_ms INTEGER
    """,
    """
    ALTER TABLE conversation_store_meta
    ADD COLUMN legacy_sessions_discarded_at_ms INTEGER
    """,
    """
    CREATE INDEX idx_sessions_directory_recency
    ON sessions(archived_at_ms, hidden_from_index, recency_at_ms DESC, session_id DESC)
    """,
    """
    CREATE INDEX idx_sessions_kind_recency
    ON sessions(session_kind, archived_at_ms, recency_at_ms DESC, session_id DESC)
    """,
)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, statements=_SCHEMA_V1_STATEMENTS),
    Migration(version=2, statements=_SCHEMA_V2_STATEMENTS),
    Migration(version=3, statements=_SCHEMA_V3_STATEMENTS),
)
