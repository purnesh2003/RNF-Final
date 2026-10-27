// Copy the invite link to the clipboard.
(function () {
  var btn = document.getElementById('copy-invite'), box = document.getElementById('invite-link');
  if (!btn || !box) return;
  btn.addEventListener('click', function () {
    box.select();
    var done = function () { btn.textContent = 'Copied!'; setTimeout(function () { btn.textContent = 'Copy'; }, 2000); };
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(box.value).then(done, function () { document.execCommand('copy'); done(); }); }
    else { document.execCommand('copy'); done(); }
  });
})();
