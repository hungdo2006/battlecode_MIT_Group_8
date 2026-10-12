import { PIECE_ASSETS } from "./pieceAssets.js";
import { countPiecesByType } from "../src/engine/rules.js";
import { columnName, squareName } from "../src/engine/coordinates.js";
export { squareName } from "../src/engine/coordinates.js";
const typeInfo = (state, id) => state.config.pieceTypes.find((type) => type.id === id);
const typeName = (state, id) => typeInfo(state, id)?.name ?? id;

const els = {};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function setupUI(handlers) {
  Object.assign(els, {
    board: document.querySelector("#board"),
    modeBadge: document.querySelector("#mode-badge"),
    roomCode: document.querySelector("#room-code"),
    roomPanel: document.querySelector("#room-panel"),
    copyRoom: document.querySelector("#copy-room"),
    turn: document.querySelector("#turn-label"),
    status: document.querySelector("#status-text"),
    round: document.querySelector("#round-label"),
    p1Name: document.querySelector("#p1-name"),
    p2Name: document.querySelector("#p2-name"),
    p1Score: document.querySelector("#p1-score"),
    p2Score: document.querySelector("#p2-score"),
    p1Pieces: document.querySelector("#p1-pieces"),
    p2Pieces: document.querySelector("#p2-pieces"),
    p1Seat: document.querySelector("#p1-seat"),
    p2Seat: document.querySelector("#p2-seat"),
    myRole: document.querySelector("#my-role"),
    onlineCount: document.querySelector("#online-count"),
    spectators: document.querySelector("#spectator-count"),
    onlinePanel: document.querySelector("#online-panel"),
    newRound: document.querySelector("#new-round"),
    resetMatch: document.querySelector("#reset-match"),
    leaveSeat: document.querySelector("#leave-seat"),
    home: document.querySelector("#home-button"),
    message: document.querySelector("#toast"),
    lastMove: document.querySelector("#last-move"),
    p1Goal: document.querySelector("#p1-goal"),
    p2Goal: document.querySelector("#p2-goal"),
    ruleSet: document.querySelector("#rule-set-label"),
    captureRules: document.querySelector("#capture-rules"),
  });

  els.copyRoom?.addEventListener("click", handlers.onCopyRoom);
  els.newRound?.addEventListener("click", handlers.onNewRound);
  els.resetMatch?.addEventListener("click", handlers.onResetMatch);
  els.leaveSeat?.addEventListener("click", handlers.onLeaveSeat);
  els.home?.addEventListener("click", () => {
    window.location.href = "./index.html";
  });

  document.querySelector("#claim-p1")?.addEventListener("click", () => handlers.onClaimSeat("P1"));
  document.querySelector("#claim-p2")?.addEventListener("click", () => handlers.onClaimSeat("P2"));

  els.board.addEventListener("click", (event) => {
    const cell = event.target.closest("[data-row][data-col]");
    if (!cell) return;
    handlers.onCellClick({
      row: Number(cell.dataset.row),
      col: Number(cell.dataset.col),
    });
  });
}

function pieceCountsText(state, player) {
  const counts = countPiecesByType(state, player);
  return state.config.pieceTypes.map((type) => `${type.symbol ?? type.name} ${counts[type.id]}`).join("  ");
}

function seatName(seat, fallback) {
  return seat?.name || fallback;
}

function isSameSquare(a, b) {
  return Boolean(a && b && a.row === b.row && a.col === b.col);
}

function legalMoveAt(legalMoves, row, col) {
  return legalMoves.find((move) => move.row === row && move.col === col);
}

function renderBoard(state, selected, legalMoves, myRole, interactive) {
  const { rows, columns } = state.config.board;
  els.board.style.setProperty("--board-rows", rows);
  els.board.style.setProperty("--board-columns", columns);
  els.board.style.aspectRatio = `${columns + 0.45} / ${rows + 0.45}`;
  els.board.setAttribute("aria-label", `${rows} by ${columns} ${state.config.name} board`);
  let html = '<div class="board-corner"></div>';
  for (let col = 0; col < columns; col += 1) html += `<div class="coord file">${columnName(col)}</div>`;

  for (let visualRow = rows - 1; visualRow >= 0; visualRow -= 1) {
    html += `<div class="coord rank">${visualRow + 1}</div>`;

    for (let col = 0; col < columns; col += 1) {
      const piece = state.board[visualRow][col];
      const selectedHere = isSameSquare(selected, { row: visualRow, col });
      const legal = legalMoveAt(legalMoves, visualRow, col);
      const lastFrom = isSameSquare(state.lastMove?.from, { row: visualRow, col });
      const lastTo = isSameSquare(state.lastMove?.to, { row: visualRow, col });
      const hasGoal = state.config.winConditions.includes("reachGoal");
      const goalP1 = hasGoal && isSameSquare(state.config.goals?.P1, { row: visualRow, col });
      const goalP2 = hasGoal && isSameSquare(state.config.goals?.P2, { row: visualRow, col });

      const classes = ["cell", (visualRow + col) % 2 === 0 ? "light" : "dark"];
      if (selectedHere) classes.push("selected");
      if (legal) classes.push(legal.capture ? "legal-capture" : "legal-move");
      if (lastFrom) classes.push("last-from");
      if (lastTo) classes.push("last-to");
      if (goalP1) classes.push("goal", "goal-p1");
      if (goalP2) classes.push("goal", "goal-p2");

      const disabled = !interactive ? " aria-disabled=\"true\"" : "";
      const label = piece
        ? `${piece.owner} ${typeName(state, piece.type)} on ${squareName(visualRow, col)}`
        : `Empty ${squareName(visualRow, col)}`;

      html += `<button class="${classes.join(" ")}" type="button" data-row="${visualRow}" data-col="${col}" aria-label="${escapeHtml(label)}"${disabled}>`;

      if (goalP1) html += '<span class="goal-tag">P1 GOAL</span>';
      if (goalP2) html += '<span class="goal-tag">P2 GOAL</span>';

      if (piece) {
        html += `<span class="piece ${piece.owner.toLowerCase()} ${escapeHtml(piece.type)}" data-piece-id="${escapeHtml(piece.id)}">`;
        const asset = PIECE_ASSETS[piece.owner]?.[piece.type];
        html += `<span class="piece-symbol"${asset ? " hidden" : ""}>${escapeHtml(typeInfo(state, piece.type)?.symbol ?? piece.type.slice(0, 2).toUpperCase())}</span>`;
        if (asset) html += `<img class="piece-image" src="${asset}" alt="" draggable="false" />`;
        html += `<span class="piece-owner">${piece.owner}</span>`;
        html += "</span>";
      }

      html += "</button>";
    }
  }

  els.board.innerHTML = html;
  for (const img of els.board.querySelectorAll("img")) img.addEventListener("error", () => {
    img.hidden = true;
    img.previousElementSibling.hidden = false;
  }, { once: true });
}

