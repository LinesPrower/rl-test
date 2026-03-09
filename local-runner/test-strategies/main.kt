import kotlinx.serialization.json.*

fun main() {
    val reader = System.`in`.bufferedReader()

    // Read initial config, then signal readiness
    reader.readLine()
    println("READY")
    System.out.flush()

    // Game loop
    var line: String?
    while (reader.readLine().also { line = it } != null) {
        val gs = Json.parseToJsonElement(line!!).jsonObject
        val ships = gs["player"]?.jsonObject?.get("ships")?.jsonArray ?: JsonArray(emptyList())

        val commands = buildJsonArray {
            for (ship in ships) {
                addJsonObject {
                    put("ship_id", ship.jsonObject["id"]!!.jsonPrimitive.int)
                    putJsonObject("acceleration") {
                        put("x", 0.0)
                        put("y", 0.0)
                    }
                    put("push", false)
                }
            }
        }

        val out = buildJsonObject { put("commands", commands) }
        println(Json.encodeToString(JsonObject.serializer(), out))
        System.out.flush()
    }
}
}
