/* SWP (Systematic Withdrawal Plan) calculator - runs fully in the browser (works for logged-out visitors too).
   Each month: take the withdrawal out first, then the rest earns that month's interest (annual rate / 12). */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n) { return "₹" + Math.round(n).toLocaleString("en-IN"); };
  var LIMIT = { invMin: 10000, invMax: 100000000, wMin: 100, yMin: 1, yMax: 40, rMin: 1, rMax: 30 };

  function compute(invest, withdraw, years, rate) {
    var r = rate / 1200, bal = invest, rows = [], totalW = 0, totalI = 0, lastMonth = years * 12, ranOut = null;
    for (var m = 1; m <= years * 12; m++) {
      var begin = bal, w = Math.min(withdraw, begin), interest = (begin - w) * r;
      bal = begin - w + interest;
      totalW += w; totalI += interest;
      rows.push({ month: m, begin: begin, withdrawal: w, interest: interest, end: bal });
      if (bal <= 0.005) { bal = 0; ranOut = m; lastMonth = m; break; }
    }
    return { rows: rows, invested: invest, totalWithdrawal: totalW, totalInterest: totalI, finalValue: bal, ranOutMonth: ranOut };
  }
  window.swpCompute = compute;

  function num(el) { var v = parseFloat(el.value); return isFinite(v) ? v : NaN; }
  function cell(tr, text, cls) { var td = document.createElement("td"); td.textContent = text; if (cls) td.className = cls; tr.appendChild(td); }

  function yearRows(rows) {
    var out = [];
    for (var i = 0; i < rows.length; i += 12) {
      var part = rows.slice(i, i + 12), w = 0, it = 0;
      part.forEach(function (x) { w += x.withdrawal; it += x.interest; });
      out.push({ label: "Year " + (i / 12 + 1), begin: part[0].begin, withdrawal: w, interest: it, end: part[part.length - 1].end });
    }
    return out;
  }

  var view = "year", last = null;
  function drawTable() {
    if (!last) return;
    var body = $("swp-body"), head = $("swp-head-first");
    head.textContent = view === "year" ? "Year" : "Month";
    body.replaceChildren();
    var list = view === "year" ? yearRows(last.rows) : last.rows.map(function (x) { return { label: "Month " + x.month, begin: x.begin, withdrawal: x.withdrawal, interest: x.interest, end: x.end }; });
    list.forEach(function (x) {
      var tr = document.createElement("tr");
      cell(tr, x.label); cell(tr, fmt(x.begin), "text-end"); cell(tr, fmt(x.withdrawal), "text-end");
      cell(tr, fmt(x.interest), "text-end"); cell(tr, fmt(x.end), "text-end");
      body.appendChild(tr);
    });
    $("view-year").classList.toggle("active", view === "year");
    $("view-month").classList.toggle("active", view === "month");
  }

  function drawChart(rows, invest) {
    var W = 600, H = 190, pad = 6, max = invest, pts = [[0, invest]];
    rows.forEach(function (x) { pts.push([x.month, x.end]); max = Math.max(max, x.end); });
    var xmax = pts[pts.length - 1][0] || 1;
    var d = pts.map(function (p, i) {
      var x = pad + (p[0] / xmax) * (W - 2 * pad), y = H - pad - (p[1] / max) * (H - 2 * pad);
      return (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }).join(" ");
    $("swp-line").setAttribute("d", d);
    $("swp-area").setAttribute("d", d + " L" + (pad + (xmax / xmax) * (W - 2 * pad)).toFixed(1) + " " + (H - pad) + " L" + pad + " " + (H - pad) + " Z");
    $("chart-max").textContent = fmt(max);
    $("chart-end").textContent = "Month " + xmax;
  }

  function render() {
    var inv = num($("inv")), w = num($("wd")), y = num($("years")), r = num($("rate")), err = $("swp-error"), bad = null;
    if (!(inv >= LIMIT.invMin && inv <= LIMIT.invMax)) bad = "Total investment must be between " + fmt(LIMIT.invMin) + " and " + fmt(LIMIT.invMax) + ".";
    else if (!(w >= LIMIT.wMin && w <= inv)) bad = "Withdrawal per month must be between " + fmt(LIMIT.wMin) + " and your total investment.";
    else if (!(y >= LIMIT.yMin && y <= LIMIT.yMax) || Math.floor(y) !== y) bad = "Time period must be a whole number of years from 1 to 40.";
    else if (!(r >= LIMIT.rMin && r <= LIMIT.rMax)) bad = "Expected return must be between 1% and 30%.";
    err.hidden = !bad; err.textContent = bad || "";
    if (bad) return;
    last = compute(inv, w, y, r);
    $("out-inv").textContent = fmt(last.invested);
    $("out-wd").textContent = fmt(last.totalWithdrawal);
    $("out-final").textContent = fmt(last.finalValue);
    $("out-interest").textContent = fmt(last.totalInterest);
    var note = $("swp-note");
    if (last.ranOutMonth) {
      var yrs = Math.floor(last.ranOutMonth / 12), mo = last.ranOutMonth % 12;
      note.textContent = "At this withdrawal your money would run out after about " + (yrs ? yrs + " year" + (yrs > 1 ? "s " : " ") : "") + (mo ? mo + " month" + (mo > 1 ? "s" : "") : "") + ". Try a smaller withdrawal or a shorter period.";
      note.hidden = false;
    } else { note.hidden = true; note.textContent = ""; }
    drawChart(last.rows, inv);
    drawTable();
  }

  function link(n, range) {
    range.addEventListener("input", function () { n.value = range.value; render(); });
    n.addEventListener("input", function () { var v = num(n); if (isFinite(v)) range.value = v; render(); });
  }
  link($("inv"), $("inv-r")); link($("wd"), $("wd-r")); link($("years"), $("years-r")); link($("rate"), $("rate-r"));
  $("inv").value = $("inv-r").value = 500000;
  $("wd").value = $("wd-r").value = 5000;
  $("years").value = $("years-r").value = 5;
  $("rate").value = $("rate-r").value = 10;
  $("view-year").addEventListener("click", function () { view = "year"; drawTable(); });
  $("view-month").addEventListener("click", function () { view = "month"; drawTable(); });
  $("swp-form").addEventListener("submit", function (e) { e.preventDefault(); });
  render();
})();
