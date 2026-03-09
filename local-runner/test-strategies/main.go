package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

type Vec2 struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
}

type Ship struct {
	ID int `json:"id"`
}

type Player struct {
	Ships []Ship `json:"ships"`
}

type GameState struct {
	Player Player `json:"player"`
}

type Command struct {
	ShipID       int  `json:"ship_id"`
	Acceleration Vec2 `json:"acceleration"`
	Push         bool `json:"push"`
}

type Output struct {
	Commands []Command `json:"commands"`
}

func main() {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 1024*1024), 1024*1024)

	// Read initial config, then signal readiness
	scanner.Scan()
	fmt.Println("READY")
	os.Stdout.Sync()

	// Game loop
	for scanner.Scan() {
		line := scanner.Text()
		var gs GameState
		if err := json.Unmarshal([]byte(line), &gs); err != nil {
			continue
		}

		commands := make([]Command, 0, len(gs.Player.Ships))
		for _, ship := range gs.Player.Ships {
			commands = append(commands, Command{
				ShipID:       ship.ID,
				Acceleration: Vec2{X: 0, Y: 0},
				Push:         false,
			})
		}

		data, _ := json.Marshal(Output{Commands: commands})
		fmt.Println(string(data))
		os.Stdout.Sync()
	}
}
