"use strict";
// Canvas renderers receive saved JSON state. They never execute bot code.
// Cyan and pink match the UI player tokens. Labels, distinct body fills and
// piece shapes keep each side identifiable without relying on color alone.
const ARENA_COLORS = { A: "#5de4ed", B: "#f197d9" };
const colors = ARENA_COLORS;
const PIECE_NAMES = { rock: "Búa", paper: "Bao", scissors: "Kéo" };
const squareName = position => `${String.fromCharCode(97 + position.col)}${position.row + 1}`;

function drawBattlecode(ctx, canvas, frame) {
  const w=canvas.width,h=canvas.height,board=frame.board;
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#0d101c";ctx.fillRect(0,0,w,h);
  if (!board?.width) {
    ctx.fillStyle="#9ca9c4";ctx.font="16px Inter,sans-serif";ctx.textAlign="center";
    ctx.fillText("Battlecode 2026 · Engine chính thức",w/2,h/2);return;
  }
  const cell=Math.min((w-140)/board.width,(h-100)/board.height),gx=(w-cell*board.width)/2,gy=(h-cell*board.height)/2;
  const position=index=>[gx+(index%board.width)*cell,gy+(board.height-1-Math.floor(index/board.width))*cell];
  ctx.fillStyle="#121827";ctx.fillRect(gx,gy,cell*board.width,cell*board.height);
  ctx.strokeStyle="#171c2c";ctx.lineWidth=.6;
  for(let x=0;x<=board.width;x++){ctx.beginPath();ctx.moveTo(gx+x*cell,gy);ctx.lineTo(gx+x*cell,gy+cell*board.height);ctx.stroke();}
  for(let y=0;y<=board.height;y++){ctx.beginPath();ctx.moveTo(gx,gy+y*cell);ctx.lineTo(gx+cell*board.width,gy+y*cell);ctx.stroke();}
  for(const [indices,color] of [[board.walls,"#727c9e"],[frame.terrain?.dirt||board.initial_dirt,"#3d4862"]]) {
    ctx.fillStyle=color;for(const index of indices||[]){const[x,y]=position(index);ctx.fillRect(x+.5,y+.5,cell-1,cell-1);}
  }
  ctx.fillStyle="#f3d377";
  for(const index of frame.terrain?.cheese||board.initial_cheese||[]){const[x,y]=position(index);ctx.fillRect(x+cell*.35,y+cell*.35,cell*.3,cell*.3);}
  for(const[index]of frame.terrain?.traps||[]){const[x,y]=position(index);ctx.strokeStyle="#ff95aa";ctx.strokeRect(x+cell*.2,y+cell*.2,cell*.6,cell*.6);}
  for(const unit of frame.units||[]){
    const x=gx+(unit.x+.5)*cell,y=gy+(board.height-unit.y-.5)*cell,king=unit.robotType===2,cat=unit.robotType===3;
    const radius=cell*(king?.65:cat?.55:.34);
    ctx.beginPath();ctx.arc(x,y,radius,0,Math.PI*2);ctx.fillStyle=unit.team===1?colors.A:unit.team===2?colors.B:"#8794b2";ctx.fill();
    ctx.strokeStyle="#e8e7ff";ctx.lineWidth=king?2:1;ctx.stroke();
    if(cell>=10){ctx.fillStyle="#0d101c";ctx.font=`600 ${Math.max(7,cell*.5)}px Inter,sans-serif`;ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText(king?"K":cat?"C":"R",x,y);}
  }
  ctx.textBaseline="alphabetic";ctx.textAlign="center";ctx.font="11px Inter,sans-serif";ctx.fillStyle="#9ca9c4";
  ctx.fillText("K · Rat King    R · Rat    C · Cat    A · cyan    B · hồng",w/2,h-18);
}
function polygon(ctx, points, fill, stroke = null, width = 1) {
  ctx.beginPath();
  points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  ctx.closePath();
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.stroke(); }
}

