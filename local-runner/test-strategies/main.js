const readline = require('readline');

const rl = readline.createInterface({ input: process.stdin, terminal: false });

const pending = [];
let waiting = null;

rl.on('line', (line) => {
    if (waiting) {
        const resolve = waiting;
        waiting = null;
        resolve(line);
    } else {
        pending.push(line);
    }
});

rl.on('close', () => {
    if (waiting) waiting(null);
});

function readLine() {
    return new Promise((resolve) => {
        if (pending.length > 0) resolve(pending.shift());
        else waiting = resolve;
    });
}

async function main() {
    // Read initial config, then signal readiness
    await readLine();
    process.stdout.write('READY\n');

    // Game loop
    while (true) {
        const line = await readLine();
        if (line === null) break;

        const gs = JSON.parse(line);
        const ships = gs.player && gs.player.ships ? gs.player.ships : [];

        const commands = ships.map(ship => ({
            ship_id: ship.id,
            acceleration: { x: 0.0, y: 0.0 },
            push: false,
        }));

        process.stdout.write(JSON.stringify({ commands }) + '\n');
    }
}

main();
