(function () {
  const $ = (s, r = document) => r.querySelector(s);

  // Menú lateral: ocultar/mostrar (en móvil se superpone)
  $('#toggleSidebar')?.addEventListener('click', () =>
    document.body.classList.toggle(innerWidth < 992 ? 'sidebar-open' : 'sidebar-collapsed'));
  document.addEventListener('click', e => { if (e.target === document.body) document.body.classList.remove('sidebar-open'); });

  // Cuadro emergente con la información de un registro
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-modal-url]');
    if (!b) return;
    fetch(b.dataset.modalUrl, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(r => r.ok ? r.text() : Promise.reject())
      .then(html => {
        document.getElementById('modalContenido').innerHTML = html;
        bootstrap.Modal.getOrCreateInstance(document.getElementById('modalGeneral')).show();
      })
      .catch(() => alert('No se pudo cargar la información.'));
  });
  document.getElementById('autoabrir')?.click();      // llegó desde una notificación: abre el detalle del soporte

  // Centro depende de la Gerencia elegida
  const g = $('#id_gerencia'), c = $('#id_centro');
  if (g && c) {
    const todas = [...c.options].map(o => o.cloneNode(true));
    const pintar = val => {
      c.innerHTML = '';
      todas.forEach(o => {
        if (!o.value || o.dataset.gerencia === g.value) {
          const n = o.cloneNode(true); n.selected = n.value === val; c.appendChild(n);
        }
      });
    };
    g.addEventListener('change', () => pintar(''));
    pintar(c.value);
  }

  // Equipo: si elige OTROS se muestra el campo para escribirlo
  const t = $('#id_tipo'), w = $('#wrap_equipo_otro');
  if (t && w) {
    const mostrar = () => { w.style.display = t.value === 'OTROS' ? '' : 'none'; };
    t.addEventListener('change', mostrar); mostrar();
  }


  // Filtros de las listas: el centro depende de la gerencia y se aplican solos al cambiarlos
  const ff = $('#formFiltros');
  if (ff) {
    const fg = ff.querySelector('select[name=gerencia]'), fc = ff.querySelector('select[name=centro]');
    if (fg && fc) {
      const todas = [...fc.options].map(o => o.cloneNode(true));
      const pintar = () => {
        const val = fc.value; fc.innerHTML = '';
        todas.forEach(o => {
          if (!o.value || !fg.value || o.dataset.gerencia === fg.value) {
            const n = o.cloneNode(true); n.selected = n.value === val; fc.appendChild(n);
          }
        });
      };
      pintar();
      fg.addEventListener('change', () => { fc.value = ''; pintar(); });
    }
    ff.querySelectorAll('select, input[type=date]').forEach(el => el.addEventListener('change', () => ff.submit()));
    const q = ff.querySelector('input[name=q]'); let espera;
    if (q) {
      q.addEventListener('input', () => {
        clearTimeout(espera);
        espera = setTimeout(() => { sessionStorage.setItem('foco_q', '1'); ff.submit(); }, 600);
      });
      if (sessionStorage.getItem('foco_q')) {
        sessionStorage.removeItem('foco_q'); q.focus(); q.setSelectionRange(q.value.length, q.value.length);
      }
    }
  }

  // Formulario de usuario: el centro solo aplica al rol Solicitante
  const rol = $('#id_rol'), campoCentro = $('#wrap_centro');
  if (rol && campoCentro) {
    const ver = () => { campoCentro.style.display = rol.value === 'SOLICITANTE' ? '' : 'none'; };
    rol.addEventListener('change', ver); ver();
  }

  // Filtros de las tablas del solicitante: se aplican solos al cambiarlos
  document.querySelectorAll('form[data-autofiltro]').forEach(form => {
    form.querySelectorAll('select, input[type=date]').forEach(el => el.addEventListener('change', () => form.submit()));
    const buscar = form.querySelector('input.form-control[name^=q]'), clave = 'foco_' + form.id; let espera;
    if (buscar) {
      buscar.addEventListener('input', () => {
        clearTimeout(espera);
        espera = setTimeout(() => { sessionStorage.setItem(clave, '1'); form.submit(); }, 600);
      });
      if (sessionStorage.getItem(clave)) {
        sessionStorage.removeItem(clave); buscar.focus(); buscar.setSelectionRange(buscar.value.length, buscar.value.length);
      }
    }
  });

  // Notificaciones: la campana consulta cada 30 s; si llega una nueva muestra un aviso y refresca las tablas
  const campana = $('#campana');
  if (campana) {
    const cuenta = $('#campanaCuenta'), lista = $('#campanaLista');
    let ultimo = null;

    // Sonido: se desbloquea con el primer clic o tecla (los navegadores no permiten audio antes) y se puede silenciar
    const sonido = new Audio(campana.dataset.sonido), botonSonido = $('#campanaSonido'), eventos = ['click', 'keydown', 'touchstart'];
    sonido.preload = 'auto'; sonido.volume = 0.8;
    const sonidoActivo = () => { try { return localStorage.getItem('sonidoNotif') !== 'off'; } catch (e) { return true; } };
    const pintarSonido = () => {
      const on = sonidoActivo();
      botonSonido.innerHTML = `<i class="bi bi-volume-${on ? 'up' : 'mute'}-fill"></i>`;
      botonSonido.title = on ? 'Sonido activado (clic para silenciar)' : 'Sonido silenciado (clic para activar)';
    };
    const sonar = () => { sonido.currentTime = 0; sonido.play().catch(() => {}); };
    const desbloquear = () => {
      eventos.forEach(ev => document.removeEventListener(ev, desbloquear));
      sonido.muted = true;
      sonido.play().then(() => { sonido.pause(); sonido.currentTime = 0; sonido.muted = false; }).catch(() => { sonido.muted = false; });
    };
    eventos.forEach(ev => document.addEventListener(ev, desbloquear));
    botonSonido.addEventListener('click', () => {
      eventos.forEach(ev => document.removeEventListener(ev, desbloquear));      // este clic ya desbloquea el audio
      try { localStorage.setItem('sonidoNotif', sonidoActivo() ? 'off' : 'on'); } catch (e) {}
      pintarSonido();
      if (sonidoActivo()) sonar();                                               // vista previa al activarlo
    });
    pintarSonido();

    const refrescarTablas = () => {
      const zonas = document.querySelectorAll('[data-refrescable]');
      if (!zonas.length) return;
      fetch(location.href, {headers: {'X-Requested-With': 'XMLHttpRequest'}}).then(r => r.text()).then(html => {
        const nuevas = new DOMParser().parseFromString(html, 'text/html').querySelectorAll('[data-refrescable]');
        zonas.forEach((z, i) => { if (nuevas[i]) z.innerHTML = nuevas[i].innerHTML; });
      }).catch(() => {});
    };
    const consultar = () => fetch(campana.dataset.url, {headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(r => r.ok ? r.json() : null).then(d => {
        if (!d) return;
        cuenta.textContent = d.no_leidas > 99 ? '99+' : d.no_leidas;
        cuenta.classList.toggle('d-none', !d.no_leidas);
        lista.innerHTML = d.html;
        if (ultimo !== null && d.ultimo_id > ultimo) {
          if (sonidoActivo()) sonar();
          $('#toastTexto').textContent = d.ultimo_mensaje;
          bootstrap.Toast.getOrCreateInstance($('#toastNotif')).show();
          refrescarTablas();
        }
        ultimo = d.ultimo_id;
      }).catch(() => {});
    consultar();
    setInterval(consultar, 30000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) consultar(); });
  }

  // Modo claro / oscuro (se recuerda en el navegador)
  const temaActual = () => document.documentElement.getAttribute('data-bs-theme') || 'light';
  const pintarBotonesTema = () => document.querySelectorAll('[data-tema]').forEach(b => {
    const oscuro = temaActual() === 'dark', texto = oscuro ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro';
    b.innerHTML = `<i class="bi bi-${oscuro ? 'sun-fill' : 'moon-stars-fill'}"></i>`;
    b.title = texto; b.setAttribute('aria-label', texto);
  });
  document.querySelectorAll('[data-tema]').forEach(b => b.addEventListener('click', () => {
    const nuevo = temaActual() === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-bs-theme', nuevo);
    try { localStorage.setItem('tema', nuevo); } catch (e) {}
    pintarBotonesTema();
    document.dispatchEvent(new CustomEvent('tema', {detail: nuevo}));
  }));
  pintarBotonesTema();
})();
