//! Lexical path containment under a project root (no required filesystem existence).
//!
//! Rejects `..` escapes, absolute paths outside root, empty/null-byte inputs.
//! Windows comparisons are case-insensitive on the resolved strings.

use serde::{Deserialize, Serialize};
use std::path::{Component, Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ContainmentResult {
    pub ok: bool,
    pub root: String,
    pub candidate: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolved: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub relative: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    pub engine: String,
}

fn has_null_byte(s: &str) -> bool {
    s.bytes().any(|b| b == 0)
}

/// Collapse `.` / `..` without requiring the path to exist.
pub fn lexical_normalize(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Prefix(prefix) => out.push(prefix.as_os_str()),
            Component::RootDir => out.push(component.as_os_str()),
            Component::CurDir => {}
            Component::ParentDir => {
                if !out.pop() {
                    // Keep leading `..` only when path is still relative without root.
                    if out.as_os_str().is_empty() {
                        out.push("..");
                    }
                } else if out.as_os_str().is_empty() {
                    // popped last segment of relative path
                }
            }
            Component::Normal(seg) => out.push(seg),
        }
    }
    if out.as_os_str().is_empty() {
        PathBuf::from(".")
    } else {
        out
    }
}

fn make_absolute(root: &Path, candidate: &Path) -> PathBuf {
    if candidate.is_absolute() {
        lexical_normalize(candidate)
    } else {
        lexical_normalize(&root.join(candidate))
    }
}

#[cfg(windows)]
fn path_key(path: &Path) -> String {
    path.to_string_lossy().replace('/', "\\").to_lowercase()
}

#[cfg(not(windows))]
fn path_key(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

fn is_same_or_child(child: &Path, parent: &Path) -> bool {
    let child_key = path_key(child);
    let parent_key = path_key(parent);
    if child_key == parent_key {
        return true;
    }
    let sep = if cfg!(windows) { '\\' } else { '/' };
    let prefix = if parent_key.ends_with(sep) {
        parent_key.clone()
    } else {
        format!("{parent_key}{sep}")
    };
    child_key.starts_with(&prefix)
}

/// Contain `candidate` under `project_root` (both may be relative; root is resolved against cwd).
pub fn contain_path(project_root: &str, candidate: &str, engine: &str) -> ContainmentResult {
    let root_raw = project_root.trim();
    let cand_raw = candidate.trim();
    if root_raw.is_empty() {
        return ContainmentResult {
            ok: false,
            root: project_root.to_string(),
            candidate: candidate.to_string(),
            resolved: None,
            relative: None,
            error: Some("empty_root".into()),
            engine: engine.into(),
        };
    }
    if cand_raw.is_empty() {
        return ContainmentResult {
            ok: false,
            root: project_root.to_string(),
            candidate: candidate.to_string(),
            resolved: None,
            relative: None,
            error: Some("empty_candidate".into()),
            engine: engine.into(),
        };
    }
    if has_null_byte(root_raw) || has_null_byte(cand_raw) {
        return ContainmentResult {
            ok: false,
            root: project_root.to_string(),
            candidate: candidate.to_string(),
            resolved: None,
            relative: None,
            error: Some("null_byte".into()),
            engine: engine.into(),
        };
    }

    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let root_path = {
        let p = Path::new(root_raw);
        if p.is_absolute() {
            lexical_normalize(p)
        } else {
            lexical_normalize(&cwd.join(p))
        }
    };
    let resolved = make_absolute(&root_path, Path::new(cand_raw));

    if !is_same_or_child(&resolved, &root_path) {
        return ContainmentResult {
            ok: false,
            root: root_path.to_string_lossy().into_owned(),
            candidate: candidate.to_string(),
            resolved: Some(resolved.to_string_lossy().into_owned()),
            relative: None,
            error: Some("outside_root".into()),
            engine: engine.into(),
        };
    }

    let relative = if path_key(&resolved) == path_key(&root_path) {
        String::new()
    } else {
        resolved
            .strip_prefix(&root_path)
            .map(|p| p.to_string_lossy().replace('\\', "/"))
            .unwrap_or_default()
    };

    ContainmentResult {
        ok: true,
        root: root_path.to_string_lossy().into_owned(),
        candidate: candidate.to_string(),
        resolved: Some(resolved.to_string_lossy().into_owned()),
        relative: Some(relative),
        error: None,
        engine: engine.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn relative_child_ok() {
        let root = std::env::temp_dir().join("vibelution_path_root_ok");
        let _ = fs::create_dir_all(&root);
        let r = contain_path(root.to_str().unwrap(), "workspace/a.txt", "rust");
        assert!(r.ok, "{r:?}");
        assert_eq!(r.relative.as_deref(), Some("workspace/a.txt"));
    }

    #[test]
    fn parent_escape_rejected() {
        let root = std::env::temp_dir().join("vibelution_path_root_escape");
        let _ = fs::create_dir_all(&root);
        let r = contain_path(root.to_str().unwrap(), "../secret.txt", "rust");
        assert!(!r.ok);
        assert_eq!(r.error.as_deref(), Some("outside_root"));
    }

    #[test]
    fn nested_dotdot_stays_inside() {
        let root = std::env::temp_dir().join("vibelution_path_root_nested");
        let _ = fs::create_dir_all(&root);
        let r = contain_path(root.to_str().unwrap(), "a/b/../../c.txt", "rust");
        assert!(r.ok, "{r:?}");
        assert_eq!(r.relative.as_deref(), Some("c.txt"));
    }

    #[test]
    fn absolute_outside_rejected() {
        let root = std::env::temp_dir().join("vibelution_path_root_abs");
        let _ = fs::create_dir_all(&root);
        let outside = std::env::temp_dir().join("vibelution_path_outside_file.txt");
        let r = contain_path(root.to_str().unwrap(), outside.to_str().unwrap(), "rust");
        assert!(!r.ok);
        assert_eq!(r.error.as_deref(), Some("outside_root"));
    }
}
