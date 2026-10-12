// C++17 OTT v2 example. No external headers/libraries.
// This field reader targets the server's documented legal_actions schema,
// not arbitrary JSON. A general JSON parser can be used in stronger bots.
#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <regex>
#include <string>

int main() {
    const std::regex playerPattern("\"player\"\\s*:\\s*\"([AB])\"");
    const std::regex movePattern(
        "\\{\\s*\"action\"\\s*:\\s*\"move\"\\s*,\\s*\"from\"\\s*:\\s*"
        "\\{\\s*\"row\"\\s*:\\s*([0-8])\\s*,\\s*\"col\"\\s*:\\s*([0-8])\\s*\\}\\s*,\\s*"
        "\"to\"\\s*:\\s*\\{\\s*\"row\"\\s*:\\s*([0-8])\\s*,\\s*\"col\"\\s*:\\s*([0-8])\\s*\\}\\s*\\}");
    std::string line;
    while (std::getline(std::cin, line)) {
        // The envelope's player is the first player field; last_move can also
        // contain a player value belonging to the opponent.
        std::smatch role;
        if (!std::regex_search(line, role, playerPattern)) return 1;
        const int goal = role[1] == "A" ? 8 : 0;
        const auto start = line.find("\"legal_actions\"");
        if (start == std::string::npos) return 1;
        const auto legal = line.substr(start);
        int best = std::numeric_limits<int>::max();
        std::string choice;
        for (std::sregex_iterator i(legal.begin(), legal.end(), movePattern), end; i != end; ++i) {
            const int row = std::stoi((*i)[3]), col = std::stoi((*i)[4]);
            const int dr = std::abs(goal - row), dc = std::abs(goal - col);
            const int score = std::max(dr, dc) * 100 + (dr + dc) * 10 + dc;
            if (score < best) { best = score; choice = i->str(); }
        }
        if (choice.empty()) return 1;
        std::cout << choice << std::endl;
    }
}
