/* Admin analytics charts: plain SVG, no outside libraries. Reads the JSON the page embeds. */
(function () {
  var data = JSON.parse(document.getElementById("analytics-data").textContent);
  var GREEN = "#0b6b57", BRASS = "#b8892b", INK = "#10202f", GRID = "#dde3ea", MUTED = "#5a6778";
  var PALETTE = ["#0b6b57", "#b8892b", "#3a9d8a", "#10202f", "#8a9bb0", "#c46b4a"];

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; });
  }
  function nice(max) {            /* round the top of an axis up to 1, 2 or 5 x 10^n */
    if (max <= 5) return 5;
    var p = Math.pow(10, Math.floor(Math.log(max) / Math.LN10)), n = max / p;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
  }
  function clip(t, L) { var m = Math.max(10, Math.floor((L - 10) / 6.6)); return t.length > m ? t.slice(0, m - 1) + "…" : t; }
  function width(el) { return Math.max(300, Math.min(640, Math.floor(el.clientWidth || 640))); }
  function empty(el, msg) { el.innerHTML = '<div class="chart-empty">' + esc(msg || "No data yet.") + "</div>"; }
  function sum(a) { return a.reduce(function (x, y) { return x + y; }, 0); }
  function svg(w, h, label, body) {
    return '<svg class="chart-svg" viewBox="0 0 ' + w + " " + h + '" role="img" aria-label="' + esc(label) + '">' + body + "</svg>";
  }
  function legend(items) {
    return '<ul class="chart-legend">' + items.map(function (i) {
      return '<li><span class="sw" style="background:' + i.color + '"></span>' + esc(i.label) + (i.note ? " <b>" + esc(i.note) + "</b>" : "") + "</li>";
    }).join("") + "</ul>";
  }

  /* --- line + area over days --- */
  function line(el, values, labels, color, noun) {
    if (!sum(values)) return empty(el, "Nothing in this range yet.");
    var W = width(el), H = 240, L = 40, R = 12, T = 12, B = 30, iw = W - L - R, ih = H - T - B;
    var top = nice(Math.max.apply(null, values)), n = values.length;
    var x = function (i) { return L + (n === 1 ? iw / 2 : iw * i / (n - 1)); };
    var y = function (v) { return T + ih - ih * v / top; };
    var b = "";
    for (var g = 0; g <= 4; g++) {
      var gv = top * g / 4, gy = y(gv);
      b += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + gy + '" y2="' + gy + '" stroke="' + GRID + '"/>' +
           '<text x="' + (L - 6) + '" y="' + (gy + 4) + '" text-anchor="end" font-size="11" fill="' + MUTED + '">' + Math.round(gv) + "</text>";
    }
    var pts = values.map(function (v, i) { return x(i) + "," + y(v); });
    b += '<polygon points="' + L + "," + y(0) + " " + pts.join(" ") + " " + x(n - 1) + "," + y(0) + '" fill="' + color + '" opacity="0.12"/>';
    b += '<polyline points="' + pts.join(" ") + '" fill="none" stroke="' + color + '" stroke-width="2.5" stroke-linejoin="round"/>';
    var step = Math.ceil(n / (W < 420 ? 4 : 7));
    values.forEach(function (v, i) {
      b += '<circle cx="' + x(i) + '" cy="' + y(v) + '" r="' + (n > 40 ? 2 : 3.5) + '" fill="' + color + '"><title>' + esc(labels[i]) + ": " + v + " " + noun + "</title></circle>";
      if ((i % step === 0 && n - 1 - i >= step * 0.7) || i === n - 1) {
        b += '<text x="' + x(i) + '" y="' + (H - 10) + '" text-anchor="' + (i === n - 1 && n > 1 ? "end" : "middle") + '" font-size="11" fill="' + MUTED + '">' + esc(labels[i]) + "</text>";
      }
    });
    el.innerHTML = svg(W, H, noun + " per day, total " + sum(values), b);
  }

  /* --- horizontal bars (one or two series) --- */
  function hbars(el, rows, series, opts) {
    opts = opts || {};
    if (!rows.length || !rows.some(function (r) { return series.some(function (s) { return r[s.key] > 0; }); })) return empty(el);
    var W = width(el), L = Math.min(opts.left || 170, Math.round(W * 0.42)), R = 64, rowH = series.length > 1 ? 44 : 30, T = 6, H = T + rows.length * rowH + 6;
    var top = nice(Math.max.apply(null, rows.map(function (r) { return Math.max.apply(null, series.map(function (s) { return r[s.key]; })); })));
    var iw = W - L - R, bh = series.length > 1 ? 15 : 18, b = "";
    rows.forEach(function (r, i) {
      var y0 = T + i * rowH;
      b += '<text x="' + (L - 8) + '" y="' + (y0 + rowH / 2 + 4) + '" text-anchor="end" font-size="12" fill="' + INK + '">' + esc(clip(r.label, L)) + "</text>";
      series.forEach(function (s, k) {
        var v = r[s.key], w = Math.max(iw * v / top, v > 0 ? 2 : 0);
        var by = y0 + (rowH - bh * series.length - (series.length - 1) * 3) / 2 + k * (bh + 3);
        b += '<rect x="' + L + '" y="' + by + '" width="' + w + '" height="' + bh + '" rx="3" fill="' + s.color + '"><title>' + esc(r.label) + " - " + esc(s.name) + ": " + v + "</title></rect>" +
             '<text x="' + (L + w + 6) + '" y="' + (by + bh - 4) + '" font-size="12" fill="' + MUTED + '">' + (s.fmt ? s.fmt(r) : v) + "</text>";
      });
    });
    el.innerHTML = svg(W, H, opts.label || "Bar chart", b) +
      (series.length > 1 ? legend(series.map(function (s) { return {color: s.color, label: s.name}; })) : "");
  }

  /* --- donut --- */
  function donut(el, rows) {
    var total = sum(rows.map(function (r) { return r.value; }));
    if (!total) return empty(el);
    var C = 2 * Math.PI * 48, off = 0, b = "";
    rows.forEach(function (r, i) {
      if (!r.value) return;
      var len = C * r.value / total;
      b += '<circle cx="60" cy="60" r="48" fill="none" stroke="' + PALETTE[i % PALETTE.length] + '" stroke-width="18" stroke-dasharray="' + len + " " + (C - len) +
           '" stroke-dashoffset="' + (-off) + '" transform="rotate(-90 60 60)"><title>' + esc(r.label) + ": " + r.value + "</title></circle>";
      off += len;
    });
    b += '<text x="60" y="58" text-anchor="middle" font-size="20" font-weight="600" fill="' + INK + '">' + total + '</text>' +
         '<text x="60" y="74" text-anchor="middle" font-size="9" fill="' + MUTED + '">members</text>';
    el.innerHTML = '<div class="donut-wrap">' + svg(120, 120, "Members by when they were last here", b) +
      legend(rows.map(function (r, i) {
        return {color: PALETTE[i % PALETTE.length], label: r.label, note: r.value + " (" + Math.round(100 * r.value / total) + "%)"};
      })) + "</div>";
  }

  /* --- vertical bars for the quizzes: attempts, with average score in the label --- */
  function quizBars(el, rows) {
    if (!rows.length) return empty(el, "No quizzes yet.");
    var data2 = rows.map(function (r) { return {label: r.label, attempts: r.attempts, avg: r.avg_score,
      text: r.attempts + " attempts, avg " + r.avg_score + "%"}; });
    if (!data2.some(function (r) { return r.attempts > 0; })) return empty(el, "No one has taken a quiz yet.");
    var W = width(el), L = Math.min(170, Math.round(W * 0.42)), R = 10, rowH = 34, T = 6, H = T + data2.length * rowH + 6;
    var top = nice(Math.max.apply(null, data2.map(function (r) { return r.attempts; }))), iw = Math.max(W - L - R - 110, 60), b = "";
    data2.forEach(function (r, i) {
      var y0 = T + i * rowH, w = Math.max(iw * r.attempts / top, r.attempts > 0 ? 2 : 0);
      b += '<text x="' + (L - 8) + '" y="' + (y0 + rowH / 2 + 4) + '" text-anchor="end" font-size="12" fill="' + INK + '">' + esc(clip(r.label, L)) + "</text>" +
           '<rect x="' + L + '" y="' + (y0 + 7) + '" width="' + w + '" height="20" rx="3" fill="' + GREEN + '"><title>' + esc(r.label) + ": " + esc(r.text) + "</title></rect>" +
           '<text x="' + (L + w + 6) + '" y="' + (y0 + 21) + '" font-size="12" fill="' + MUTED + '">' + r.attempts + (r.attempts ? " · avg " + r.avg + "%" : "") + "</text>";
    });
    el.innerHTML = svg(W, H, "Quiz attempts and average score", b);
  }

  var el = function (k) { return document.querySelector('[data-chart="' + k + '"]'); };
  line(el("signups"), data.signups, data.labels, GREEN, "new members");
  line(el("messages"), data.messages, data.labels, BRASS, "messages");
  donut(el("last_seen"), data.last_seen);
  hbars(el("rooms"), data.rooms, [{key: "value", color: GREEN, name: "Messages"}], {left: 110, label: "Messages by room"});
  hbars(el("occupations"), data.occupations,
        [{key: "members", color: GREEN, name: "Members"}, {key: "quiz_takers", color: BRASS, name: "Took a quiz",
          fmt: function (r) { return r.quiz_takers + " (" + r.rate + "%)"; }}],
        {left: 190, label: "Members and quiz takers by occupation"});
  hbars(el("ages"), data.ages, [{key: "value", color: GREEN, name: "Members"}], {left: 110, label: "Members by age"});
  quizBars(el("quizzes"), data.quizzes);
})();
