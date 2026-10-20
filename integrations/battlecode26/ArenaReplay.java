import battlecode.schema.*;
import com.google.flatbuffers.Table;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.*;
import java.lang.reflect.*;
import java.nio.ByteBuffer;
import java.nio.file.*;
import java.util.*;
import java.util.zip.GZIPInputStream;

/** Converts the official replay, never re-simulates game rules. Raw .bc26 is retained. */
public final class ArenaReplay {
    static final ObjectMapper JSON = new ObjectMapper();
    static final class Raw extends Table {
        Raw(Table table) throws Exception {
            Field position = Table.class.getDeclaredField("bb_pos");
            position.setAccessible(true);
            __reset(position.getInt(table), table.getByteBuffer());
        }
        int actionPosition(int index) {
            int offset = __offset(26); // Turn.actions, pinned official schema.
            if (offset == 0) throw new IllegalArgumentException("Missing actions vector");
            int element = __vector(offset) + index * 4;
            return element + bb.getInt(element);
        }
    }
    static Map<String,Object> fields(Object object) throws Exception {
        Map<String,Object> result = new LinkedHashMap<>();
        for (Method method : object.getClass().getDeclaredMethods()) {
            Class<?> type = method.getReturnType();
            if (!Modifier.isStatic(method.getModifiers()) && method.getParameterCount() == 0
                && (type.isPrimitive() || type == String.class) && !method.getName().startsWith("__"))
                result.put(method.getName(), method.invoke(object));
        }
        return result;
    }
    static int number(Map<String,Object> values, String key) {
        return ((Number) values.getOrDefault(key, 0)).intValue();
    }
    static Map<String,Object> spawn(SpawnAction spawn) throws Exception { return fields(spawn); }
    static List<Object> snapshot(Map<Integer,Map<String,Object>> units) {
        List<Object> result = new ArrayList<>();
        for (Map<String,Object> unit : units.values()) result.add(new LinkedHashMap<>(unit));
        return result;
    }
    public static void main(String[] args) throws Exception {
        byte[] bytes;
        try (InputStream input = new GZIPInputStream(Files.newInputStream(Path.of(args[0])))) {
            bytes = input.readNBytes(64 * 1024 * 1024 + 1);
        }
        if (bytes.length > 64 * 1024 * 1024) throw new IOException("Replay exceeds decoded limit");
        GameWrapper game = GameWrapper.getRootAsGameWrapper(ByteBuffer.wrap(bytes));
        List<Map<String,Object>> frames = new ArrayList<>();
        Map<Integer,Map<String,Object>> units = new LinkedHashMap<>();
        Map<String,Object> board = new LinkedHashMap<>(), outcome = null;
        Map<Integer,Integer> baseHealth = new HashMap<>();
        int maxRounds = 0;
        for (int i = 0; i < game.eventsLength(); i++) {
            EventWrapper event = game.events(i);
            if (event.eType() == Event.GameHeader) {
                GameHeader header = (GameHeader) event.e(new GameHeader());
                for (int j = 0; j < header.robotTypeMetadataLength(); j++) {
                    RobotTypeMetadata type = header.robotTypeMetadata(j);
                    baseHealth.put((int) type.type(), type.baseHealth());
                }
            } else if (event.eType() == Event.MatchHeader) {
                if (!frames.isEmpty()) throw new IOException("Expected exactly one match");
                MatchHeader header = (MatchHeader) event.e(new MatchHeader());
                GameMap map = header.map(); maxRounds = header.maxRounds();
                board.put("name", map.name()); board.put("width", map.size().x()); board.put("height", map.size().y());
                List<Integer> walls = new ArrayList<>(), dirt = new ArrayList<>(), cheese = new ArrayList<>();
                for (int j = 0; j < map.wallsLength(); j++) if (map.walls(j)) walls.add(j);
                for (int j = 0; j < map.dirtLength(); j++) if (map.dirt(j)) dirt.add(j);
                for (int j = 0; j < map.cheeseLength(); j++) if (map.cheese(j) > 0) cheese.add(j);
                board.put("walls", walls); board.put("initial_dirt", dirt); board.put("initial_cheese", cheese);
                for (int j = 0; j < map.initialBodies().spawnActionsLength(); j++) {
                    SpawnAction body = map.initialBodies().spawnActions(j);
                    Map<String,Object> unit = spawn(body); unit.put("health", baseHealth.getOrDefault((int)body.robotType(), 0));
                    units.put(body.id(), unit);
                }
                Map<String,Object> frame = new LinkedHashMap<>();
                frame.put("game_id", "battlecode26"); frame.put("turn", 0); frame.put("board", board);
                frame.put("units", snapshot(units)); frame.put("events", List.of()); frame.put("result", null);
                frames.add(frame);
            } else if (event.eType() == Event.Round) {
                Round round = (Round) event.e(new Round());
                List<Object> events = new ArrayList<>();
                for (int j = 0; j < round.turnsLength(); j++) {
                    Turn turn = round.turns(j);
                    Map<String,Object> unit = units.get(turn.robotId());
                    if (unit != null) {
                        unit.put("x", turn.x()); unit.put("y", turn.y()); unit.put("dir", turn.dir());
                        unit.put("health", turn.health()); unit.put("cheese", turn.cheese());
                    }
                    Raw rawTurn = new Raw(turn);
                    for (int k = 0; k < turn.actionsLength(); k++) {
                        String name = Action.name(turn.actionsType(k));
                        Class<?> type = Class.forName("battlecode.schema." + name);
                        // Official unions contain both Structs and Tables. Calling
                        // Turn.actions(Table, k) on a Struct reads its bytes as a
                        // vtable and can fail for ordinary movement actions.
                        Object action = type.getMethod("__assign", int.class, ByteBuffer.class)
                            .invoke(type.getConstructor().newInstance(), rawTurn.actionPosition(k), turn.getByteBuffer());
                        Map<String,Object> values = fields(action);
                        values.put("type", name); values.put("actor", turn.robotId()); events.add(values);
                        if (name.equals("SpawnAction")) {
                            values = new LinkedHashMap<>(values); values.remove("type"); values.remove("actor");
                            values.put("health", baseHealth.getOrDefault(number(values,"robotType"), 0));
                            units.put(number(values,"id"), values);
                        } else if (name.equals("DieAction")) units.remove(number(values,"id"));
                    }
                }
                for (int j = 0; j < round.diedIdsLength(); j++) units.remove(round.diedIds(j));
                Map<String,Object> scores = new LinkedHashMap<>();
                for (int j = 0; j < round.teamIdsLength(); j++) {
                    // The pinned engine packs global cheese into this field:
                    // ratKings + 10 * cheese (GameWorld.processEndOfRound).
                    int combined = round.teamAliveRatKings(j);
                    scores.put(round.teamIds(j) == 1 ? "A" : "B", Map.of(
                        "kings", combined % 10, "rats", round.teamAliveBabyRats(j),
                        "cheese", combined / 10, "cheese_transferred", round.teamCheeseTransferred(j),
                        "cat_damage", round.teamCatDamage(j)));
                }
                Map<String,Object> frame = new LinkedHashMap<>();
                frame.put("game_id", "battlecode26"); frame.put("turn", round.roundId()); frame.put("units", snapshot(units));
                frame.put("events", events); frame.put("scores", scores); frame.put("result", null); frames.add(frame);
            } else if (event.eType() == Event.MatchFooter) {
                MatchFooter footer = (MatchFooter) event.e(new MatchFooter()); outcome = new LinkedHashMap<>();
                outcome.put("winner", footer.winner() == 1 ? "A" : footer.winner() == 2 ? "B" : null);
                outcome.put("reason", WinType.name(footer.winType())); outcome.put("turn", footer.totalRounds());
            }
        }
        if (outcome == null || frames.isEmpty()) throw new IOException("Incomplete official replay");
        frames.get(frames.size()-1).put("result", outcome);
        JSON.writeValue(Path.of(args[1]).toFile(), Map.of("version", 1, "engine_commit", "103abf6b67a2cf544e6344dddef9318af9ae9193",
            "max_rounds", maxRounds, "board", board, "frames", frames, "result", outcome));
    }
}
