use std::io::{self, BufRead, Write};
use serde_json::{json, Value};

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let mut lines = stdin.lock().lines();

    // Read initial config, then signal readiness
    lines.next();
    writeln!(out, "READY").unwrap();
    out.flush().unwrap();

    // Game loop
    for line in lines {
        let line = line.unwrap();
        let gs: Value = serde_json::from_str(&line).unwrap();

        let empty = vec![];
        let ships = gs["player"]["ships"].as_array().unwrap_or(&empty);

        let commands: Vec<Value> = ships.iter().map(|ship| {
            json!({
                "ship_id": ship["id"].as_i64().unwrap_or(0),
                "acceleration": { "x": 0.0, "y": 0.0 },
                "push": false,
            })
        }).collect();

        writeln!(out, "{}", json!({ "commands": commands })).unwrap();
        out.flush().unwrap();
    }
}