function drawRobot(ctx, x, y, size, player, hp, maximum, time, isHit) {
  const color = colors[player];
  const solid = player === "A";
  const armor = solid ? "#153a47" : "#f197d9";
  const detail = solid ? "#205c6c" : "#b95c9c";
  const ink = solid ? "#a8f7ff" : "#32182e";
  ctx.save();
  ctx.translate(x, y);
  const scale = size / 60;
  ctx.scale(scale, scale);
  ctx.globalAlpha = hp <= 0 ? 0.28 : 1;
  ctx.fillStyle = "#00000040";
  ctx.beginPath(); ctx.ellipse(0, 22, 28, 8, 0, 0, Math.PI * 2); ctx.fill();
  if (hp > 0) {
    ctx.strokeStyle = color + "55"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.ellipse(0, 22, 32, 10, 0, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.shadowBlur = 0;
  polygon(ctx, [[-20, 8], [-7, 8], [-8, 24], [-25, 24]], detail, color);
  polygon(ctx, [[7, 8], [20, 8], [25, 24], [8, 24]], detail, color);
  polygon(ctx, [[-24, -17], [-15, -12], [-17, 7], [-29, 7], [-31, -8]], armor, color);
  polygon(ctx, [[24, -17], [15, -12], [17, 7], [29, 7], [31, -8]], armor, color);
  polygon(ctx, [[-15, -18], [15, -18], [21, -8], [17, 12], [-17, 12], [-21, -8]], isHit ? "#3d4862" : armor, color, 1.3);
  ctx.shadowBlur = 0;
  ctx.fillStyle = detail; ctx.fillRect(-9, -10, 18, 13);
  ctx.strokeStyle = color; ctx.strokeRect(-9, -10, 18, 13);
  ctx.fillStyle = ink; ctx.fillRect(-3, -7, 6, 7);
  polygon(ctx, [[-12, -38], [12, -38], [17, -30], [11, -20], [-11, -20], [-17, -30]], armor, color, 1.3);
  ctx.shadowBlur = 0; ctx.shadowColor = color;
  ctx.fillStyle = ink; ctx.fillRect(-10, -32, 20, 5);
  ctx.shadowBlur = 0;
  ctx.strokeStyle = color; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, -38); ctx.lineTo(0, -45); ctx.stroke();
  ctx.fillStyle = color; ctx.fillRect(-2, -47, 4, 3);
  ctx.fillStyle = "#3d4862"; ctx.fillRect(-24, 32, 48, 3);
  ctx.fillStyle = color; ctx.fillRect(-24, 32, 48 * Math.max(0, hp / maximum), 3);
  ctx.font = "11px Consolas, monospace"; ctx.textAlign = "center";
  ctx.fillStyle = color; ctx.fillText(`ROBOT ${player}`, 0, 48);
  ctx.restore();
}

function drawRobotArena(ctx, canvas, frame, transition, time, reducedMotion) {
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0d101c"; ctx.fillRect(0, 0, w, h);
  const n = frame.rules.map_size;
  const gridSize = Math.min(h - 98, w - 150);
  const cell = gridSize / n;
  const gx = (w - gridSize) / 2, gy = (h - gridSize) / 2;
  ctx.strokeStyle = "#293248"; ctx.lineWidth = 1;
  for (let i = 0; i <= n; i++) {
    ctx.beginPath(); ctx.moveTo(gx + i * cell, gy); ctx.lineTo(gx + i * cell, gy + gridSize); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(gx, gy + i * cell); ctx.lineTo(gx + gridSize, gy + i * cell); ctx.stroke();
  }
  // Solid, quiet board frame; coordinate and movement geometry is unchanged.
  ctx.strokeStyle = "#8794b2"; ctx.lineWidth = 1;
  ctx.strokeRect(gx, gy, gridSize, gridSize);
  ctx.font = "11px Consolas, monospace"; ctx.textAlign = "center"; ctx.fillStyle = "#9ca9c4";
  for (let i = 0; i < n; i++) {
    ctx.fillText(String(i).padStart(2, "0"), gx + (i + .5) * cell, gy - 12);
    ctx.fillText(String(i).padStart(2, "0"), gx - 18, gy + (i + .5) * cell + 3);
  }
  // RAF timestamps can precede performance.now() called during this frame.
  // Clamp both ends so a fresh attack never gives Canvas a negative radius.
  const t = !transition || !transition.duration || reducedMotion ? 1 : Math.max(0, Math.min(1, (time - transition.started) / transition.duration));
  const ease = t * t * (3 - 2 * t);
  const positions = {};
  for (const player of ["A", "B"]) {
    const current = frame.robots[player], previous = transition?.from.robots[player] || current;
    positions[player] = { x: gx + (previous.x + (current.x - previous.x) * ease + .5) * cell,
                          y: gy + (previous.y + (current.y - previous.y) * ease + .5) * cell };
    const pos = positions[player];
    ctx.fillStyle = colors[player] + "0b";
    ctx.fillRect(gx + current.x * cell + 1, gy + current.y * cell + 1, cell - 2, cell - 2);
    ctx.strokeStyle = colors[player] + "44"; ctx.lineWidth = 1;
    ctx.strokeRect(gx + current.x * cell + 2, gy + current.y * cell + 2, cell - 4, cell - 4);
    const hit = frame.events.some(event => event.type === "attack" && event.target === player && event.hit) && t < 1;
    drawRobot(ctx, pos.x, pos.y - cell * .06, Math.max(22, Math.min(60, cell * .91)), player, current.hp, frame.rules.initial_hp, time, hit);
  }
  if (transition && t < 1 && !reducedMotion) {
    for (const event of frame.events.filter(event => event.type === "attack")) {
      const start = positions[event.player], target = positions[event.target];
      ctx.save(); ctx.globalAlpha = Math.sin(t * Math.PI);
      ctx.strokeStyle = colors[event.player]; ctx.shadowColor = colors[event.player]; ctx.shadowBlur = 0; ctx.lineWidth = event.hit ? 4 : 1;
      if (!event.hit) ctx.setLineDash([5, 6]);
      ctx.beginPath(); ctx.moveTo(start.x, start.y); ctx.lineTo(target.x, target.y); ctx.stroke();
      if (event.hit) {
        ctx.setLineDash([]); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(target.x, target.y, cell * .65 * t, 0, Math.PI * 2); ctx.stroke();
        for (let i = 0; i < 7; i++) {
          const angle = i / 7 * Math.PI * 2;
          ctx.fillStyle = colors[event.player];
          ctx.fillRect(target.x + Math.cos(angle) * cell * t, target.y + Math.sin(angle) * cell * t, 3, 3);
        }
        ctx.font = "bold 16px Consolas, monospace"; ctx.textAlign = "center";
        ctx.fillText(`-${event.damage}`, target.x, target.y - cell * .65 - t * 15);
      }
      ctx.restore();
    }
  }
}

function drawPiece(ctx, x, y, size, piece, opacity = 1) {
  const color = colors[piece.owner];
  const solid = piece.owner === "A";
  const ink = solid ? "#a8f7ff" : "#32182e";
  const detail = solid ? "#205c6c" : "#e6a0d5";
  ctx.save(); ctx.translate(x, y); ctx.scale(size / 54, size / 54); ctx.globalAlpha = opacity;
  ctx.shadowColor = color; ctx.shadowBlur = 0;
  polygon(ctx, [[-24, -12], [-14, -23], [14, -23], [24, -12], [24, 13], [13, 23], [-13, 23], [-24, 13]], solid ? "#153a47" : "#f197d9", color, 1.2);
  ctx.shadowBlur = 0;
  if (piece.type === "rock") {
    polygon(ctx, [[-13, -7], [-8, -14], [2, -16], [12, -9], [14, 6], [6, 12], [-10, 10], [-15, 3]], detail, ink, 1.4);
    ctx.strokeStyle = ink; ctx.beginPath(); ctx.moveTo(-8, -9); ctx.lineTo(2, -2); ctx.lineTo(10, -6); ctx.stroke();
  } else if (piece.type === "paper") {
    polygon(ctx, [[-11, -16], [5, -16], [13, -8], [13, 14], [-11, 14]], detail, ink, 1.3);
    polygon(ctx, [[5, -16], [5, -8], [13, -8]], solid ? "#727c9e" : "#3d4862", ink);
    ctx.strokeStyle = ink;
    for (const yLine of [-3, 3, 9]) { ctx.beginPath(); ctx.moveTo(-6, yLine); ctx.lineTo(8, yLine); ctx.stroke(); }
  } else {
    ctx.strokeStyle = ink; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(-7, 9, 5, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(7, 9, 5, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(-5, 5); ctx.lineTo(11, -15); ctx.moveTo(5, 5); ctx.lineTo(-11, -15); ctx.stroke();
    ctx.fillStyle = ink; ctx.fillRect(-2, -2, 4, 4);
  }
  ctx.fillStyle = color; ctx.font = "10px Consolas,monospace"; ctx.textAlign = "center";
  ctx.fillText(`${piece.owner} / ${piece.type[0].toUpperCase()}`, 0, 32);
  ctx.restore();
}

function drawOTT(ctx, canvas, frame, transition, time, reducedMotion) {
  const width = canvas.width, height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0d101c"; ctx.fillRect(0, 0, width, height);
  const grid = Math.min(height - 98, width - 100), cell = grid / frame.board_size;
  const gx = (width - grid) / 2, gy = (height - grid) / 2;
  const center = p => ({ x: gx + (p.col + .5) * cell, y: gy + (frame.board_size - 1 - p.row + .5) * cell });
  const t = !transition?.duration || reducedMotion ? 1 : Math.max(0, Math.min(1, (time - transition.started) / transition.duration));
  const easing = t * t * (3 - 2 * t);
  const same = (a, b) => a && b && a.row === b.row && a.col === b.col;
  for (let row = 0; row < frame.board_size; row++) {
    for (let col = 0; col < frame.board_size; col++) {
      const p = center({ row, col });
      ctx.fillStyle = (row + col) % 2 ? "#171c2c" : "#101624";
      ctx.fillRect(p.x - cell / 2, p.y - cell / 2, cell, cell);
      ctx.strokeStyle = "#3d4862"; ctx.lineWidth = 1;
      ctx.strokeRect(p.x - cell / 2, p.y - cell / 2, cell, cell);
      for (const player of ["A", "B"]) {
        if (same(frame.goals[player], { row, col })) {
          ctx.fillStyle = colors[player] + "17"; ctx.fillRect(p.x - cell / 2 + 1, p.y - cell / 2 + 1, cell - 2, cell - 2);
          ctx.strokeStyle = colors[player] + "aa"; ctx.strokeRect(p.x - cell / 2 + 3, p.y - cell / 2 + 3, cell - 6, cell - 6);
          ctx.fillStyle = colors[player]; ctx.font = "11px Consolas,monospace"; ctx.textAlign = "center";
          ctx.fillText(`${player} GOAL`, p.x, p.y + cell * .37);
        }
      }
      if (same(frame.last_move?.from, { row, col }) || same(frame.last_move?.to, { row, col })) {
        ctx.fillStyle = colors[frame.last_move.player] + "1c";
        ctx.fillRect(p.x - cell / 2 + 2, p.y - cell / 2 + 2, cell - 4, cell - 4);
      }
    }
  }
  ctx.font = "12px Consolas,monospace"; ctx.textAlign = "center"; ctx.fillStyle = "#9ca9c4";
  for (let index = 0; index < frame.board_size; index++) {
    ctx.fillText(String.fromCharCode(97 + index), gx + (index + .5) * cell, gy - 12);
    ctx.fillText(String(frame.board_size - index), gx - 17, gy + (index + .5) * cell + 3);
  }
  const move = frame.events.find(event => event.type === "board_move");
  if (move) {
    const from = center(move.from), to = center(move.to);
    ctx.strokeStyle = colors[move.player] + "77"; ctx.lineWidth = 2; ctx.setLineDash([4, 5]);
    ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y); ctx.stroke(); ctx.setLineDash([]);
    if (move.captured && t < 1 && !reducedMotion) {
      drawPiece(ctx, to.x, to.y, cell * .71, move.captured, 1 - t);
      ctx.save(); ctx.strokeStyle = "#b0b9d3"; ctx.globalAlpha = 1 - t; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(to.x, to.y, cell * (.15 + t * .6), 0, Math.PI * 2); ctx.stroke(); ctx.restore();
    }
  }
  for (let row = 0; row < frame.board_size; row++) {
    for (let col = 0; col < frame.board_size; col++) {
      const piece = frame.board[row][col];
      if (!piece) continue;
      let p = center({ row, col });
      if (move && piece.id === move.piece_id && t < 1 && transition?.from.round === frame.round) {
        const from = center(move.from);
        p = { x: from.x + (p.x - from.x) * easing, y: from.y + (p.y - from.y) * easing };
      }
      drawPiece(ctx, p.x, p.y - cell * .03, cell * .72, piece);
    }
  }
  ctx.font = "12px Consolas,monospace"; ctx.fillStyle = "#b0b9d3"; ctx.textAlign = "left";
  ctx.fillText("R / BÚA", gx + grid + 20, gy + 25);
  ctx.fillText("P / BAO", gx + grid + 20, gy + 48);
  ctx.fillText("S / KÉO", gx + grid + 20, gy + 71);
  ctx.fillStyle = "#9ca9c4"; ctx.fillText("R > S", gx + grid + 20, gy + 117);
  ctx.fillText("S > P", gx + grid + 20, gy + 140); ctx.fillText("P > R", gx + grid + 20, gy + 163);
}

// The frontend registry can be extended alongside an adapter. A generic state
// renderer remains available for newly installed games without custom artwork.
window.NeonRenderers = (() => {
  const registry = new Map();
  const generic = {
    draw(ctx, canvas, frame) {
      ctx.fillStyle = "#0d101c"; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#b0b9d3"; ctx.font = "12px Consolas,monospace";
      JSON.stringify(frame, null, 2).split("\n").slice(0, 30).forEach((line, i) => ctx.fillText(line.slice(0, 90), 40, 55 + i * 15));
    },
    hud(frame) { return { grid: frame.game_id || "GAME", phase: "STATE VIEW", turnMax: "—", players: { A: { value: 0, max: 1, text: "PLAYER A" }, B: { value: 0, max: 1, text: "PLAYER B" } } }; },
    log(event) { return event.type === "fault" ? `${event.player}: ${event.message}` : JSON.stringify(event); },
    result(result) { return result.reason; },
  };
  return { register(id, renderer) { registry.set(id, renderer); }, get(id) { return registry.get(id) || generic; } };
})();

NeonRenderers.register("robot_battle", {
  draw: drawRobotArena,
  hud(frame) {
    return { grid: `GRID ${frame.rules.map_size} × ${frame.rules.map_size}`, phase: "SIMULTANEOUS / ROBOTS", turnMax: frame.rules.max_turns,
      players: Object.fromEntries(["A", "B"].map(p => [p, { value: frame.robots[p].hp, max: frame.rules.initial_hp, text: `${frame.robots[p].hp} / ${frame.rules.initial_hp} HP` }])) };
  },
  log(event) {
    if (event.type === "move") return `${event.player} → (${event.to.join(", ")})`;
    if (event.type === "blocked") return `${event.player}: di chuyển bị chặn`;
    if (event.type === "attack") return event.hit ? `${event.player} ⚡ ${event.target} / -${event.damage} HP` : `${event.player}: tấn công trượt`;
    if (event.type === "fault") return `${event.player}: ${event.message}`;
    return null;
  },
  result(result) { return result.reason === "knockout" ? "Robot hết HP." : result.reason === "turn_limit" ? "Đạt số lượt tối đa. Kết quả xét theo HP." : result.reason; },
});

NeonRenderers.register("battlecode26", {
  draw:drawBattlecode,
  hud(frame) {
    const scores=frame.scores||{};
    return {grid:`BATTLECODE 2026 / ${frame.board?.name||frame.rules?.map||""}`,phase:frame.pending_engine?"ENGINE ĐANG CHẠY · REPLAY SẼ XUẤT HIỆN KHI HOÀN TẤT":"REPLAY TỪ ENGINE CHÍNH THỨC",turnMax:frame.max_rounds||"—",
      players:Object.fromEntries(["A","B"].map((side,i)=>{const score=scores[side]||{},units=(frame.units||[]).filter(u=>u.team===i+1),kings=score.kings??units.filter(u=>u.robotType===2).length,rats=score.rats??units.filter(u=>u.robotType===1).length;return[side,{value:kings,max:5,text:`${kings} King · ${rats} Rat · ${score.cheese??"—"} cheese`}];}))};
  },
  log(event) {return event.type==="fault"?event.message:`#${event.actor??event.id??"—"} · ${event.type}`;},
  result(result) {return {RESIGNATION:"Đối thủ đầu hàng.",RATKING_DESTROYED:"Rat King của đối thủ đã bị hạ.",MORE_POINTS:"Chiến thắng theo điểm engine chính thức.",MORE_ROBOTS:"Chiến thắng theo số đơn vị.",MORE_CHEESE:"Chiến thắng theo lượng cheese.",TIE:"Kết quả hòa.",COIN_FLIP:"Engine phân định theo luật tie-break."}[result.reason]||result.reason;}
});

NeonRenderers.register("ott_v2", {
  draw: drawOTT,
  hud(frame) {
    return { grid: "OTT v2 / 9 × 9", phase: `VÁN ${frame.round}/${frame.rules.rounds} · ${frame.round_turn} NƯỚC · ${frame.current_player} ĐẾN LƯỢT`,
      turnMax: frame.rules.max_turns * frame.rules.rounds + frame.rules.rounds - 1,
      players: Object.fromEntries(["A", "B"].map(p => [p, { value: Object.values(frame.counts[p]).reduce((a, b) => a + b, 0), max: 9,
        text: `R:${frame.counts[p].rock} P:${frame.counts[p].paper} S:${frame.counts[p].scissors} · ${frame.scores[p]} ĐIỂM` }])) };
  },
  log(event) {
    if (event.type === "board_move") return `${event.player} ${PIECE_NAMES[event.piece_type]}: ${squareName(event.from)} → ${squareName(event.to)}`;
    if (event.type === "capture") return `${event.player} ăn ${event.piece.owner} / ${PIECE_NAMES[event.piece.type]}`;
    if (event.type === "round_end") return `Ván ${event.round}: ${event.winner ? event.winner + " thắng" : "hòa"} / ${event.reason}`;
    if (event.type === "round_start") return `Bắt đầu ván ${event.round}`;
    if (event.type === "fault") return `${event.player}: ${event.message}`;
    return null;
  },
  result(result) {
    if (result.reason === "goal") return `Chiếm góc đích ${squareName(result.goal)}.`;
    if (result.reason === "elimination") return `Loại hết quân ${PIECE_NAMES[result.eliminated_type]} của đối thủ.`;
    if (result.reason === "series_complete") return `Kết thúc các ván. Điểm A ${result.scores.A} : ${result.scores.B} B.`;
    if (result.reason === "turn_limit") return "Đạt giới hạn nước: hòa ván.";
    if (result.reason === "stalemate") return "Không còn nước hợp lệ: hòa ván.";
    return result.reason;
  },
});
