import re
from io import BytesIO

from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from .models import Bitacora, Categoria, Centro, Equipo, Gerencia, Notificacion, Soporte, Usuario


class MesaAyudaTests(TestCase):
    def setUp(self):
        self.g1, self.g2 = Gerencia.objects.create(nombre="Norte"), Gerencia.objects.create(nombre="Sur")
        self.c1 = Centro.objects.create(gerencia=self.g1, nombre="Centro A", direccion="Calle 1")
        self.c1b = Centro.objects.create(gerencia=self.g1, nombre="Centro A2", direccion="Calle 3")
        self.c2 = Centro.objects.create(gerencia=self.g2, nombre="Centro B", direccion="Calle 2")
        mk = lambda u, rol, **kw: Usuario.objects.create_user(u, password="Clave12345", rol=rol, first_name=u.title(),
                                                              last_name="X", **kw)
        self.admin, self.cons = mk("admin", "ADMIN"), mk("cons", "CONSULTA")
        self.tec = mk("tec", "TECNICO", gerencia=self.g1)
        self.sol = mk("sol", "SOLICITANTE", gerencia=self.g1, centro=self.c1)

    # ------------------------------------------------------------------ ayudas
    def entrar(self, u):
        self.client.logout()
        self.client.login(username=u, password="Clave12345")

    def datos_equipo(self, **kw):
        d = dict(tipo=str(Categoria.objects.get(nombre="CPU").pk), equipo_otro="", marca="Dell", modelo="Optiplex",
                 serial="S1", activo_fijo="AF1", gerencia=self.g1.pk, centro=self.c1.pk, area="Caja",
                 cantidad=1, estatus="OPERATIVO")
        d.update(kw)
        return d

    def equipo(self, centro, **kw):
        d = dict(categoria=Categoria.objects.get(nombre="CPU"), marca="Dell", modelo="Optiplex", centro=centro, area="Caja")
        d.update(kw)
        return Equipo.objects.create(**d)

    def soporte(self, centro, **kw):
        d = dict(centro=centro, motivo="Falla", hallazgo="", solicitante="Ana", area="")
        d.update(kw)
        return Soporte.objects.create(**d)

    # ------------------------------------------------------------------ base
    def test_login_dashboard_y_bitacora(self):
        self.assertRedirects(self.client.get("/"), "/login/?next=/")
        login = self.client.get(reverse("login"))
        self.assertContains(login, 'id="verPassword"')
        self.assertContains(login, "data-tema")
        r = self.client.post(reverse("login"), {"username": "admin", "password": "Clave12345"})
        self.assertRedirects(r, "/")
        inicio = self.client.get("/")
        self.assertContains(inicio, "Estado de los soportes")
        self.assertContains(inicio, "data-tema")
        self.assertTrue(Bitacora.objects.filter(accion="LOGIN", usuario=self.admin).exists())

    def test_equipo_otros_y_validaciones(self):
        self.entrar("tec")
        self.client.post(reverse("equipos_nuevo"), self.datos_equipo(tipo="OTROS", equipo_otro="Router", serial="R1", activo_fijo="R1"))
        self.assertEqual(Equipo.objects.get(serial="R1").nombre_equipo, "Router")
        r = self.client.post(reverse("equipos_nuevo"), self.datos_equipo(tipo="OTROS", equipo_otro="", serial="R2", activo_fijo="R2"))
        self.assertContains(r, "Escribe el nombre del equipo")
        self.entrar("admin")
        r = self.client.post(reverse("equipos_nuevo"), self.datos_equipo(gerencia=self.g2.pk, serial="R3", activo_fijo="R3"))
        self.assertContains(r, "no pertenece a la gerencia")

    def test_mover_cambiar_estatus_y_detalle_en_bitacora(self):
        self.entrar("tec")
        self.client.post(reverse("equipos_nuevo"), self.datos_equipo())
        e = Equipo.objects.get()
        self.client.post(reverse("equipos_mover", args=[e.pk]),
                         {"gerencia": self.g1.pk, "centro": self.c1b.pk, "estatus": "DANADO", "nota": "Se cayó"})
        e.refresh_from_db()
        self.assertEqual((e.centro, e.estatus), (self.c1b, "DANADO"))
        b = Bitacora.objects.filter(accion="MOVER").first()
        self.assertIn("Estatus: Operativo → Dañado", b.detalle)
        self.assertIn("Ubicación: Norte / Centro A → Norte / Centro A2", b.detalle)
        # el técnico no puede sacar el equipo de su gerencia...
        r = self.client.post(reverse("equipos_mover", args=[e.pk]), {"gerencia": self.g2.pk, "centro": self.c2.pk, "estatus": "DANADO"})
        self.assertEqual(r.status_code, 200)
        e.refresh_from_db()
        self.assertEqual(e.centro, self.c1b)
        # ...el administrador sí, entre gerencias
        self.entrar("admin")
        self.client.post(reverse("equipos_mover", args=[e.pk]), {"gerencia": self.g2.pk, "centro": self.c2.pk, "estatus": "OPERATIVO"})
        e.refresh_from_db()
        self.assertEqual(e.centro, self.c2)

    def test_permisos_por_rol(self):
        e = self.equipo(self.c1)
        self.entrar("tec")
        self.assertEqual(self.client.post(reverse("equipos_eliminar", args=[e.pk])).status_code, 403)
        for n in ("usuarios", "bitacora", "gerencias_nuevo"):
            self.assertEqual(self.client.get(reverse(n)).status_code, 403, n)
        self.entrar("cons")
        self.assertEqual(self.client.get(reverse("equipos_nuevo")).status_code, 403)
        self.assertEqual(self.client.get(reverse("equipos")).status_code, 200)
        self.entrar("admin")
        self.client.post(reverse("equipos_eliminar", args=[e.pk]))
        self.assertFalse(Equipo.objects.exists())
        self.assertTrue(Bitacora.objects.filter(accion="ELIMINAR", usuario=self.admin).exists())

    # ------------------------------------------------------------------ soportes
    def test_soporte_tecnico_edita_solo_campos_permitidos(self):
        self.entrar("tec")
        self.assertContains(self.client.get(reverse("soportes_nuevo")), "Persona que solicitó el servicio")
        self.client.post(reverse("soportes_nuevo"), dict(gerencia=self.g1.pk, centro=self.c1.pk, area="Caja", motivo="No enciende",
                         hallazgo="Fuente dañada", solucion="", recomendaciones="", solicitante="Ana", estatus="PENDIENTE"))
        s = Soporte.objects.get()
        self.assertEqual(s.tecnico, self.tec)
        self.assertContains(self.client.get(reverse("soportes_detalle", args=[s.pk])), "Fuente dañada")
        html = self.client.get(reverse("soportes")).content.decode()
        self.assertIn(reverse("soportes_editar", args=[s.pk]), html)
        self.assertNotIn(reverse("soportes_eliminar", args=[s.pk]), html)

        pagina = self.client.get(reverse("soportes_editar", args=[s.pk])).content.decode()
        tag = lambda n: re.search(rf'<(?:textarea|input|select)[^>]*name="{n}"[^>]*>', pagina).group(0)
        for habilitado in ("hallazgo", "solucion", "recomendaciones", "estatus"):
            self.assertNotIn("disabled", tag(habilitado), habilitado)
        for bloqueado in ("area", "motivo", "solicitante", "centro", "gerencia"):
            self.assertIn("disabled", tag(bloqueado), bloqueado)

        # intenta alterar todo: solo deben cambiar los cuatro campos habilitados (el área sigue bloqueada)
        self.client.post(reverse("soportes_editar", args=[s.pk]), dict(gerencia=self.g2.pk, centro=self.c2.pk, area="Almacén",
                         motivo="ALTERADO", hallazgo="Fuente dañada y placa", solucion="Cambio de fuente",
                         recomendaciones="Revisar UPS", solicitante="ALTERADO", estatus="RESUELTO"))
        s.refresh_from_db()
        self.assertEqual((s.area, s.hallazgo, s.solucion, s.recomendaciones, s.estatus),
                         ("Caja", "Fuente dañada y placa", "Cambio de fuente", "Revisar UPS", "RESUELTO"))
        self.assertEqual((s.motivo, s.solicitante, s.centro), ("No enciende", "Ana", self.c1))
        detalle = Bitacora.objects.filter(accion="EDITAR", usuario=self.tec, detalle__startswith=f"Soporte #{s.pk} ").first().detalle
        for esperado in ("Estatus: Pendiente → Resuelto", "Solución: — → Cambio de fuente"):
            self.assertIn(esperado, detalle)
        self.assertNotIn("Motivo", detalle)
        self.assertNotIn("Área", detalle)
        # una solicitud nueva (sin hallazgo ni área): el técnico puede, por ejemplo, ponerla En proceso
        nueva = self.soporte(self.c1)
        r = self.client.post(reverse("soportes_editar", args=[nueva.pk]), dict(estatus="PROCESO"))
        self.assertEqual(r.status_code, 302)
        nueva.refresh_from_db()
        self.assertEqual(nueva.estatus, "PROCESO")
        self.assertEqual(self.client.post(reverse("soportes_eliminar", args=[s.pk])).status_code, 403)
        self.entrar("cons")
        self.assertEqual(self.client.get(reverse("soportes_editar", args=[s.pk])).status_code, 403)
        self.entrar("admin")                                                   # el administrador edita todo
        self.client.post(reverse("soportes_editar", args=[s.pk]), dict(gerencia=self.g1.pk, centro=self.c1.pk, area="Caja 2",
                         motivo="No enciende", hallazgo="Corregido", solucion="Cambio de fuente", recomendaciones="Revisar UPS",
                         solicitante="Ana", estatus="RESUELTO"))
        s.refresh_from_db()
        self.assertEqual((s.hallazgo, s.area, s.estatus), ("Corregido", "Caja 2", "RESUELTO"))

    def test_soporte_area_obligatoria_y_fecha_sin_hora(self):
        self.entrar("tec")
        d = dict(gerencia=self.g1.pk, centro=self.c1.pk, area="", motivo="Falla", hallazgo="x", solucion="",
                 recomendaciones="", solicitante="Ana", estatus="PENDIENTE")
        self.assertContains(self.client.post(reverse("soportes_nuevo"), d), "Este campo es obligatorio")
        self.client.post(reverse("soportes_nuevo"), dict(d, area="Recepción"))
        s = Soporte.objects.get()
        hoy = s.fecha.astimezone().strftime("%d/%m/%Y")
        html = self.client.get(reverse("soportes")).content.decode()
        self.assertIn("Recepción", html)
        self.assertIn(hoy, html)
        self.assertNotRegex(html, hoy + r"\s+\d{1,2}:\d{2}")
        ws = load_workbook(BytesIO(self.client.get(reverse("soportes_excel")).content)).active
        self.assertEqual(len(ws.cell(2, 1).value), 10)
        self.assertEqual(ws.cell(2, 4).value, "Recepción")

    # ------------------------------------------------------------------ exportación, filtros, usuarios
    def test_excel_solo_lo_filtrado(self):
        self.entrar("admin")
        for i, est in enumerate(["OPERATIVO", "DANADO", "DANADO"]):
            self.client.post(reverse("equipos_nuevo"), self.datos_equipo(serial=f"S{i}", activo_fijo=f"A{i}", estatus=est))
        ws = load_workbook(BytesIO(self.client.get(reverse("equipos_excel") + "?estatus=DANADO").content)).active
        self.assertEqual(ws.max_row, 3)
        self.assertEqual([c.value for c in ws[1]][:3], ["Equipo", "Marca", "Modelo"])
        self.assertEqual(ws.cell(2, 10).value, "Dañado")
        for clave in ("soportes", "gerencias", "centros", "categorias", "usuarios", "bitacora"):
            self.assertEqual(self.client.get(reverse(f"{clave}_excel")).status_code, 200)

    def test_filtros_pastillas_chips_y_busqueda(self):
        self.entrar("admin")
        for i, (est, g, c) in enumerate([("OPERATIVO", self.g1, self.c1), ("DANADO", self.g1, self.c1), ("DANADO", self.g2, self.c2)]):
            self.client.post(reverse("equipos_nuevo"), self.datos_equipo(serial=f"F{i}", activo_fijo=f"F{i}", estatus=est,
                                                                       gerencia=g.pk, centro=c.pk))
        r = self.client.get(reverse("equipos"), {"gerencia": self.g1.pk})
        cuentas = {p["texto"]: p["n"] for p in r.context["pastillas"]}
        self.assertEqual(cuentas, {"Todos": 2, "Operativo": 1, "Dañado": 1, "En reparación": 0, "Desincorporado": 0})
        self.assertEqual([c["texto"] for c in r.context["chips"]], ["Gerencia: Norte"])
        r = self.client.get(reverse("equipos"), {"gerencia": self.g1.pk, "estatus": "DANADO", "q": "F1"})
        self.assertEqual((r.context["total"], len(r.context["chips"])), (1, 3))
        self.assertContains(self.client.get(reverse("equipos")), "data-gerencia")
        self.assertEqual(self.client.get(reverse("soportes"), {"desde": "2026-01-01", "hasta": "x"}).status_code, 200)

    def test_eliminaciones_protegidas_y_usuarios(self):
        self.entrar("admin")
        self.client.post(reverse("gerencias_eliminar", args=[self.g1.pk]))
        self.assertTrue(Gerencia.objects.filter(pk=self.g1.pk).exists())
        self.client.post(reverse("usuarios_eliminar", args=[self.admin.pk]))
        self.assertTrue(Usuario.objects.filter(pk=self.admin.pk).exists())
        self.client.post(reverse("usuarios_eliminar", args=[self.cons.pk]))
        self.assertFalse(Usuario.objects.filter(pk=self.cons.pk).exists())
        self.client.post(reverse("usuarios_nuevo"), dict(username="nuevo", first_name="Nu", last_name="Evo", cargo="Analista",
                         rol="TECNICO", gerencia=self.g1.pk, password1="Segura-98765", password2="Segura-98765"))
        self.assertEqual(Usuario.objects.get(username="nuevo").rol, "TECNICO")
        self.assertTrue(Bitacora.objects.filter(accion="CREAR", modulo="Usuarios").exists())

    def test_usuarios_exigen_gerencia_y_centro_segun_rol(self):
        self.entrar("admin")
        base = dict(first_name="Nu", last_name="Evo", cargo="x", password1="Segura-98765", password2="Segura-98765")
        r = self.client.post(reverse("usuarios_nuevo"), dict(base, username="t1", rol="TECNICO"))
        self.assertContains(r, "Este rol necesita una gerencia asignada")
        r = self.client.post(reverse("usuarios_nuevo"), dict(base, username="s1", rol="SOLICITANTE", gerencia=self.g1.pk))
        self.assertContains(r, "El solicitante necesita un centro asignado")
        r = self.client.post(reverse("usuarios_nuevo"), dict(base, username="s2", rol="SOLICITANTE", gerencia=self.g1.pk, centro=self.c2.pk))
        self.assertContains(r, "El centro no pertenece a la gerencia")
        self.client.post(reverse("usuarios_nuevo"), dict(base, username="s3", rol="SOLICITANTE", gerencia=self.g1.pk, centro=self.c1.pk))
        self.assertEqual(Usuario.objects.get(username="s3").centro, self.c1)
        self.client.post(reverse("usuarios_nuevo"), dict(base, username="a1", rol="CONSULTA", gerencia=self.g1.pk, centro=self.c1.pk))
        self.assertIsNone(Usuario.objects.get(username="a1").centro)          # el centro solo aplica al solicitante

    def test_geolocalizacion_por_enlace_de_google_maps(self):
        self.entrar("admin")
        base = dict(gerencia=self.g1.pk, nombre="Centro Z", direccion="Av. 1", observaciones="")
        ok = "https://www.google.com/maps/place/Santo+Domingo/@18.4861,-69.9312,15z"
        self.client.post(reverse("centros_nuevo"), dict(base, geolocalizacion=ok))
        self.assertEqual(Centro.objects.get(nombre="Centro Z").geolocalizacion, ok)
        for malo in ("https://example.com/maps/x", "https://google.evil.com/maps/x", "no-es-un-enlace"):
            self.assertContains(self.client.post(reverse("centros_nuevo"), dict(base, nombre="Malo", geolocalizacion=malo)), "Google Maps")
        self.assertContains(self.client.get(reverse("centros")), "Abrir en Google Maps")

    def test_todas_las_pantallas_cargan(self):
        self.entrar("admin")
        for n in ("dashboard", "equipos", "soportes", "gerencias", "centros", "categorias", "usuarios", "bitacora",
                  "equipos_nuevo", "soportes_nuevo", "gerencias_nuevo", "centros_nuevo", "categorias_nuevo", "usuarios_nuevo"):
            self.assertEqual(self.client.get(reverse(n)).status_code, 200, n)

    def test_sesion_se_cierra_al_reiniciar_el_servidor(self):
        self.entrar("admin")
        self.assertEqual(self.client.get("/").status_code, 200)
        with override_settings(ARRANQUE_ID="otro-arranque"):
            self.assertRedirects(self.client.get("/"), "/login/?next=/")

    # ------------------------------------------------------------------ segmentación y solicitante
    def test_segmentacion_por_gerencia(self):
        self.equipo(self.c1, serial="E1"), self.equipo(self.c2, serial="E2")
        s1, s2 = self.soporte(self.c1), self.soporte(self.c2)
        e2 = Equipo.objects.get(serial="E2")
        self.entrar("tec")                                                     # técnico de la gerencia Norte
        total = lambda n: self.client.get(reverse(n)).context["total"]
        self.assertEqual((total("equipos"), total("soportes"), total("gerencias"), total("centros")), (1, 1, 1, 2))
        dash = self.client.get("/")
        self.assertEqual((dash.context["total_soportes"], dash.context["total_equipos"], dash.context["alcance"]), (1, 1, "Norte"))
        self.assertEqual(self.client.get(reverse("equipos_mover", args=[e2.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("soportes_editar", args=[s2.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("soportes_detalle", args=[s2.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("soportes_detalle", args=[s1.pk])).status_code, 200)
        ws = load_workbook(BytesIO(self.client.get(reverse("soportes_excel")).content)).active
        self.assertEqual(ws.max_row, 2)
        filtros = self.client.get(reverse("soportes")).context["filtros"]
        self.assertEqual([o[1] for f in filtros if f["name"] == "gerencia" for o in f["opciones"]], ["Norte"])
        self.assertEqual(self.client.get(reverse("equipos_nuevo")).context["form"].fields["gerencia"].queryset.count(), 1)
        for u in ("cons", "admin"):                                            # consulta y administrador ven todo
            self.entrar(u)
            self.assertEqual((total("equipos"), total("soportes"), total("gerencias")), (2, 2, 2))
        sin = Usuario.objects.create_user("sin", password="Clave12345", rol="TECNICO")      # técnico sin gerencia
        self.entrar("sin")
        self.assertEqual((total("equipos"), total("soportes")), (0, 0))
        self.assertContains(self.client.get("/"), "asignada")

    def test_solicitante(self):
        self.equipo(self.c1, serial="MIO"), self.equipo(self.c1b, serial="OTRO-CENTRO"), self.equipo(self.c2, serial="OTRA-GERENCIA")
        self.soporte(self.c1, motivo="Mi centro")
        ajeno = self.soporte(self.c1b, motivo="Otro centro")
        self.entrar("sol")
        r = self.client.get("/")
        self.assertTemplateUsed(r, "solicitante.html")
        self.assertContains(r, "Solicitar soporte")
        self.assertContains(r, "MIO")
        self.assertContains(r, "Mi centro")
        for ajeno_txt in ("OTRO-CENTRO", "OTRA-GERENCIA", "Otro centro"):
            self.assertNotContains(r, ajeno_txt)
        self.assertNotContains(r, "cSoportes")                                 # sin gráficos
        self.assertNotContains(r, "chart.umd")
        self.assertNotContains(r, "g-inv")                                     # menú recortado
        for n in ("equipos", "soportes", "gerencias", "centros", "categorias", "usuarios", "bitacora", "equipos_nuevo",
                  "soportes_nuevo", "equipos_excel", "soportes_excel"):
            self.assertEqual(self.client.get(reverse(n)).status_code, 403, n)
        formulario = self.client.get(reverse("soportes_solicitar"))
        self.assertContains(formulario, "Nombre del solicitante")
        self.assertNotContains(formulario, 'value="Sol X"')                   # el nombre no viene prellenado
        sin_area = self.client.post(reverse("soportes_solicitar"), {"motivo": "No imprime", "solicitante": "María Pérez", "area": ""})
        self.assertContains(sin_area, "Este campo es obligatorio")             # el área es obligatoria
        self.assertFalse(Soporte.objects.filter(motivo="No imprime").exists())
        r = self.client.post(reverse("soportes_solicitar"), {"motivo": "No imprime", "solicitante": "María Pérez", "area": "Recepción"})
        self.assertRedirects(r, "/")
        s = Soporte.objects.get(motivo="No imprime")
        self.assertEqual((s.estatus, s.centro, s.solicitante, s.area, s.tecnico), ("PENDIENTE", self.c1, "María Pérez", "Recepción", self.tec))
        inicio = self.client.get("/")
        self.assertContains(inicio, "No imprime")
        self.assertContains(inicio, "Tec X")                                   # ve qué técnico lo atiende
        self.assertContains(inicio, "Recepción")                               # y el área
        self.assertEqual(self.client.get(reverse("soportes_detalle", args=[s.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("soportes_detalle", args=[ajeno.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("soportes_solicitar"), {"motivo": "", "solicitante": ""}).status_code, 200)
        self.entrar("tec")                                                     # el técnico de la gerencia lo ve como pendiente
        self.assertContains(self.client.get(reverse("soportes")), "No imprime")
        sin_centro = Usuario.objects.create_user("sol2", password="Clave12345", rol="SOLICITANTE", gerencia=self.g1)
        self.entrar("sol2")
        self.assertEqual(self.client.get(reverse("soportes_solicitar")).status_code, 403)
        self.assertContains(self.client.get("/"), "asignada")

    # ------------------------------------------------------------------ asignación de técnico y notificaciones
    def solicitar(self, usuario, motivo):
        self.entrar(usuario)
        self.client.post(reverse("soportes_solicitar"), {"motivo": motivo, "solicitante": "María Pérez", "area": "Recepción"})
        return Soporte.objects.get(motivo=motivo)

    def test_solicitud_se_asigna_al_tecnico_de_la_gerencia_con_menos_carga(self):
        tec2 = Usuario.objects.create_user("tec2", password="Clave12345", rol="TECNICO", gerencia=self.g1, first_name="Tec2", last_name="X")
        tec_sur = Usuario.objects.create_user("tecsur", password="Clave12345", rol="TECNICO", gerencia=self.g2)
        self.soporte(self.c1, tecnico=self.tec), self.soporte(self.c1, tecnico=self.tec, estatus="PROCESO")   # tec ya tiene 2 abiertos
        s = self.solicitar("sol", "No imprime")
        self.assertEqual(s.tecnico, tec2)                                      # menos carga y de la misma gerencia
        n = Notificacion.objects.get(soporte=s, usuario=tec2)
        self.assertEqual((n.usuario, n.leida), (tec2, False))
        self.assertIn("No imprime", n.mensaje)
        self.assertFalse(Notificacion.objects.filter(usuario__in=[self.tec, tec_sur]).exists())
        self.assertIn(f"Técnico asignado: {tec2}", Bitacora.objects.filter(accion="CREAR", usuario=self.sol).first().detalle)

    def test_campana_tabla_y_marcas_del_tecnico(self):
        s = self.solicitar("sol", "No imprime")
        n = Notificacion.objects.get(soporte=s, usuario=self.tec)
        self.entrar("tec")
        d = self.client.get(reverse("notificaciones_resumen")).json()
        self.assertEqual((d["no_leidas"], d["ultimo_id"]), (1, n.pk))
        self.assertIn("No imprime", d["html"])
        self.assertContains(self.client.get("/"), "campanaCuenta")
        dash = self.client.get("/")                                            # su tabla: solicitudes asignadas, marcadas como nuevas
        for texto in ("Solicitudes asignadas a mí", "No imprime", "María Pérez", 'me-1">Nuevo'):
            self.assertContains(dash, texto)
        lista = self.client.get(reverse("soportes"))
        self.assertContains(lista, 'me-1">Nuevo')
        self.assertContains(lista, "data-refrescable")                         # se refresca sola al llegar avisos
        self.assertContains(lista, "Asignados a mí")
        self.assertEqual(self.client.get(reverse("soportes"), {"tecnico": self.tec.pk}).context["total"], 1)
        self.entrar("cons")                                                    # Solo consulta tiene su propia campana, no la del técnico
        self.assertEqual(self.client.get(reverse("notificaciones_resumen")).status_code, 200)
        self.assertEqual(self.client.get(reverse("notificaciones_abrir", args=[n.pk])).status_code, 404)
        self.entrar("sol")
        self.assertEqual(self.client.get(reverse("notificaciones_resumen")).status_code, 200)   # el solicitante también tiene campana
        self.assertContains(self.client.get("/"), "campanaCuenta")
        self.entrar("admin")
        self.assertEqual(self.client.get(reverse("notificaciones_abrir", args=[n.pk])).status_code, 404)
        self.entrar("tec")
        r = self.client.get(reverse("notificaciones_abrir", args=[n.pk]))     # abrirlo: lo marca leído y va al soporte
        self.assertRedirects(r, reverse("soportes_editar", args=[s.pk]))
        n.refresh_from_db()
        self.assertTrue(n.leida)
        self.assertNotContains(self.client.get(reverse("soportes")), 'me-1">Nuevo')
        # ver el detalle también marca como leído; y "marcar todas" limpia el contador
        s2 = self.solicitar("sol", "Otra falla")
        self.entrar("tec")
        self.client.get(reverse("soportes_detalle", args=[s2.pk]))
        self.assertEqual(self.client.get(reverse("notificaciones_resumen")).json()["no_leidas"], 0)
        self.solicitar("sol", "Tercera falla")
        self.entrar("tec")
        self.assertEqual(self.client.get(reverse("notificaciones_resumen")).json()["no_leidas"], 1)
        r = self.client.post(reverse("notificaciones_leer_todas"), {"next": "https://externo.com/x"})
        self.assertRedirects(r, "/")                                           # no redirige a sitios externos
        self.assertEqual(self.client.get(reverse("notificaciones_resumen")).json()["no_leidas"], 0)

    def test_sin_tecnico_avisa_al_admin_y_se_asigna_al_crear_uno(self):
        sol_sur = Usuario.objects.create_user("solsur", password="Clave12345", rol="SOLICITANTE", gerencia=self.g2, centro=self.c2)
        s = self.solicitar("solsur", "Sin técnico")
        self.assertIsNone(s.tecnico)
        self.assertTrue(Notificacion.objects.filter(usuario=self.admin, soporte=s, mensaje__startswith="Sin técnico disponible").exists())
        self.entrar("admin")
        self.client.post(reverse("usuarios_nuevo"), dict(username="tecsur", first_name="T", last_name="S", cargo="x", rol="TECNICO",
                         gerencia=self.g2.pk, password1="Segura-98765", password2="Segura-98765"))
        s.refresh_from_db()
        self.assertEqual(s.tecnico.username, "tecsur")
        self.assertTrue(Notificacion.objects.filter(usuario=s.tecnico, soporte=s).exists())
        self.assertIn("Se le asignaron 1", Bitacora.objects.filter(modulo="Usuarios", accion="CREAR").first().detalle)

    def test_soporte_registrado_por_admin_o_tecnico(self):
        datos = dict(gerencia=self.g1.pk, centro=self.c1.pk, area="Caja", motivo="Falla", hallazgo="x", solucion="",
                     recomendaciones="", solicitante="Ana", estatus="PENDIENTE")
        self.entrar("admin")                                                   # el admin no queda como técnico: va el de la gerencia
        self.client.post(reverse("soportes_nuevo"), datos)
        s = Soporte.objects.get()
        self.assertEqual(s.tecnico, self.tec)
        self.assertTrue(Notificacion.objects.filter(usuario=self.tec, soporte=s).exists())
        self.entrar("tec")                                                     # un técnico que registra se queda con el soporte, sin avisarse
        self.client.post(reverse("soportes_nuevo"), dict(datos, motivo="Propio"))
        self.assertEqual(Soporte.objects.get(motivo="Propio").tecnico, self.tec)
        self.assertEqual(Notificacion.objects.filter(usuario=self.tec).count(), 1)
        sin = self.soporte(self.c1, motivo="Huérfano")                         # un técnico que edita uno sin técnico se lo queda
        self.client.post(reverse("soportes_editar", args=[sin.pk]), dict(hallazgo="Visto", estatus="PENDIENTE"))
        sin.refresh_from_db()
        self.assertEqual(sin.tecnico, self.tec)

    # ------------------------------------------------------------------ filtros del solicitante
    def test_filtros_en_la_pantalla_del_solicitante(self):
        self.equipo(self.c1, serial="D1", marca="Dell"), self.equipo(self.c1, serial="H1", marca="HP", estatus="DANADO")
        self.equipo(self.c1b, serial="AJENO", marca="Dell")
        self.soporte(self.c1, motivo="No imprime", solicitante="Ana", estatus="PENDIENTE")
        self.soporte(self.c1, motivo="Sin red", solicitante="Luis", estatus="RESUELTO")
        self.soporte(self.c1b, motivo="Otro centro", solicitante="Pedro")
        self.entrar("sol")

        def cuenta(**params):
            r = self.client.get("/", params)
            return r.context["activos"]["page"].paginator.count, r.context["soportes"]["page"].paginator.count

        self.assertEqual(cuenta(), (2, 2))
        self.assertEqual(cuenta(qa="dell"), (1, 2))                    # cada tabla filtra por separado
        self.assertEqual(cuenta(ea="DANADO"), (1, 2))
        self.assertEqual(cuenta(es="PENDIENTE"), (2, 1))
        self.assertEqual(cuenta(qs="red"), (2, 1))
        self.assertEqual(cuenta(ss="Luis"), (2, 1))
        self.assertEqual(cuenta(qs="Otro centro"), (2, 0))              # nunca aparecen otros centros
        self.assertEqual(cuenta(ss="Pedro"), (2, 0))
        self.assertEqual(cuenta(desde="2999-01-01"), (2, 0))
        self.assertEqual(cuenta(desde="x", ea="basura"), (0, 2))        # valores inválidos no rompen la página
        r = self.client.get("/", {"qa": "dell", "es": "PENDIENTE"})     # al filtrar una tabla se conservan los filtros de la otra
        self.assertContains(r, 'name="qa" value="dell"')
        self.assertContains(r, 'name="es" value="PENDIENTE"')
        self.assertContains(r, "data-autofiltro")
        self.assertContains(self.client.get("/", {"qa": "zzz"}), "No hay equipos con estos filtros")
        opciones = [o[1] for fl in r.context["soportes"]["filtros"] if fl["name"] == "ss" for o in fl["opciones"]]
        self.assertEqual(sorted(opciones), ["Ana", "Luis"])             # solo nombres de su propio centro

    def test_filtro_solicitante_en_la_lista_de_soportes(self):
        self.soporte(self.c1, solicitante="Ana"), self.soporte(self.c1, solicitante="Luis")
        self.soporte(self.c1b, solicitante="Pedro"), self.soporte(self.c2, solicitante="Zoe")
        self.entrar("tec")                                              # técnico de Norte: c1 y c1b
        r = self.client.get(reverse("soportes"), {"solicitante": "Ana"})
        self.assertEqual(r.context["total"], 1)
        self.assertEqual([c["texto"] for c in r.context["chips"]], ["Solicitante: Ana"])
        opciones = [o[1] for fl in r.context["filtros"] if fl["name"] == "solicitante" for o in fl["opciones"]]
        self.assertEqual(sorted(opciones), ["Ana", "Luis", "Pedro"])    # Zoe es de otra gerencia
        self.assertEqual(self.client.get(reverse("soportes"), {"solicitante": "Zoe"}).context["total"], 0)
        self.entrar("admin")
        self.assertEqual(self.client.get(reverse("soportes"), {"solicitante": "Zoe"}).context["total"], 1)
        ws = load_workbook(BytesIO(self.client.get(reverse("soportes_excel") + "?solicitante=Zoe").content)).active
        self.assertEqual(ws.max_row, 2)

    def test_sonido_de_notificaciones(self):
        from django.contrib.staticfiles import finders
        self.assertIsNotNone(finders.find("sounds/notificacion.wav"))
        self.entrar("tec")
        pagina = self.client.get("/")
        self.assertContains(pagina, 'data-sonido="/static/sounds/notificacion.wav"')
        self.assertContains(pagina, "campanaSonido")

    def test_solicitante_recibe_aviso_cuando_se_edita_su_soporte(self):
        s = self.solicitar("sol", "No imprime")                           # queda asignado a tec
        mismo = Usuario.objects.create_user("sol_mismo", password="Clave12345", rol="SOLICITANTE", gerencia=self.g1, centro=self.c1)
        otro = Usuario.objects.create_user("sol_otro", password="Clave12345", rol="SOLICITANTE", gerencia=self.g1, centro=self.c1b)
        Notificacion.objects.all().delete()                                # se ignora el aviso de asignación al técnico
        self.entrar("tec")
        datos = dict(hallazgo="Falta tóner", solucion="", recomendaciones="", estatus="PROCESO")
        self.client.post(reverse("soportes_editar", args=[s.pk]), datos)
        n = Notificacion.objects.get(usuario=self.sol)
        self.assertEqual((n.soporte, n.leida), (s, False))
        for esperado in ("Soporte #", "No imprime", "Tec X", "Estatus: Pendiente → En proceso", "Hallazgo actualizado"):
            self.assertIn(esperado, n.mensaje)
        self.assertNotIn("Falta tóner", n.mensaje)                        # no copia los textos largos
        self.assertTrue(Notificacion.objects.filter(usuario=mismo, soporte=s).exists())      # otro solicitante del mismo centro
        self.assertFalse(Notificacion.objects.filter(usuario=otro).exists())                 # de otro centro: no
        self.assertFalse(Notificacion.objects.filter(usuario=self.tec).exists())
        total = Notificacion.objects.count()
        self.client.post(reverse("soportes_editar", args=[s.pk]), datos)  # guardar sin cambios no avisa
        self.assertEqual(Notificacion.objects.count(), total)

        self.entrar("sol")                                                # lo que ve el solicitante
        self.assertEqual(self.client.get(reverse("notificaciones_resumen")).json()["no_leidas"], 1)
        inicio = self.client.get("/")
        for texto in ("campanaCuenta", "Actualizado", "data-refrescable"):
            self.assertContains(inicio, texto)
        self.entrar("sol_otro")
        self.assertEqual(self.client.get(reverse("notificaciones_abrir", args=[n.pk])).status_code, 404)
        self.entrar("sol")
        self.assertRedirects(self.client.get(reverse("notificaciones_abrir", args=[n.pk])), f"/?ver={s.pk}")
        r = self.client.get(f"/?ver={s.pk}")                              # abre solo el detalle del soporte
        self.assertContains(r, 'id="autoabrir"')
        self.assertContains(r, reverse("soportes_detalle", args=[s.pk]))
        n.refresh_from_db()
        self.assertTrue(n.leida)
        self.assertNotContains(self.client.get("/"), "Actualizado")
        self.assertEqual(self.client.get("/", {"ver": "999999"}).status_code, 200)              # soporte ajeno/inexistente: se ignora
        self.assertNotContains(self.client.get("/", {"ver": "999999"}), "autoabrir")

        self.entrar("admin")                                              # el administrador también avisa
        self.client.post(reverse("soportes_editar", args=[s.pk]), dict(gerencia=self.g1.pk, centro=self.c1.pk, area="Recepción",
                         motivo="No imprime", hallazgo="Falta tóner", solucion="Cambio de tóner", recomendaciones="",
                         solicitante="María Pérez", estatus="RESUELTO"))
        ultimo = Notificacion.objects.filter(usuario=self.sol).first()
        self.assertIn("Estatus: En proceso → Resuelto", ultimo.mensaje)
        self.assertIn("Solución actualizada", ultimo.mensaje)
        self.entrar("sol")                                                # ver el detalle también lo marca como leído
        self.client.get(reverse("soportes_detalle", args=[s.pk]))
        self.assertEqual(self.client.get(reverse("notificaciones_resumen")).json()["no_leidas"], 0)

    def test_solo_consulta_recibe_solicitudes_y_cambios_del_tecnico(self):
        cons2 = Usuario.objects.create_user("cons2", password="Clave12345", rol="CONSULTA", first_name="C2", last_name="X")
        inactivo = Usuario.objects.create_user("cons3", password="Clave12345", rol="CONSULTA", is_active=False)
        s = self.solicitar("sol", "No imprime")                           # solicitud nueva (se asigna a tec)
        for u in (self.cons, cons2):
            n = Notificacion.objects.get(usuario=u, soporte=s)
            for esperado in ("Nueva solicitud", "Centro A", "Norte", "No imprime", "María Pérez", "Técnico asignado"):
                self.assertIn(esperado, n.mensaje)
        self.assertFalse(Notificacion.objects.filter(usuario=inactivo).exists())
        self.assertFalse(Notificacion.objects.filter(usuario=self.admin).exists())        # el admin no recibe estos avisos
        # ve todas las gerencias: una solicitud de otra gerencia también le llega
        sol_sur = Usuario.objects.create_user("solsur", password="Clave12345", rol="SOLICITANTE", gerencia=self.g2, centro=self.c2)
        s_sur = self.solicitar("solsur", "Sin red")
        self.assertTrue(Notificacion.objects.filter(usuario=self.cons, soporte=s_sur, mensaje__contains="Sin técnico asignado").exists())

        self.entrar("tec")                                                # el técnico edita: Solo consulta se entera
        datos = dict(hallazgo="Falta tóner", solucion="", recomendaciones="", estatus="PROCESO")
        self.client.post(reverse("soportes_editar", args=[s.pk]), datos)
        n = Notificacion.objects.filter(usuario=self.cons, soporte=s).first()
        for esperado in ("Centro A", "No imprime", "actualizado por Tec X", "Estatus: Pendiente → En proceso", "Hallazgo actualizado"):
            self.assertIn(esperado, n.mensaje)
        self.assertNotIn("Falta tóner", n.mensaje)
        total = Notificacion.objects.count()
        self.client.post(reverse("soportes_editar", args=[s.pk]), datos)  # sin cambios no avisa
        self.assertEqual(Notificacion.objects.count(), total)

        self.entrar("cons")                                               # lo que ve Solo consulta
        self.assertEqual(self.client.get(reverse("notificaciones_resumen")).json()["no_leidas"], 3)   # 2 solicitudes + 1 cambio
        self.assertContains(self.client.get("/"), "campanaCuenta")
        lista = self.client.get(reverse("soportes"))
        self.assertContains(lista, 'me-1">Novedad')
        self.assertContains(lista, "data-refrescable")
        self.assertNotContains(lista, "soportes_editar")                  # sigue sin poder editar
        self.assertRedirects(self.client.get(reverse("notificaciones_abrir", args=[n.pk])), f"/soportes/?ver={s.pk}",
                             fetch_redirect_response=False)
        r = self.client.get(reverse("soportes"), {"ver": s.pk, "estatus": "PROCESO"})
        self.assertContains(r, 'id="autoabrir"')
        self.assertContains(r, reverse("soportes_detalle", args=[s.pk]))
        self.assertTrue(all("ver=" not in c["quitar"] for c in r.context["chips"]))     # no se vuelve a abrir al filtrar
        n.refresh_from_db()
        self.assertTrue(n.leida)
        self.assertEqual(self.client.get(reverse("soportes"), {"ver": "999999"}).status_code, 200)
        self.assertNotContains(self.client.get(reverse("soportes"), {"ver": "999999"}), "autoabrir")
        self.client.get(reverse("soportes_detalle", args=[s_sur.pk]))     # ver el detalle también marca como leído
        self.assertEqual(self.client.get(reverse("notificaciones_resumen")).json()["no_leidas"], 1)
        self.assertEqual(self.client.get(reverse("soportes_editar", args=[s.pk])).status_code, 403)