function renderLastMove(state) {
  if (!state.lastMove) {
    els.lastMove.textContent = "No moves yet.";
    return;
  }

  const move = state.lastMove;
  const capture = move.captured
    ? `, captured ${move.captured.owner} ${typeName(state, move.captured.type)}`
    : "";
  els.lastMove.textContent = `${move.player}: ${squareName(move.from.row, move.from.col)} -> ${squareName(move.to.row, move.to.col)}${capture}`;
}

export function renderUI(view) {
  const {
    state,
    mode,
    roomCode,
    selected,
    legalMoves,
    myRole,
    onlineCount = 0,
    spectatorCount = 0,
    message = "",
    canInteract = true,
    connected = true,
  } = view;

  const online = mode === "online";
  els.modeBadge.textContent = online ? "ONLINE" : "LOCAL";
  els.modeBadge.className = `badge ${online ? "online" : "local"}`;

  els.roomPanel.hidden = !online;
  els.onlinePanel.hidden = !online;
  if (online) els.roomCode.textContent = roomCode;

  els.p1Name.textContent = seatName(state.players?.P1, "Open seat");
  els.p2Name.textContent = seatName(state.players?.P2, "Open seat");
  els.p1Score.textContent = String(state.scores?.P1 ?? 0);
  els.p2Score.textContent = String(state.scores?.P2 ?? 0);
  els.p1Pieces.textContent = pieceCountsText(state, "P1");
  els.p2Pieces.textContent = pieceCountsText(state, "P2");
  els.round.textContent = `Round ${state.round}`;
  els.ruleSet.textContent = state.config.name;
  for (const player of ["P1", "P2"]) {
    const goal = state.config.goals?.[player];
    els[player === "P1" ? "p1Goal" : "p2Goal"].textContent = state.config.winConditions.includes("reachGoal") && goal
      ? squareName(goal.row, goal.col) : "—";
  }
  els.captureRules.textContent = Object.entries(state.config.beats).flatMap(([id, targets]) =>
    targets.map((target) => `${typeName(state, id)} > ${typeName(state, target)}`)).join(" · ");

  els.turn.textContent = state.winner
    ? `Winner: ${state.winner}`
    : `Turn: ${state.turn}`;

  els.status.textContent = state.winner
    ? state.winReason
    : online && !connected
      ? "Disconnected. Reconnecting to the host…"
    : online && (!state.players?.P1 || !state.players?.P2)
      ? "Waiting for both player seats to be filled."
      : online && (state.players.P1.connected === false || state.players.P2.connected === false)
        ? "Waiting for a player to reconnect."
        : `Move up to ${state.config.movement.maxSteps} step(s) in ${state.config.movement.directions.length} directions.`;

  if (online) {
    els.myRole.textContent = myRole || "Spectator";
    els.onlineCount.textContent = String(onlineCount);
    els.spectators.textContent = String(spectatorCount);

    const claimP1 = document.querySelector("#claim-p1");
    const claimP2 = document.querySelector("#claim-p2");
    claimP1.disabled = !connected || Boolean(state.players?.P1) || Boolean(myRole);
    claimP2.disabled = !connected || Boolean(state.players?.P2) || Boolean(myRole);
    els.p1Seat.textContent = state.players?.P1 ? state.players.P1.connected === false ? "Reconnecting" : "Occupied" : "Available";
    els.p2Seat.textContent = state.players?.P2 ? state.players.P2.connected === false ? "Reconnecting" : "Occupied" : "Available";
    els.leaveSeat.hidden = !myRole;
  }

  els.newRound.hidden = !state.winner;
  els.resetMatch.hidden = online ? !myRole : false;
  els.newRound.disabled = online && (!myRole || !connected);
  els.resetMatch.disabled = online && !connected;

  renderLastMove(state);
  renderBoard(state, selected, legalMoves, myRole, canInteract);

  if (message) showToast(message);
}

let toastTimer = null;
export function showToast(message, kind = "info") {
  if (!els.message || !message) return;
  els.message.textContent = message;
  els.message.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    els.message.className = "toast";
  }, 2600);
}
