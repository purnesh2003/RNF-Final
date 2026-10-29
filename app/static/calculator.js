// One Calculator page with two tabs (SIP / SWP). The tab is remembered in the address (#sip / #swp).
(function () {
  var tabs = document.querySelectorAll('#calc-tabs [data-calc]');
  var panels = { sip: document.getElementById('panel-sip'), swp: document.getElementById('panel-swp') };
  function show(kind) {
    tabs.forEach(function (b) { var on = b.dataset.calc === kind; b.classList.toggle('active', on); b.setAttribute('aria-selected', on); });
    panels.sip.hidden = kind !== 'sip'; panels.swp.hidden = kind !== 'swp';
  }
  tabs.forEach(function (b) {
    b.addEventListener('click', function () {
      show(b.dataset.calc);
      if (window.history && history.replaceState) history.replaceState(null, '', '#' + b.dataset.calc);
    });
  });
  window.addEventListener('hashchange', function () { show(location.hash === '#swp' ? 'swp' : 'sip'); });
  show(location.hash === '#swp' ? 'swp' : 'sip');
  ['sip-form', 'swp-form'].forEach(function (id) {       // Enter must not reload the page
    var f = document.getElementById(id); if (f) f.addEventListener('submit', function (e) { e.preventDefault(); });
  });
})();
