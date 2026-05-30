// Tema claro/oscuro: automático (sigue el sistema) + override manual con botón.
// Se carga temprano (head, sin defer) para aplicar el override ANTES de pintar.
(function () {
  var root = document.documentElement;
  // 1) aplicar override guardado (si hay) antes del primer paint → sin parpadeo
  try {
    var saved = localStorage.getItem('biblio_theme');
    if (saved === 'light' || saved === 'dark') root.dataset.theme = saved;
  } catch (e) {}

  function efectivoEsOscuro() {
    var t = root.dataset.theme;
    if (t === 'dark') return true;
    if (t === 'light') return false;
    return matchMedia('(prefers-color-scheme: dark)').matches;   // sin override → sistema
  }

  function agregarBoton() {
    if (document.getElementById('themeToggle')) return;
    var b = document.createElement('button');
    b.id = 'themeToggle';
    b.type = 'button';
    b.title = 'Cambiar tema claro/oscuro';
    b.setAttribute('aria-label', 'Cambiar tema claro/oscuro');
    var pintarIcono = function () { b.textContent = efectivoEsOscuro() ? '☀️' : '🌙'; };
    pintarIcono();
    b.addEventListener('click', function () {
      var next = efectivoEsOscuro() ? 'light' : 'dark';
      root.dataset.theme = next;
      try { localStorage.setItem('biblio_theme', next); } catch (e) {}
      pintarIcono();
    });
    document.body.appendChild(b);
  }
  if (document.readyState !== 'loading') agregarBoton();
  else document.addEventListener('DOMContentLoaded', agregarBoton);
})();
