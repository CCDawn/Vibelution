use serde_json::Value;
use std::env;
use std::io::{self, Read};
use vibelution_usage_normalize::normalize_usage;

fn main() {
    let mut raw = String::new();
    if let Err(err) = io::stdin().read_to_string(&mut raw) {
        eprintln!("{{\"ok\":false,\"error\":\"stdin_read\",\"message\":{}}}", serde_json::to_string(&err.to_string()).unwrap_or_else(|_| "\"\"".into()));
        std::process::exit(2);
    }
    let value: Value = match serde_json::from_str(raw.trim()) {
        Ok(v) => v,
        Err(err) => {
            eprintln!(
                "{{\"ok\":false,\"error\":\"json_parse\",\"message\":{}}}",
                serde_json::to_string(&err.to_string()).unwrap_or_else(|_| "\"\"".into())
            );
            std::process::exit(2);
        }
    };
    let usage = value
        .get("usage")
        .cloned()
        .unwrap_or(value);
    let normalized = normalize_usage(&usage, "rust");
    let pretty = env::args().any(|a| a == "--pretty");
    let out = if pretty {
        serde_json::to_string_pretty(&normalized)
    } else {
        serde_json::to_string(&normalized)
    };
    match out {
        Ok(s) => println!("{s}"),
        Err(err) => {
            eprintln!("{err}");
            std::process::exit(2);
        }
    }
}
