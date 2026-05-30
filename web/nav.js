// Visibilidad del menú según el rol. El panel ya está protegido server-side;
// esto es UX (no mostrar links que el rol no puede usar).
//   Admin     → solo admin.
//   Reportes  → directivo o admin.
//   Libros/Tecnología (alta) → todos menos directivo (que audita, no da de alta).
// Recuerda el rol en localStorage para aplicarlo al instante (sin parpadeo).
(function () {
  function apply(rol) {
    var set = function (sel, on) {
      document.querySelectorAll(sel).forEach(function (a) { a.style.display = on ? 'inline' : 'none'; });
    };
    set('a[href="/admin.html"]', rol === 'admin');
    set('a[href="/reportes.html"]', rol === 'directivo' || rol === 'admin');
    set('a[href="/materiales.html"]', rol !== 'directivo');
    set('a[href="/tech.html"]', rol !== 'directivo');
  }
  // Acceso a "🔔 Avisos" (la credencial, donde se activan las notificaciones push) en el menú.
  // Necesario para staff: la app instalada abre en el Mostrador y no tiene barra de direcciones,
  // así que sin este link no había forma de llegar a la credencial a activar los avisos.
  (function () {
    var nav = document.querySelector('nav');
    if (nav && !nav.querySelector('a[href="/credencial.html"]')) {
      var a = document.createElement('a');
      a.href = '/credencial.html';
      a.textContent = '🔔 Avisos';
      a.style.cssText = 'color:var(--link);text-decoration:none';
      nav.appendChild(a);
    }
  })();

  try { var c = localStorage.getItem('biblio_rol'); if (c) apply(c); } catch (e) {}
  fetch('/api/auth/me')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (me) {
      if (!me) return;
      try { localStorage.setItem('biblio_rol', me.rol); } catch (e) {}
      apply(me.rol);
    })
    .catch(function () {});
})();
