// JDK 8+ OTT v2 sample. Reader targets server legal_actions, not arbitrary JSON.
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Main {
    public static void main(String[] args) throws Exception {
        Pattern playerPattern = Pattern.compile("\"player\"\\s*:\\s*\"([AB])\"");
        Pattern movePattern = Pattern.compile(
            "\\{\\s*\"action\"\\s*:\\s*\"move\"\\s*,\\s*\"from\"\\s*:\\s*" +
            "\\{\\s*\"row\"\\s*:\\s*([0-8])\\s*,\\s*\"col\"\\s*:\\s*([0-8])\\s*\\}\\s*,\\s*" +
            "\"to\"\\s*:\\s*\\{\\s*\"row\"\\s*:\\s*([0-8])\\s*,\\s*\"col\"\\s*:\\s*([0-8])\\s*\\}\\s*\\}");
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line = input.readLine()) != null) {
            Matcher role = playerPattern.matcher(line);
            if (!role.find()) throw new IllegalArgumentException("Missing player");
            int goal = role.group(1).equals("A") ? 8 : 0;
            int start = line.indexOf("\"legal_actions\"");
            if (start < 0) throw new IllegalArgumentException("Missing legal_actions");
            Matcher move = movePattern.matcher(line.substring(start));
            String choice = null;
            int best = Integer.MAX_VALUE;
            while (move.find()) {
                int row = Integer.parseInt(move.group(3)), col = Integer.parseInt(move.group(4));
                int dr = Math.abs(goal - row), dc = Math.abs(goal - col);
                int score = Math.max(dr, dc) * 100 + (dr + dc) * 10 + dr;
                if (score < best) { best = score; choice = move.group(); }
            }
            if (choice == null) throw new IllegalStateException("No legal action");
            System.out.println(choice);
            System.out.flush();
        }
    }
}
