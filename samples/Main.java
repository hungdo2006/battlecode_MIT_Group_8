// JDK 8+; no Maven/Gradle or JSON library. Readers target the fixed protocol
// schema, rather than implementing a general-purpose JSON parser.
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Main {
    static String object(String json, String key) {
        Matcher match = Pattern.compile("\"" + key + "\"\\s*:\\s*\\{([^}]*)\\}").matcher(json);
        if (!match.find()) throw new IllegalArgumentException("Missing robot");
        return match.group(1);
    }

    static int number(String json, String key) {
        Matcher match = Pattern.compile("\"" + key + "\"\\s*:\\s*(-?[0-9]+)").matcher(json);
        if (!match.find()) throw new IllegalArgumentException("Missing number");
        return Integer.parseInt(match.group(1));
    }

    public static void main(String[] args) throws Exception {
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        Pattern playerA = Pattern.compile("\"player\"\\s*:\\s*\"A\"");
        while ((line = input.readLine()) != null) {
            String you = object(line, "you"), enemy = object(line, "enemy");
            int dx = number(enemy, "x") - number(you, "x");
            int dy = number(enemy, "y") - number(you, "y");
            int distance = Math.abs(dx) + Math.abs(dy);
            int turn = number(line, "turn");
            if (distance == 1) {
                // Phantom recalibrates once every five turns.
                System.out.println(turn % 5 == 0 ? "{\"type\":\"wait\"}" : "{\"type\":\"attack\"}");
            } else if (distance == 2 && playerA.matcher(line).find()) {
                System.out.println("{\"type\":\"wait\"}");
            } else {
                String direction = dx != 0 ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up");
                System.out.println("{\"type\":\"move\",\"direction\":\"" + direction + "\"}");
            }
            System.out.flush();
        }
    }
}
