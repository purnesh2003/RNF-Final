/* SIP calculator - runs fully in the browser (works for logged-out visitors too). */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var LIMITS = {
    goal:   { min: 10000, max: 100000000, step: 10000, def: 1000000, label: "Final amount required (₹)", res: "Monthly SIP required", main: "SIP" },
    invest: { min: 500,   max: 10000000,  step: 500,   def: 10000,   label: "Monthly SIP amount (₹)",    res: "Expected final value", main: "FV" }
  };
  var fmt = function (n) { return "₹" + Math.round(n).toLocaleString("en-IN"); };

  // Annuity-due maths (SIP paid at the start of each month).
  function factor(rate, years) {
    var n = years * 12, r = rate / 1200;
    if (r === 0) return n;
    return ((Math.pow(1 + r, n) - 1) / r) * (1 + r);   // future value of Rs 1 a month
  }
  function compute(mode, amount, years, rate) {
    var f = factor(rate, years), n = years * 12, sip, fv;
    if (mode === "goal") { fv = amount; sip = amount / f; } else { sip = amount; fv = amount * f; }
    var invested = sip * n;
    return { sip: sip, fv: fv, invested: invested, returns: Math.max(fv - invested, 0) };
  }
  window.sipCompute = compute;

  function mode() { return $("m-invest").checked ? "invest" : "goal"; }
  function num(el) { var v = parseFloat(el.value); return isFinite(v) ? v : NaN; }

  function render() {
    var m = mode(), L = LIMITS[m], err = $("sip-error");
    var a = num($("amount")), y = num($("years")), r = num($("rate"));
    var bad = null;
    if (!(a >= L.min && a <= L.max)) bad = "Amount must be between " + fmt(L.min) + " and " + fmt(L.max) + ".";
    else if (!(y >= 1 && y <= 40) || Math.floor(y) !== y) bad = "Duration must be a whole number of years from 1 to 40.";
    else if (!(r >= 1 && r <= 30)) bad = "Rate of return must be between 1% and 30%.";
    err.hidden = !bad; err.textContent = bad || "";
    if (bad) return;
    var o = compute(m, a, y, r);
    $("res-label").textContent = L.res;
    $("out-main").textContent = fmt(m === "goal" ? o.sip : o.fv);
    $("out-invested").textContent = fmt(o.invested);
    $("out-returns").textContent = fmt(o.returns);
    var C = 2 * Math.PI * 48, total = o.invested + o.returns, share = total ? o.returns / total : 0;
    $("ring").setAttribute("stroke-dasharray", (C * share).toFixed(2) + " " + C.toFixed(2));
  }

  function setMode() {
    var L = LIMITS[mode()];
    $("amount-label").textContent = L.label;
    var s = $("amount-r"); s.min = L.min; s.max = L.max; s.step = L.step;
    $("amount").min = L.min; $("amount").max = L.max; $("amount").step = L.step;
    $("amount").value = s.value = L.def;
    render();
  }

  function link(num_, range) {
    range.addEventListener("input", function () { num_.value = range.value; render(); });
    num_.addEventListener("input", function () { var v = num(num_); if (isFinite(v)) range.value = v; render(); });
  }
  link($("amount"), $("amount-r")); link($("years"), $("years-r")); link($("rate"), $("rate-r"));
  $("years").value = $("years-r").value = 5;
  $("rate").value = $("rate-r").value = 12;
  $("m-goal").addEventListener("change", setMode);
  $("m-invest").addEventListener("change", setMode);
  setMode();
})();
