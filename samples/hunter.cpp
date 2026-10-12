// C++17, no external JSON dependency. The small readers below target the fixed
// protocol schema (flat robot objects + integer fields), not arbitrary JSON.
#include <cmath>
#include <iostream>
#include <regex>
#include <stdexcept>
#include <string>

std::string object(const std::string& json, const std::string& key) {
    std::smatch match;
    std::regex pattern("\"" + key + "\"\\s*:\\s*\\{([^}]*)\\}");
    if (!std::regex_search(json, match, pattern)) throw std::runtime_error("Missing robot");
    return match[1];
}

int number(const std::string& json, const std::string& key) {
    std::smatch match;
    std::regex pattern("\"" + key + "\"\\s*:\\s*(-?[0-9]+)");
    if (!std::regex_search(json, match, pattern)) throw std::runtime_error("Missing number");
    return std::stoi(match[1]);
}

int main() {
    std::string line;
    const std::regex playerA("\"player\"\\s*:\\s*\"A\"");
    while (std::getline(std::cin, line)) {
        const auto you = object(line, "you"), enemy = object(line, "enemy");
        const int dx = number(enemy, "x") - number(you, "x");
        const int dy = number(enemy, "y") - number(you, "y");
        const int distance = std::abs(dx) + std::abs(dy);
        const int turn = number(line, "turn");
        if (distance == 1) {
            // Sentinel spends one turn in four waiting; Hunter can exploit it.
            std::cout << (turn % 4 == 0 ? "{\"type\":\"wait\"}" : "{\"type\":\"attack\"}") << std::endl;
        } else if (distance == 2 && std::regex_search(line, playerA)) {
            std::cout << "{\"type\":\"wait\"}" << std::endl;
        } else {
            const auto direction = dx != 0 ? (dx > 0 ? "right" : "left") : (dy > 0 ? "down" : "up");
            std::cout << "{\"type\":\"move\",\"direction\":\"" << direction << "\"}" << std::endl;
        }
    }
    return 0;
}
