/* Turns http(s):// and www. addresses in plain text into clickable links.
   Builds DOM nodes (never innerHTML), so a message can not inject HTML. */
(function () {
  var URL_RE = /(?:https?:\/\/|www\.)[^\s<>"']+/gi;
  window.rnfLinkify = function (text) {
    var frag = document.createDocumentFragment(), pos = 0, m;
    text = String(text == null ? '' : text);
    URL_RE.lastIndex = 0;
    while ((m = URL_RE.exec(text)) !== null) {
      var url = m[0], tail = '';
      while (url && '.,;:!?)]}'.indexOf(url.charAt(url.length - 1)) !== -1) {
        var last = url.charAt(url.length - 1);
        if (last === ')' && url.split('(').length >= url.split(')').length) break;
        tail = last + tail; url = url.slice(0, -1);
      }
      if (!url || url.indexOf('.') === -1) continue;
      frag.appendChild(document.createTextNode(text.slice(pos, m.index)));
      var a = document.createElement('a');
      a.href = /^https?:/i.test(url) ? url : 'https://' + url;
      a.target = '_blank'; a.rel = 'noopener noreferrer nofollow'; a.textContent = url;
      frag.appendChild(a);
      frag.appendChild(document.createTextNode(tail));
      pos = m.index + m[0].length;
    }
    frag.appendChild(document.createTextNode(text.slice(pos)));
    return frag;
  };
})();
