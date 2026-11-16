# Mesa de Ayuda (Django)

Inventario de equipos + registro de soportes técnicos por gerencia y centro.

## Puesta en marcha
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate                              # crea tablas y las categorías iniciales
python manage.py createsuperuser                      # este usuario queda como Administrador
python manage.py runserver
```
Abre http://127.0.0.1:8000 · Pruebas: `python manage.py test core`

## Logo
Reemplaza `static/img/logo.svg` por tu logo. Si es PNG, súbelo a `static/img/` y cambia
`LOGO = "img/logo.png"` en `config/settings.py` (se usa en login, menú y pestaña del navegador).
El nombre del sistema también se cambia ahí (`NOMBRE_APP`).

## Roles, permisos y segmentación
| Rol | Qué ve | Qué puede hacer |
|---|---|---|
| **Administrador** | Todas las gerencias | Todo: crear, editar y eliminar; usuarios; bitácora; mover equipos entre gerencias |
| **Solo consulta** | Todas las gerencias | Solo ver y descargar Excel |
| **Técnico** | Solo la **gerencia que tiene asignada** (gráficos, equipos, soportes, centros) | Registrar equipos, soportes y centros de su gerencia; mover equipos entre centros de su gerencia y cambiar su estatus; en un soporte existente puede editar **hallazgo, solución, recomendaciones y estatus** (área, motivo, solicitante, gerencia y centro quedan bloqueados) |
| **Solicitante** | Solo su **centro**: tabla de sus activos y de sus soportes solicitados (sin gráficos) | Pedir un soporte con *motivo*, *nombre del solicitante* y *área*; queda como **Pendiente** |

- Técnico y Solicitante deben tener **gerencia** (y el Solicitante, **centro**) asignada en su usuario; sin eso no ven información.
- Registrar gerencias, editar/eliminar equipos, centros, gerencias, categorías y eliminar soportes: solo Administrador.
- Los niveles están en `core/views.py`, diccionario `CRUD` (`nuevo`, `editar`, `eliminar`). Qué campos edita el técnico en un
  soporte: `EDITABLES` en `SoporteTecnicoForm` (`core/forms.py`).

## Asignación de técnico y notificaciones
- Cuando un solicitante pide un soporte (o un administrador registra uno), el sistema **asigna el técnico de la gerencia del centro**.
  Si la gerencia tiene varios técnicos activos, elige al que tenga menos soportes abiertos (pendientes o en proceso).
- El técnico recibe una **notificación** en la campana de la barra superior (contador rojo, lista y aviso emergente). La campana se
  consulta cada 30 segundos y, si llega algo nuevo, las tablas de soportes y la de "Solicitudes asignadas a mí" se refrescan solas.
  Lo nuevo aparece marcado con **Nuevo** hasta que el técnico abre el soporte o la notificación.
- Cuando un técnico (o un administrador) **edita un soporte** y hay cambios, los **solicitantes de ese centro** reciben una notificación
  que dice qué cambió (por ejemplo `Estatus: Pendiente → En proceso`, `Hallazgo actualizado`). Los textos largos no se copian.
  El solicitante ve la campana, el sonido y el aviso emergente igual que el técnico; su tabla marca el soporte como **Actualizado** y,
  al abrir la notificación, se muestra el detalle del soporte. Guardar sin cambios no avisa.
- Los usuarios de **Solo consulta** reciben la campana con: cada **solicitud nueva** (de cualquier gerencia, con el técnico asignado) y
  cada **cambio** que un técnico o administrador haga a un soporte. Siguen siendo de solo lectura: al abrir el aviso se muestra la lista
  de soportes con el detalle de ese soporte abierto.
- Si la gerencia no tiene técnico, el soporte queda sin asignar y se avisa a los administradores; al crear (o activar) un técnico en esa
  gerencia, se le asignan automáticamente las solicitudes abiertas que estaban sin técnico.
- Al ejecutar `python manage.py migrate` se asignan también los soportes abiertos que ya existían sin técnico.

## Sonido de las notificaciones
- Al llegar una notificación nueva suena `static/sounds/notificacion.wav`. Para usar otro sonido, reemplaza ese archivo (mismo nombre,
  mejor corto: menos de 2 segundos) o cambia la ruta en `templates/base.html` (atributo `data-sonido`).
- El botón del altavoz dentro de la campana lo activa o silencia (se recuerda en cada navegador). Los navegadores no reproducen audio
  hasta que la persona hace un primer clic o pulsa una tecla en la página; después ya suena solo.

## Personalizar el Excel
Los Excel se generan en código (no hay plantilla). Qué tocar:
- **Columnas y datos:** en `core/views.py`, diccionario `LISTAS`: `cols` (encabezados) y `fila` (valores de cada fila, en el mismo orden).
  Lo que cambies sale igual en la tabla de pantalla y en el Excel.
- **Colores, fuente, anchos, filtros, nombre de la hoja y del archivo:** función `export_xlsx` en `core/utils.py`
  (`fgColor="0B1A2E"` es el color del encabezado, `freeze_panes`, `auto_filter`, `filename=...`).
- **Título, logo o una plantilla `.xlsx` propia:** ver los ejemplos que te dio el asistente (insertar filas arriba y `ws.add_image(...)`
  —requiere `pip install pillow` y un logo PNG—, o `load_workbook("plantilla.xlsx")` y escribir los datos desde la fila donde empiezan).

## Notas
- Para producción define `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` y `DJANGO_ALLOWED_HOSTS`, y usa `collectstatic`.
- Bootstrap, iconos, Chart.js y fuentes se cargan por CDN (requiere internet en el navegador).
- El panel `/admin/` de Django es solo para superusuarios y sus cambios NO quedan en la bitácora.

## Sesiones
- La sesión se cierra al cerrar el navegador y también al detener e iniciar de nuevo el servidor
  (guardar un archivo con `runserver` no la cierra). Se controla en `config/settings.py`:
  `SESSION_EXPIRE_AT_BROWSER_CLOSE` y `CERRAR_SESION_AL_REINICIAR`.
- En producción con varios procesos (gunicorn con varios workers) `CERRAR_SESION_AL_REINICIAR` viene
  desactivado; actívalo con `DJANGO_CERRAR_SESION_AL_REINICIAR=1` solo si usas un único proceso.

## Actualizar desde una versión anterior
Reemplaza los archivos y ejecuta `python manage.py migrate`. Los centros que tenían latitud/longitud
se convierten automáticamente en un enlace de Google Maps.
# SRSO-ACTIVOS-IT-
