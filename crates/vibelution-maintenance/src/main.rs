use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use std::env;
use std::path::{Path, PathBuf};
use std::time::Instant;

const DEFAULT_KEEP_LATEST: i64 = 50;
const MAX_KEEP_LATEST: i64 = 500;

#[derive(Debug)]
struct CliArgs {
    db_path: PathBuf,
    keep_latest: i64,
    integrity_check: bool,
    pretty: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MaintenanceReport {
    ok: bool,
    schema_version: u8,
    tool: &'static str,
    command: &'static str,
    db_path: String,
    keep_latest: i64,
    integrity_check_mode: &'static str,
    integrity_check: String,
    tables: TableReport,
    prune_dry_run: PruneDryRun,
    elapsed_ms: u128,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct TableReport {
    git_working_tree_snapshot: TableStats,
    git_file_change: TableStats,
    git_entity_change: TableStats,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct TableStats {
    exists: bool,
    row_count: i64,
    worktree_rows: i64,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PruneDryRun {
    candidate_snapshots: i64,
    candidate_file_rows: i64,
    candidate_entity_rows: i64,
    sample_snapshot_ids: Vec<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ErrorReport {
    ok: bool,
    schema_version: u8,
    tool: &'static str,
    command: String,
    error_type: &'static str,
    message: String,
}

fn main() {
    if let Err(message) = run() {
        let report = ErrorReport {
            ok: false,
            schema_version: 1,
            tool: "vibelution-maintenance",
            command: env::args().nth(1).unwrap_or_default(),
            error_type: "CliError",
            message,
        };
        eprintln!(
            "{}",
            serde_json::to_string(&report).unwrap_or_else(|_| "{\"ok\":false}".to_string())
        );
        std::process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let args = parse_args(env::args().skip(1).collect())?;
    let started_at = Instant::now();
    let conn = Connection::open_with_flags(
        &args.db_path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|err| format!("failed to open SQLite database read-only: {err}"))?;
    conn.pragma_update(None, "query_only", "ON")
        .map_err(|err| format!("failed to enable query_only mode: {err}"))?;

    let mut report = build_git_memory_report(&conn, &args.db_path, &args)
        .map_err(|err| format!("failed to build git-memory report: {err}"))?;
    report.elapsed_ms = started_at.elapsed().as_millis();

    let rendered = if args.pretty {
        serde_json::to_string_pretty(&report)
    } else {
        serde_json::to_string(&report)
    }
    .map_err(|err| format!("failed to render JSON report: {err}"))?;
    println!("{rendered}");
    Ok(())
}

fn parse_args(raw: Vec<String>) -> Result<CliArgs, String> {
    if raw.first().map(|value| value.as_str()) != Some("git-memory") {
        return Err(usage());
    }

    let mut db_path: Option<PathBuf> = None;
    let mut keep_latest = DEFAULT_KEEP_LATEST;
    let mut integrity_check = false;
    let mut pretty = false;
    let mut index = 1usize;
    while index < raw.len() {
        match raw[index].as_str() {
            "--db" => {
                index += 1;
                let Some(value) = raw.get(index) else {
                    return Err("--db requires a path".to_string());
                };
                db_path = Some(PathBuf::from(value));
            }
            "--keep-latest" => {
                index += 1;
                let Some(value) = raw.get(index) else {
                    return Err("--keep-latest requires an integer".to_string());
                };
                let parsed = value
                    .parse::<i64>()
                    .map_err(|_| "--keep-latest must be an integer".to_string())?;
                keep_latest = normalize_keep_latest(parsed);
            }
            "--pretty" => {
                pretty = true;
            }
            "--integrity-check" => {
                integrity_check = true;
            }
            "--help" | "-h" => {
                return Err(usage());
            }
            unexpected => {
                return Err(format!("unexpected argument: {unexpected}\n{}", usage()));
            }
        }
        index += 1;
    }

    let db_path = db_path.ok_or_else(|| "--db is required".to_string())?;
    Ok(CliArgs {
        db_path,
        keep_latest,
        integrity_check,
        pretty,
    })
}

fn usage() -> String {
    "usage: vibelution-maintenance git-memory --db <agent_brain.db> [--keep-latest <1..500>] [--integrity-check] [--pretty]"
        .to_string()
}

fn normalize_keep_latest(value: i64) -> i64 {
    value.clamp(1, MAX_KEEP_LATEST)
}

fn build_git_memory_report(
    conn: &Connection,
    db_path: &Path,
    args: &CliArgs,
) -> rusqlite::Result<MaintenanceReport> {
    let integrity_check = if args.integrity_check {
        integrity_check(conn)?
    } else {
        "skipped".to_string()
    };
    let tables = TableReport {
        git_working_tree_snapshot: table_stats(
            conn,
            "GitWorkingTreeSnapshot",
            "snapshot_id LIKE 'wt-%'",
        )?,
        git_file_change: table_stats(conn, "GitFileChange", "is_worktree = 1")?,
        git_entity_change: table_stats(conn, "GitEntityChange", "is_worktree = 1")?,
    };
    let prune_dry_run = prune_dry_run(conn, args.keep_latest)?;
    Ok(MaintenanceReport {
        ok: true,
        schema_version: 1,
        tool: "vibelution-maintenance",
        command: "git-memory",
        db_path: db_path.display().to_string(),
        keep_latest: args.keep_latest,
        integrity_check_mode: if args.integrity_check {
            "full"
        } else {
            "skipped"
        },
        integrity_check,
        tables,
        prune_dry_run,
        elapsed_ms: 0,
    })
}

fn integrity_check(conn: &Connection) -> rusqlite::Result<String> {
    conn.query_row("PRAGMA integrity_check", [], |row| row.get::<_, String>(0))
}

fn table_exists(conn: &Connection, table: &str) -> rusqlite::Result<bool> {
    conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?1",
        [table],
        |row| row.get::<_, i64>(0),
    )
    .map(|count| count > 0)
}

fn table_stats(
    conn: &Connection,
    table: &str,
    worktree_where: &str,
) -> rusqlite::Result<TableStats> {
    if !table_exists(conn, table)? {
        return Ok(TableStats {
            exists: false,
            row_count: 0,
            worktree_rows: 0,
        });
    }
    let row_count = count_query(conn, &format!("SELECT COUNT(*) FROM {table}"), &[])?;
    let worktree_rows = count_query(
        conn,
        &format!("SELECT COUNT(*) FROM {table} WHERE {worktree_where}"),
        &[],
    )?;
    Ok(TableStats {
        exists: true,
        row_count,
        worktree_rows,
    })
}

fn prune_dry_run(conn: &Connection, keep_latest: i64) -> rusqlite::Result<PruneDryRun> {
    if !table_exists(conn, "GitWorkingTreeSnapshot")? {
        return Ok(PruneDryRun {
            candidate_snapshots: 0,
            candidate_file_rows: 0,
            candidate_entity_rows: 0,
            sample_snapshot_ids: Vec::new(),
        });
    }

    let candidate_snapshots = count_query(
        conn,
        "WITH prune AS (
            SELECT snapshot_id
            FROM GitWorkingTreeSnapshot
            WHERE snapshot_id LIKE 'wt-%'
            ORDER BY created_at DESC, snapshot_id DESC
            LIMIT -1 OFFSET ?1
        )
        SELECT COUNT(*) FROM prune",
        &[&keep_latest],
    )?;

    let candidate_file_rows = if table_exists(conn, "GitFileChange")? {
        count_query(
            conn,
            "WITH prune AS (
                SELECT snapshot_id
                FROM GitWorkingTreeSnapshot
                WHERE snapshot_id LIKE 'wt-%'
                ORDER BY created_at DESC, snapshot_id DESC
                LIMIT -1 OFFSET ?1
            )
            SELECT COUNT(*)
            FROM GitFileChange
            WHERE is_worktree = 1
              AND commit_sha IN (SELECT snapshot_id FROM prune)",
            &[&keep_latest],
        )?
    } else {
        0
    };

    let candidate_entity_rows = if table_exists(conn, "GitEntityChange")? {
        count_query(
            conn,
            "WITH prune AS (
                SELECT snapshot_id
                FROM GitWorkingTreeSnapshot
                WHERE snapshot_id LIKE 'wt-%'
                ORDER BY created_at DESC, snapshot_id DESC
                LIMIT -1 OFFSET ?1
            )
            SELECT COUNT(*)
            FROM GitEntityChange
            WHERE is_worktree = 1
              AND commit_sha IN (SELECT snapshot_id FROM prune)",
            &[&keep_latest],
        )?
    } else {
        0
    };

    let mut statement = conn.prepare(
        "SELECT snapshot_id
         FROM GitWorkingTreeSnapshot
         WHERE snapshot_id LIKE 'wt-%'
         ORDER BY created_at DESC, snapshot_id DESC
         LIMIT 5 OFFSET ?1",
    )?;
    let sample_snapshot_ids = statement
        .query_map([keep_latest], |row| row.get::<_, String>(0))?
        .collect::<Result<Vec<_>, _>>()?;

    Ok(PruneDryRun {
        candidate_snapshots,
        candidate_file_rows,
        candidate_entity_rows,
        sample_snapshot_ids,
    })
}

fn count_query(
    conn: &Connection,
    sql: &str,
    params: &[&dyn rusqlite::ToSql],
) -> rusqlite::Result<i64> {
    conn.query_row(sql, params, |row| row.get::<_, i64>(0))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clamps_keep_latest_to_existing_python_bounds() {
        assert_eq!(normalize_keep_latest(-10), 1);
        assert_eq!(normalize_keep_latest(0), 1);
        assert_eq!(normalize_keep_latest(42), 42);
        assert_eq!(normalize_keep_latest(900), 500);
    }

    #[test]
    fn reports_prune_candidates_without_mutating_rows() {
        let conn = Connection::open_in_memory().expect("in-memory sqlite opens");
        conn.execute_batch(
            "
            CREATE TABLE GitWorkingTreeSnapshot(
                snapshot_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                base_rev TEXT,
                has_staged INTEGER NOT NULL DEFAULT 0,
                has_unstaged INTEGER NOT NULL DEFAULT 0,
                has_untracked INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE GitFileChange(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_sha TEXT NOT NULL,
                path TEXT NOT NULL,
                change_type TEXT NOT NULL,
                old_path TEXT,
                is_worktree INTEGER NOT NULL DEFAULT 0,
                summary TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE GitEntityChange(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_sha TEXT NOT NULL,
                path TEXT NOT NULL,
                entity_ref TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                change_type TEXT NOT NULL,
                is_worktree INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            ",
        )
        .expect("schema created");
        for index in 0..4 {
            let snapshot_id = format!("wt-test-{index}");
            conn.execute(
                "INSERT INTO GitWorkingTreeSnapshot(snapshot_id, created_at) VALUES (?1, ?2)",
                (&snapshot_id, format!("2026-01-01T00:00:0{index}")),
            )
            .expect("snapshot inserted");
            conn.execute(
                "INSERT INTO GitFileChange(commit_sha, path, change_type, is_worktree, created_at)
                 VALUES (?1, 'sample.py', 'modified', 1, '2026-01-01T00:00:00')",
                [&snapshot_id],
            )
            .expect("file row inserted");
            for entity_index in 0..3 {
                conn.execute(
                    "INSERT INTO GitEntityChange(
                        commit_sha, path, entity_ref, entity_type, change_type, is_worktree, created_at
                     ) VALUES (?1, 'sample.py', ?2, 'function', 'modified', 1, '2026-01-01T00:00:00')",
                    (&snapshot_id, format!("entity_{entity_index}")),
                )
                .expect("entity row inserted");
            }
        }

        let args = CliArgs {
            db_path: PathBuf::from("brain.db"),
            keep_latest: 2,
            integrity_check: false,
            pretty: false,
        };
        let report =
            build_git_memory_report(&conn, Path::new("brain.db"), &args).expect("report builds");

        assert_eq!(report.integrity_check_mode, "skipped");
        assert_eq!(report.integrity_check, "skipped");
        assert_eq!(report.prune_dry_run.candidate_snapshots, 2);
        assert_eq!(report.prune_dry_run.candidate_file_rows, 2);
        assert_eq!(report.prune_dry_run.candidate_entity_rows, 6);
        assert_eq!(
            report.prune_dry_run.sample_snapshot_ids,
            vec!["wt-test-1".to_string(), "wt-test-0".to_string()]
        );
        assert_eq!(
            conn.query_row("SELECT COUNT(*) FROM GitWorkingTreeSnapshot", [], |row| {
                row.get::<_, i64>(0)
            })
            .expect("row count"),
            4
        );
    }
}
