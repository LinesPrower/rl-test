import java.io.*;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;

class Main {
    static final ObjectMapper MAPPER = new ObjectMapper();

    public static void main(String[] args) throws Exception {
        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));

        // Read initial config, then signal readiness
        br.readLine();
        System.out.println("READY");
        System.out.flush();

        // Game loop
        String line;
        while ((line = br.readLine()) != null) {
            JsonNode gs = MAPPER.readTree(line);
            JsonNode ships = gs.path("player").path("ships");

            ArrayNode commands = MAPPER.createArrayNode();
            if (ships.isArray()) {
                for (JsonNode ship : ships) {
                    ObjectNode cmd = MAPPER.createObjectNode();
                    cmd.put("ship_id", ship.get("id").asInt());
                    ObjectNode acc = MAPPER.createObjectNode();
                    acc.put("x", 0.0);
                    acc.put("y", 0.0);
                    cmd.set("acceleration", acc);
                    cmd.put("push", false);
                    commands.add(cmd);
                }
            }

            ObjectNode out = MAPPER.createObjectNode();
            out.set("commands", commands);
            System.out.println(MAPPER.writeValueAsString(out));
            System.out.flush();
        }
    }
}
