#include <iostream>
#include <string>
#include "json.hpp"

using json = nlohmann::json;

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::string line;

    // Read initial config, then signal readiness
    std::getline(std::cin, line);
    std::cout << "READY" << std::endl;

    // Game loop
    while (std::getline(std::cin, line)) {
        auto gs = json::parse(line);
        json commands = json::array();

        if (gs.contains("player") && gs["player"].contains("ships")) {
            for (auto& ship : gs["player"]["ships"]) {
                commands.push_back({
                    {"ship_id", ship["id"].get<int>()},
                    {"acceleration", {{"x", 0.0}, {"y", 0.0}}},
                    {"push", false},
                });
            }
        }

        std::cout << json{{"commands", commands}}.dump() << std::endl;
    }

    return 0;
}
