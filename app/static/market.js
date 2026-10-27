// Pre-market / post-market update buttons in the community chat. Reads the saved briefing; never calls the AI.
(function () {
  var bar = document.getElementById('mu-bar'), panel = document.getElementById('mu-panel');
  if (!bar || !panel) return;
  var openKind = null;

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }

  function fmt(iso) {
    try { return new Date(iso).toLocaleString([], {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}); }
    catch (e) { return ''; }
  }

  function renderBody(text) {
    var wrap = document.createElement('div'), list = null;
    text.split('\n').forEach(function (raw) {
      var line = raw.trim();
      if (!line) { list = null; return; }
      if (/^[-•*]\s+/.test(line)) {
        if (!list) { list = el('ul'); wrap.appendChild(list); }
        list.appendChild(el('li', '', line.replace(/^[-•*]\s+/, '')));
      } else {
        list = null;
        var heading = line === line.toUpperCase() && /[A-Z]/.test(line) && line.length < 60;
        wrap.appendChild(el('div', heading ? 'mu-head' : 'mt-2', line));
      }
    });
    return wrap;
  }

  function show(kind, btn) {
    panel.classList.remove('d-none');
    panel.replaceChildren(el('div', 'text-muted small', 'Loading…'));
    fetch('/market-update/' + kind, {headers: {'X-Requested-With': 'fetch'}, credentials: 'same-origin'})
      .then(function (r) { return r.json().then(function (d) { return {status: r.status, d: d}; }); })
      .then(function (res) {
        var d = res.d;
        panel.replaceChildren();
        if (!d.ok) { panel.appendChild(el('div', 'text-muted', d.error || 'No update available yet.')); return; }
        panel.appendChild(el('h2', '', d.label));
        panel.appendChild(el('div', 'mu-meta', 'Updated ' + fmt(d.updated)));
        if (!d.is_today) panel.appendChild(el('div', 'alert alert-warning py-1 px-2 mu-stale', "This is the latest available update (not today's yet)."));
        panel.appendChild(renderBody(d.body));
        var foot = el('div', 'mu-foot');
        foot.appendChild(el('div', '', 'Posted by the admin for educational purpose only. Not a SEBI registered advisor; this is not a tip or a buy/sell recommendation.'));
        if (d.sources && d.sources.length) {
          var s = el('div', 'mt-1', 'Sources: ');
          d.sources.forEach(function (x, i) {
            var a = el('a', '', x.title); a.href = x.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
            if (i) s.appendChild(document.createTextNode(' · '));
            s.appendChild(a);
          });
          foot.appendChild(s);
        }
        panel.appendChild(foot);
      })
      .catch(function () { panel.replaceChildren(el('div', 'text-danger small', 'Could not load the update. Please try again.')); });
  }

  bar.addEventListener('click', function (e) {
    var btn = e.target.closest('button[data-mu]'); if (!btn) return;
    var kind = btn.dataset.mu;
    bar.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-expanded', 'false'); b.classList.remove('active'); });
    if (openKind === kind) { panel.classList.add('d-none'); openKind = null; return; }  // second click closes it
    openKind = kind; btn.classList.add('active'); btn.setAttribute('aria-expanded', 'true');
    show(kind, btn);
  });
})();
