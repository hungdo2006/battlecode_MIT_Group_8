// Execute the shipped results script against a small DOM contract in Node.
// Browser acceptance remains a separate check_offline_results_ui.py gate.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.textContent = ""; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  addEventListener() {}
  querySelector(tag) {
    return this.children.find(n => n.tag === tag || n.querySelector(tag)) || null;
  }
  set innerHTML(_) { throw new Error("Public results must use text nodes"); }
}
const nodes = Object.fromEntries(["results", "status", "reload"].map(id => [id, new Element("div")]));
const hostileName = '<img src=x onerror="globalThis.injected=true">';
const tournament = {
  name: "Adjudicated QA final", source: "qa-school", game_id: "robot_battle", format: "single_elimination",
  standings: [], groups: [],
  matches: [{round: 1, team_a: hostileName, team_b: "QA Beta", winner: null}],
  bracket: [
    {round: 1, status: "COMPLETED", team_a: hostileName, team_b: "QA Beta", winner: "QA Beta"},
    {round: 2, status: "BYE", team_a: "QA Beta", team_b: null, winner: "QA Beta"},
    {round: 3, status: "SKIPPED", team_a: null, team_b: null, winner: null},
  ],
};
const html = fs.readFileSync(path.join(__dirname, "../frontend/results.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const context = {
  document: {getElementById: id => nodes[id], createElement: tag => new Element(tag)},
  fetch: async (url, options) => {
    assert.equal(url, "/api/public/standings");
    assert.equal(options.credentials, "omit");
    assert.equal(options.cache, "no-store");
    return {ok: true, json: async () => ({tournaments: [], offline_tournaments: [tournament]})};
  },
};
vm.runInNewContext(script, context);
setImmediate(() => {
  const flatten = node => [node.textContent, ...node.children.map(flatten)].join("\n");
  const text = flatten(nodes.results);
  assert.match(text, /Nhánh đấu offline/);
  assert.match(text, /Thắng: QA Beta/);
  assert.match(text, /Miễn đấu: QA Beta/);
  assert.match(text, /Không cần thi đấu/);
  assert.match(text, /Kết quả 1 trận/);
  assert.match(text, /Hòa/);
  assert.ok(text.includes(hostileName));
  assert.equal(context.injected, undefined);
  console.log("PASS public results: adjudicated bracket, BYE, skipped reset, draw history, text-only names");
});
