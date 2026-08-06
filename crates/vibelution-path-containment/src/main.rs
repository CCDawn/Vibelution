use serde::Deserialize;
use serde_json::json;
use std::io::{self, Read};
use vibelution_path_containment::contain_path;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Request {
    project_root: String,
    candidate: String,
}

fn main() {
    let mut raw = String::new();
    if let Err(err) = io::stdin().read_to_string(&mut raw) {
        eprintln!("{}", json!({"ok": false, "error": "stdin_read", "message": err.to_string()}));
        std::process::exit(2);
    }
    let req: Request = match serde_json::from_str(raw.trim()) {
        Ok(v) => v,
        Err(err) => {
            eprintln!("{}", json!({"ok": false, "error": "json_parse", "message": err.to_string()}));
            std::process::exit(2);
        }
    };
    let result = contain_path(&req.project_root, &req.candidate, "rust");
    match serde_json::to_string(&result) {
        Ok(s) => println!("{s}"),
        Err(err) => {
            eprintln!("{err}");
            std::process::exit(2);
        }
    }
}
