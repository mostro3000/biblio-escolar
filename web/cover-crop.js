/* Recortador de portadas — ENCUADRE MANUAL (sin OpenCV: abre al instante).
   Expone window.escanearTapa(file) -> Promise<string|null>  (data URL JPEG de la tapa recortada,
   o null si se cancela). Muestra la foto con un recuadro que se MUEVE y se ESTIRA desde las esquinas;
   recorta exactamente a ese recuadro. La IA (aparte) lee título/autor. */
(function () {
  function cargarImagen(file) {
    return new Promise((resolve, reject) => {
      const img = new Image(), url = URL.createObjectURL(file);
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('img')); };
      img.src = url;
    });
  }

  // Dibuja la imagen (ya orientada por el navegador) en un canvas de máx maxLado px → píxeles planos.
  function aCanvas(img, maxLado) {
    let w = img.naturalWidth, h = img.naturalHeight;
    if (Math.max(w, h) > maxLado) { const s = maxLado / Math.max(w, h); w = Math.round(w * s); h = Math.round(h * s); }
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    c.getContext('2d').drawImage(img, 0, 0, w, h);
    return c;
  }

  function editar(work) {
    return new Promise((resolve) => {
      const maxW = Math.min(window.innerWidth - 24, 520);
      const maxH = window.innerHeight * 0.6;
      const scale = Math.min(maxW / work.width, maxH / work.height, 1);
      const dw = Math.round(work.width * scale), dh = Math.round(work.height * scale);
      const MIN = 30;                                  // tamaño mínimo del recuadro (px display)
      let R = { x: dw * .1, y: dh * .1, w: dw * .8, h: dh * .8 };   // recuadro inicial (80% centrado)

      const ov = document.createElement('div');
      ov.style.cssText = 'position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.88);display:flex;' +
        'flex-direction:column;align-items:center;justify-content:center;gap:.8rem;padding:1rem';
      const msg = document.createElement('p');
      msg.textContent = 'Encuadrá la tapa: arrastrá las esquinas o moviendo el recuadro';
      msg.style.cssText = 'color:#fff;font-size:.92rem;margin:0;text-align:center';
      const cv = document.createElement('canvas'); cv.width = dw; cv.height = dh;
      cv.style.cssText = 'touch-action:none;border-radius:.4rem;max-width:100%';
      const fila = document.createElement('div'); fila.style.cssText = 'display:flex;gap:.6rem';
      const bCancel = document.createElement('button'); bCancel.type = 'button'; bCancel.textContent = 'Cancelar';
      bCancel.style.cssText = 'padding:.6rem 1rem;border:0;border-radius:.5rem;background:#475569;color:#fff;font-weight:600;cursor:pointer';
      const bOk = document.createElement('button'); bOk.type = 'button'; bOk.textContent = '✓ Recortar';
      bOk.style.cssText = 'padding:.6rem 1rem;border:0;border-radius:.5rem;background:#16a34a;color:#fff;font-weight:700;cursor:pointer';
      fila.append(bCancel, bOk); ov.append(msg, cv, fila); document.body.appendChild(ov);

      const ctx = cv.getContext('2d');
      // esquinas del recuadro: 0=TL 1=TR 2=BR 3=BL
      const esquinas = () => [{ x: R.x, y: R.y }, { x: R.x + R.w, y: R.y }, { x: R.x + R.w, y: R.y + R.h }, { x: R.x, y: R.y + R.h }];
      function dibujar() {
        ctx.clearRect(0, 0, dw, dh);
        ctx.drawImage(work, 0, 0, dw, dh);
        ctx.fillStyle = 'rgba(0,0,0,.5)';             // oscurecer afuera del recuadro
        ctx.fillRect(0, 0, dw, R.y);
        ctx.fillRect(0, R.y + R.h, dw, dh - (R.y + R.h));
        ctx.fillRect(0, R.y, R.x, R.h);
        ctx.fillRect(R.x + R.w, R.y, dw - (R.x + R.w), R.h);
        ctx.strokeStyle = '#22c55e'; ctx.lineWidth = 2; ctx.strokeRect(R.x, R.y, R.w, R.h);
        esquinas().forEach(p => {
          ctx.beginPath(); ctx.arc(p.x, p.y, 10, 0, 7); ctx.fillStyle = '#22c55e'; ctx.fill();
          ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke();
        });
      }
      dibujar();

      let modo = null, ci = -1, off = { x: 0, y: 0 };
      const pos = (ev) => { const r = cv.getBoundingClientRect(); return { x: (ev.clientX - r.left) * dw / r.width, y: (ev.clientY - r.top) * dh / r.height }; };
      const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
      cv.addEventListener('pointerdown', (ev) => {
        const p = pos(ev), c = esquinas(); let best = 28, bi = -1;
        c.forEach((q, i) => { const d = Math.hypot(q.x - p.x, q.y - p.y); if (d < best) { best = d; bi = i; } });
        if (bi >= 0) { modo = 'resize'; ci = bi; }
        else if (p.x > R.x && p.x < R.x + R.w && p.y > R.y && p.y < R.y + R.h) { modo = 'move'; off = { x: p.x - R.x, y: p.y - R.y }; }
        else return;
        cv.setPointerCapture(ev.pointerId);
      });
      cv.addEventListener('pointermove', (ev) => {
        if (!modo) return;
        const p = pos(ev);
        if (modo === 'move') {
          R.x = clamp(p.x - off.x, 0, dw - R.w);
          R.y = clamp(p.y - off.y, 0, dh - R.h);
        } else {                                       // resize: la esquina opuesta queda fija
          const c = esquinas(); const fijo = c[(ci + 2) % 4];
          const mx = clamp(p.x, 0, dw), my = clamp(p.y, 0, dh);
          R.x = Math.min(mx, fijo.x); R.y = Math.min(my, fijo.y);
          R.w = Math.max(MIN, Math.abs(mx - fijo.x)); R.h = Math.max(MIN, Math.abs(my - fijo.y));
        }
        dibujar();
      });
      const soltar = () => { modo = null; ci = -1; };
      cv.addEventListener('pointerup', soltar);
      cv.addEventListener('pointercancel', soltar);

      function cerrar(val) { ov.remove(); resolve(val); }
      bCancel.addEventListener('click', () => cerrar(null));
      bOk.addEventListener('click', () => {
        // recortar la región del recuadro DEL canvas de trabajo (coords display -> work)
        const sx = R.x / scale, sy = R.y / scale, sw = R.w / scale, sh = R.h / scale;
        let ow = sw, oh = sh, m = Math.max(ow, oh);
        if (m > 700) { const s = 700 / m; ow = Math.round(ow * s); oh = Math.round(oh * s); }
        const out = document.createElement('canvas'); out.width = Math.max(1, Math.round(ow)); out.height = Math.max(1, Math.round(oh));
        out.getContext('2d').drawImage(work, sx, sy, sw, sh, 0, 0, out.width, out.height);
        cerrar(out.toDataURL('image/jpeg', 0.85));
      });
    });
  }

  window.escanearTapa = async function (file) {
    let img;
    try { img = await cargarImagen(file); } catch { return null; }
    return await editar(aCanvas(img, 1500));
  };
})();
