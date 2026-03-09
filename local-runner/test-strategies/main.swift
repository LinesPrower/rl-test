import Foundation

// Read initial config, then signal readiness
_ = Swift.readLine()
print("READY")
fflush(stdout)

// Game loop
while let line = Swift.readLine() {
    guard
        let data = line.data(using: .utf8),
        let gs = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
        let player = gs["player"] as? [String: Any],
        let ships = player["ships"] as? [[String: Any]]
    else {
        print("{\"commands\":[]}")
        fflush(stdout)
        continue
    }

    var commands: [[String: Any]] = []
    for ship in ships {
        guard let id = ship["id"] as? Int else { continue }
        commands.append([
            "ship_id": id,
            "acceleration": ["x": 0.0, "y": 0.0],
            "push": false,
        ])
    }

    let output: [String: Any] = ["commands": commands]
    if let outData = try? JSONSerialization.data(withJSONObject: output),
       let outStr = String(data: outData, encoding: .utf8) {
        print(outStr)
    }
    fflush(stdout)
}
