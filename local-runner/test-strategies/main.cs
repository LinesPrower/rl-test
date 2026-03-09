using System;
using System.Text.Json.Nodes;

class Program
{
    static void Main()
    {
        // Read initial config, then signal readiness
        Console.ReadLine();
        Console.WriteLine("READY");

        // Game loop
        string? line;
        while ((line = Console.ReadLine()) != null)
        {
            var gs = JsonNode.Parse(line)!;
            var ships = gs["player"]?["ships"]?.AsArray() ?? new JsonArray();

            var commands = new JsonArray();
            foreach (var ship in ships)
            {
                commands.Add(new JsonObject
                {
                    ["ship_id"] = ship!["id"]!.GetValue<int>(),
                    ["acceleration"] = new JsonObject { ["x"] = 0.0, ["y"] = 0.0 },
                    ["push"] = false,
                });
            }

            var output = new JsonObject { ["commands"] = commands };
            Console.WriteLine(output.ToJsonString());
        }
    }
}
