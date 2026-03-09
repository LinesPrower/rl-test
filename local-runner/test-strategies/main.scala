import io.circe.Json
import io.circe.parser.parse
import io.circe.syntax.EncoderOps

object Main {
  private def buildZeroCommandsFromInput(line: String): Json = {
    val commands = parse(line).toOption
      .flatMap(_.hcursor.downField("player").downField("ships").as[Vector[Json]].toOption)
      .getOrElse(Vector.empty)
      .flatMap { ship =>
        ship.hcursor.get[Int]("id").toOption.map { shipId =>
          Json.obj(
            "ship_id" -> shipId.asJson,
            "acceleration" -> Json.obj(
              "x" -> 0.0.asJson,
              "y" -> 0.0.asJson
            ),
            "push" -> false.asJson
          )
        }
      }

    Json.obj("commands" -> Json.fromValues(commands))
  }

  private def warmUpJsonPath(): Unit = {
    // Move class loading / first-call initialization to startup instead of turn 0.
    val warmupInput = """{"player":{"ships":[{"id":0}]}}"""
    buildZeroCommandsFromInput(warmupInput).noSpaces
  }

  def main(args: Array[String]): Unit = {
    val stdin = scala.io.Source.stdin.getLines()

    // Read initial config, then signal readiness
    if (!stdin.hasNext) return
    stdin.next()
    warmUpJsonPath()
    println("READY")
    Console.out.flush()

    // Game loop
    while (stdin.hasNext) {
      val line = stdin.next()

      val output = buildZeroCommandsFromInput(line)
      println(output.noSpaces)
      Console.out.flush()
    }
  }
}
