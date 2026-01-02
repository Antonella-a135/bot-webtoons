import discord
from discord.ext import commands, tasks
import gspread
import json
import datetime
import os
from flask import Flask
from threading import Thread

# =========================
# CONFIGURACIÓN DESDE RENDER
# =========================
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GOOGLE_SHEETS_URL = os.environ.get("GOOGLE_SHEETS_URL")
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")
OWNER_ID = int(os.environ.get("OWNER_ID"))  # Tu ID de Discord

cred_dict = json.loads(GOOGLE_CREDENTIALS)
gc = gspread.service_account_from_dict(cred_dict)
sh = gc.open_by_url(GOOGLE_SHEETS_URL)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Hojas a ignorar
IGNORAR_HOJAS = {"CARPETAS", "DIA DE SUBIDA"}

# Archivos de datos
ARCHIVO_HIATUS = "hiatus.json"
ARCHIVO_SOLO = "solo.json"
ARCHIVO_CALENDARIO = "calendario.json"
ARCHIVO_PLAZOS = "plazos.json"
ARCHIVO_ALIAS = "alias.json"

# Map de días en inglés -> español
TRAD = {
    "monday": "lunes",
    "tuesday": "martes",
    "wednesday": "miércoles",
    "thursday": "jueves",
    "friday": "viernes",
    "saturday": "sábado",
    "sunday": "domingo",
}
DIAS_VALIDOS = list(TRAD.values())

# =========================
# SERVIDOR WEB 24/7 (ANTI-SLEEP)
# =========================
app = Flask("")

@app.route("/")
def home():
    return "Bot activo 24/7"

def run_web():
    app.run(host="0.0.0.0", port=10000)

def mantener_vivo():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

# =========================
# UTILIDADES DE ARCHIVOS
# =========================
def cargar(archivo, defecto):
    if not os.path.exists(archivo):
        return defecto
    with open(archivo, "r", encoding="utf-8") as f:
        return json.load(f)

def guardar(archivo, data):
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# =========================
# UTILIDADES DE RESPUESTA
# =========================
async def responder(ctx, msg: str):
    await ctx.send(msg)

async def enviar_dm(msg: str):
    user = await bot.fetch_user(OWNER_ID)
    await user.send(msg)

# =========================
# ALIAS DE OBRAS
# =========================
def resolver_obra(nombre_entrada: str) -> str:
    alias = cargar(ARCHIVO_ALIAS, {})
    return alias.get(nombre_entrada, nombre_entrada)

@bot.command()
async def alias(ctx, corto, *, completo):
    data = cargar(ARCHIVO_ALIAS, {})
    data[corto] = completo
    guardar(ARCHIVO_ALIAS, data)
    await responder(ctx, f"✅ Alias agregado:\n{corto} → {completo}")

@bot.command()
async def ver_alias(ctx):
    data = cargar(ARCHIVO_ALIAS, {})
    if not data:
        await responder(ctx, "📂 No hay alias registrados.")
        return
    msg = "📂 ALIAS:\n"
    for corto, largo in data.items():
        msg += f"- {corto} → {largo}\n"
    await responder(ctx, msg)

# =========================
# UTILIDADES DE HOJAS / CAPS
# =========================
def obtener_hoja_y_datos(obra: str):
    """Devuelve (hoja, headers, datos) o (None, None, None) si falla."""
    try:
        hoja = sh.worksheet(obra)
    except Exception:
        return None, None, None

    datos = hoja.get_all_values()
    if len(datos) < 3:
        return hoja, None, None

    headers = [h.lower().strip() for h in datos[1]]
    return hoja, headers, datos

def encontrar_proximo_cap_no_temple(headers, datos):
    """Primer cap donde 'subido a temple' != ✅."""
    if "subido a temple" not in headers:
        return None, None
    idx_temple = headers.index("subido a temple")

    for fila in datos[2:]:
        if len(fila) <= idx_temple:
            continue
        cap = fila[0]
        if not cap:
            continue
        val_temple = fila[idx_temple]
        if val_temple != "✅":
            return cap, fila
    return None, None

def faltas_asignacion(headers, fila):
    """
    Mira columnas 'traductor', 'cleaner', 'typer' para ver qué falta asignar.
    Devuelve lista como ['Tradu', 'Clean', 'Type'].
    """
    faltan = []

    def vacio(v):
        return (v is None) or (v.strip() == "")

    # Traductor
    if "traductor" in headers:
        idx = headers.index("traductor")
        if len(fila) <= idx or vacio(fila[idx]):
            faltan.append("Tradu")

    # Cleaner
    if "cleaner" in headers:
        idx = headers.index("cleaner")
        if len(fila) <= idx or vacio(fila[idx]):
            faltan.append("Clean")

    # Typer
    if "typer" in headers:
        idx = headers.index("typer")
        if len(fila) <= idx or vacio(fila[idx]):
            faltan.append("Type")

    return faltan

def cap_listo_para_temple(headers, fila):
    """
    Devuelve True si RAW, trad, clean y type están listos (✅) pero no subido a temple.
    """
    necesarios = ["raw subida", "trad. listo", "clean listo", "type listo", "subido a temple"]
    if not all(n in headers for n in necesarios):
        return False

    idx_raw = headers.index("raw subida")
    idx_trad = headers.index("trad. listo")
    idx_clean = headers.index("clean listo")
    idx_type = headers.index("type listo")
    idx_temple = headers.index("subido a temple")

    if len(fila) <= max(idx_raw, idx_trad, idx_clean, idx_type, idx_temple):
        return False

    val_raw = fila[idx_raw]
    val_trad = fila[idx_trad]
    val_clean = fila[idx_clean]
    val_type = fila[idx_type]
    val_temple = fila[idx_temple]

    return (val_raw == "✅" and
            val_trad == "✅" and
            val_clean == "✅" and
            val_type == "✅" and
            val_temple != "✅")

# =========================
# DETECTAR RAW (SIGUIENTE CAPÍTULO)
# =========================
def detectar_raw():
    avisos = []
    hiatus = cargar(ARCHIVO_HIATUS, [])
    solo = cargar(ARCHIVO_SOLO, [])

    for hoja in sh.worksheets():
        nombre = hoja.title
        if nombre in IGNORAR_HOJAS or nombre in hiatus or nombre in solo:
            continue

        datos = hoja.get_all_values()
        if len(datos) < 3:
            continue

        encabezados = [c.lower().strip() for c in datos[1]]
        if "raw subida" not in encabezados or "subido a temple" not in encabezados:
            continue

        idx_raw = encabezados.index("raw subida")
        idx_temple = encabezados.index("subido a temple")

        for fila in datos[2:]:
            if len(fila) <= max(idx_raw, idx_temple):
                continue
            cap = fila[0]
            if not cap:
                continue
            val_raw = fila[idx_raw]
            val_temple = fila[idx_temple]
            if val_temple != "✅":
                if val_raw != "✅":
                    avisos.append((nombre, cap))
                break

    return avisos

# =========================
# READY
# =========================
@bot.event
async def on_ready():
    print("✅ Bot activo 24/7 (horario Perú)")
    if not chequeo_automatico.is_running():
        chequeo_automatico.start()

# =========================
# COMANDOS BÁSICOS
# =========================
@bot.command()
async def ping(ctx):
    await responder(ctx, "pong 🏓")

@bot.command()
async def raw_pendientes(ctx):
    raws = detectar_raw()
    if not raws:
        await responder(ctx, "⭑ RAW PENDIENTES ⭑\n\n✅ No hay RAW pendientes para el siguiente Cap de cada obra.")
    else:
        lineas = [f"• {obra} → Cap {cap}" for obra, cap in raws]
        msg = "⭑ RAW PENDIENTES ⭑\n\n" + "\n".join(lineas)
        await responder(ctx, msg)

# =========================
# VER ESTADO
# =========================
@bot.command()
async def ver_estado(ctx, obra, cap):
    obra = resolver_obra(obra)
    hoja, headers, datos = obtener_hoja_y_datos(obra)
    if hoja is None or headers is None:
        await responder(ctx, "❌ No pude leer esa obra en el Excel.")
        return

    try:
        col_raw = headers.index("raw subida")
        col_trad = headers.index("trad. listo")
        col_clean = headers.index("clean listo")
        col_type = headers.index("type listo")
        col_temple = headers.index("subido a temple")
    except ValueError:
        await responder(ctx, "❌ Faltan columnas esperadas en esa hoja (RAW / listo / Temple).")
        return

    fila = next((f for f in datos[2:] if len(f) > 0 and f[0] == cap), None)
    if not fila:
        await responder(ctx, "❌ Capítulo no encontrado.")
        return

    def estado(v):
        return "✅ listo" if v == "✅" else "⏳ pendiente"

    msg = f"⭑ ESTADO {obra} Cap {cap} ⭑\n\n"
    msg += f"{estado(fila[col_raw])} RAW\n"
    msg += f"{estado(fila[col_trad])} Traducción\n"
    msg += f"{estado(fila[col_clean])} Clean\n"
    msg += f"{estado(fila[col_type])} Type\n"
    msg += f"{estado(fila[col_temple])} Subido a Temple\n"

    await responder(ctx, msg)

# =========================
# HIATUS
# =========================
@bot.command()
async def hiatus(ctx, *, obra):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_HIATUS, [])
    if obra not in data:
        data.append(obra)
        guardar(ARCHIVO_HIATUS, data)
        await responder(ctx, f"🔕 {obra} en hiatus")
    else:
        await responder(ctx, f"ℹ️ {obra} ya estaba en hiatus")

@bot.command()
async def reactivar(ctx, *, obra):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_HIATUS, [])
    if obra in data:
        data.remove(obra)
        guardar(ARCHIVO_HIATUS, data)
        await responder(ctx, f"🔔 {obra} reactivada")
    else:
        await responder(ctx, f"ℹ️ {obra} no estaba en hiatus")

@bot.command()
async def ver_hiatus(ctx):
    data = cargar(ARCHIVO_HIATUS, [])
    if not data:
        await responder(ctx, "✅ No hay obras en hiatus.")
    else:
        msg = "🔕 OBRAS EN HIATUS:\n" + "\n".join(f"- {o}" for o in data)
        await responder(ctx, msg)

# =========================
# SOLO
# =========================
@bot.command()
async def solo(ctx, *, obra):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_SOLO, [])
    if obra not in data:
        data.append(obra)
        guardar(ARCHIVO_SOLO, data)
        await responder(ctx, f"🧍 {obra} en modo SOLO")
    else:
        await responder(ctx, f"ℹ️ {obra} ya estaba en modo SOLO")

@bot.command()
async def reactivar_solo(ctx, *, obra):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_SOLO, [])
    if obra in data:
        data.remove(obra)
        guardar(ARCHIVO_SOLO, data)
        await responder(ctx, f"🔔 {obra} salió de SOLO")
    else:
        await responder(ctx, f"ℹ️ {obra} no estaba en SOLO")

@bot.command()
async def ver_solo(ctx):
    data = cargar(ARCHIVO_SOLO, [])
    if not data:
        await responder(ctx, "✅ No hay obras en modo SOLO.")
    else:
        msg = "🧍 OBRAS SOLO:\n" + "\n".join(f"- {o}" for o in data)
        await responder(ctx, msg)

# =========================
# CALENDARIO (DÍAS DE SUBIDA)
# =========================
def formatear_calendario_item(datos):
    tipo = datos.get("tipo")
    valor = datos.get("valor")

    if tipo == "semana":
        return str(valor)
    if tipo == "semana_multiple":
        return ", ".join(valor)
    if tipo == "mes":
        return ", ".join(str(x) for x in valor)
    return str(datos)

@bot.command()
async def agregar_obra(ctx, obra, *, valor):
    """
    !agregar_obra yang-ilwoo-y-yo miércoles
    !agregar_obra director lunes, jueves
    !agregar_obra director 4,14,24
    """
    obra = resolver_obra(obra)
    cal = cargar(ARCHIVO_CALENDARIO, {})
    valor = valor.lower().replace(" ", "")

    # Días del mes
    if all(ch.isdigit() or ch == "," for ch in valor):
        dias = [int(x) for x in valor.split(",") if x]
        cal[obra] = {"tipo": "mes", "valor": dias}
        guardar(ARCHIVO_CALENDARIO, cal)
        bonito = formatear_calendario_item(cal[obra])
        await responder(ctx, f"📆 {obra} → {bonito}")
        return

    # Varios días de semana
    if "," in valor:
        dias = valor.split(",")
        for d in dias:
            if d not in DIAS_VALIDOS:
                await responder(ctx, "❌ Día inválido. Usa: lunes, martes, miércoles...")
                return
        cal[obra] = {"tipo": "semana_multiple", "valor": dias}
        guardar(ARCHIVO_CALENDARIO, cal)
        bonito = formatear_calendario_item(cal[obra])
        await responder(ctx, f"📅 {obra} → {bonito}")
        return

    # Un solo día
    if valor in DIAS_VALIDOS:
        cal[obra] = {"tipo": "semana", "valor": valor}
        guardar(ARCHIVO_CALENDARIO, cal)
        bonito = formatear_calendario_item(cal[obra])
        await responder(ctx, f"📅 {obra} → {bonito}")
        return

    await responder(ctx, "❌ Formato inválido. Ejemplo: lunes / lunes,viernes / 4,14,24")

@bot.command()
async def cambiar_dia(ctx, obra, *, nuevo_valor):
    obra = resolver_obra(obra)
    cal = cargar(ARCHIVO_CALENDARIO, {})
    if obra not in cal:
        await responder(ctx, "❌ Esa obra no está en el calendario.")
        return
    ctx.message.content = f"!agregar_obra {obra} {nuevo_valor}"
    await agregar_obra(ctx, obra, valor=nuevo_valor)

@bot.command()
async def eliminar_obra(ctx, *, obra):
    obra_real = resolver_obra(obra)
    cal = cargar(ARCHIVO_CALENDARIO, {})
    if obra_real in cal:
        del cal[obra_real]
        guardar(ARCHIVO_CALENDARIO, cal)
        await responder(ctx, f"🗑️ {obra_real} eliminada del calendario")
    else:
        await responder(ctx, "❌ Esa obra no está en el calendario.")

@bot.command()
async def calendario(ctx):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    if not cal:
        await responder(ctx, "📅 El calendario está vacío.")
        return
    msg = "📅 CALENDARIO:\n"
    for obra, datos in cal.items():
        bonito = formatear_calendario_item(datos)
        msg += f"- {obra} → {bonito}\n"
    await responder(ctx, msg)

# =========================
# HOY / MAÑANA
# =========================
def obras_por_fecha(fecha: datetime.date):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    dia_semana_en = fecha.strftime("%A").lower()
    dia_semana = TRAD.get(dia_semana_en, "")
    dia_mes = fecha.day

    resultado = []
    for obra, datos in cal.items():
        tipo = datos.get("tipo")
        valor = datos.get("valor")

        if tipo == "semana" and valor == dia_semana:
            resultado.append(obra)
        elif tipo == "semana_multiple" and dia_semana in valor:
            resultado.append(obra)
        elif tipo == "mes" and dia_mes in valor:
            resultado.append(obra)

    return resultado

def obtener_caps_a_asignar_para_fecha(fecha_base: datetime.date):
    """
    Busca obras que se subirán 7 días después de 'fecha_base'
    y devuelve lista de (obra, cap, faltas_asignar).
    """
    fecha_target = fecha_base + datetime.timedelta(days=7)
    obras_target = obras_por_fecha(fecha_target)
    hiatus = cargar(ARCHIVO_HIATUS, [])
    solo = cargar(ARCHIVO_SOLO, [])
    resultado = []

    for obra in obras_target:
        if obra in IGNORAR_HOJAS or obra in hiatus or obra in solo:
            continue
        hoja, headers, datos = obtener_hoja_y_datos(obra)
        if hoja is None or headers is None:
            continue
        cap, fila = encontrar_proximo_cap_no_temple(headers, datos)
        if not cap or not fila:
            continue
        faltan = faltas_asignacion(headers, fila)
        if faltan:
            resultado.append((obra, cap, faltan))

    return resultado

@bot.command()
async def hoy(ctx):
    # Fecha base (hoy Perú)
    ahora = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    fecha = ahora.date()

    # Obras que se suben hoy
    obras = obras_por_fecha(fecha)

    # Caps a asignar hoy (para dentro de 7 días)
    asignar = obtener_caps_a_asignar_para_fecha(fecha)

    msg_partes = []

    msg = "⭑ HOY ⭑\n\n"
    if not obras:
        msg += "📭 Hoy no hay obras en el calendario.\n"
    else:
        msg += "⬆️ Subidas a la web:\n"
        for obra in obras:
            # Intentamos obtener el próximo cap no subido
            hoja, headers, datos = obtener_hoja_y_datos(obra)
            if hoja is None or headers is None:
                msg += f"• {obra}\n"
                continue
            cap, fila = encontrar_proximo_cap_no_temple(headers, datos)
            if cap:
                msg += f"• {obra} → Cap {cap}\n"
            else:
                msg += f"• {obra}\n"
    msg_partes.append(msg)

    if asignar:
        lineas = []
        for obra, cap, faltan in asignar:
            faltas_txt = ", ".join(faltan)
            lineas.append(f"• {obra} → Cap {cap} | {faltas_txt}")
        msg2 = "\n📝 Caps por asignar (para dentro de 7 días):\n" + "\n".join(lineas)
        msg_partes.append(msg2)

    await responder(ctx, "\n".join(msg_partes))

@bot.command()
async def mañana(ctx):
    ahora = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    fecha = (ahora + datetime.timedelta(days=1)).date()

    obras = obras_por_fecha(fecha)
    asignar = obtener_caps_a_asignar_para_fecha(fecha)

    msg_partes = []

    msg = "⭑ MAÑANA ⭑\n\n"
    if not obras:
        msg += "📭 Mañana no hay obras en el calendario.\n"
    else:
        msg += "⬆️ Subidas a la web:\n"
        for obra in obras:
            hoja, headers, datos = obtener_hoja_y_datos(obra)
            if hoja is None or headers is None:
                msg += f"• {obra}\n"
                continue
            cap, fila = encontrar_proximo_cap_no_temple(headers, datos)
            if cap:
                msg += f"• {obra} → Cap {cap}\n"
            else:
                msg += f"• {obra}\n"
    msg_partes.append(msg)

    if asignar:
        lineas = []
        for obra, cap, faltan in asignar:
            faltas_txt = ", ".join(faltan)
            lineas.append(f"• {obra} → Cap {cap} | {faltas_txt}")
        msg2 = "\n📝 Caps por asignar (para dentro de 7 días):\n" + "\n".join(lineas)
        msg_partes.append(msg2)

    await responder(ctx, "\n".join(msg_partes))

# =========================
# PLAZOS Y ATRASOS
# =========================
@bot.command()
async def asignar_plazo(ctx, obra, cap, persona, fecha):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_PLAZOS, {})
    data.setdefault(obra, {})
    data[obra][cap] = {"persona": persona, "fecha": fecha}
    guardar(ARCHIVO_PLAZOS, data)
    await responder(ctx, f"✅ Plazo asignado: {obra} Cap {cap} → {persona} hasta {fecha}")

@bot.command()
async def eliminar_plazo(ctx, obra, cap):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_PLAZOS, {})
    if obra in data and cap in data[obra]:
        del data[obra][cap]
        guardar(ARCHIVO_PLAZOS, data)
        await responder(ctx, "🗑️ Plazo eliminado.")
    else:
        await responder(ctx, "❌ No encontré ese plazo.")

@bot.command()
async def ver_atrasos(ctx):
    data = cargar(ARCHIVO_PLAZOS, {})
    if not data:
        await responder(ctx, "✅ No hay plazos registrados.")
        return

    hoy_peru = (datetime.datetime.utcnow() - datetime.timedelta(hours=5)).date()
    atrasos = []

    for obra, caps in data.items():
        for cap, info in caps.items():
            try:
                f = datetime.datetime.strptime(info["fecha"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if hoy_peru > f:
                dias = (hoy_peru - f).days
                atrasos.append(f"{obra} Cap {cap} → {info['persona']} ({dias} días tarde)")

    if not atrasos:
        await responder(ctx, "✅ No hay atrasos.")
    else:
        msg = "⏰ ATRASOS:\n" + "\n".join(f"- {a}" for a in atrasos)
        await responder(ctx, msg)

# =========================
# COMANDOS (LISTA)
# =========================
@bot.command()
async def comandos(ctx):
    await responder(ctx, """
📌 COMANDOS DEL BOT

!ping → Ver si el bot está activo.

!raw_pendientes → Ver el siguiente Cap que falta RAW de cada obra.

!ver_estado obra Cap → Ver qué falta en ese Cap (RAW, tradu, clean, type, Temple).

!hiatus obra → Poner una obra en pausa (no entra en recordatorios de RAW / asignación).

!reactivar obra → Quitar la obra del hiatus.

!ver_hiatus → Ver todas las obras pausadas.

!solo obra → Marcar una obra como solo tuya (sin recordatorios de RAW / asignación).

!reactivar_solo obra → Quitar el modo solo.

!ver_solo → Ver obras en modo solo.

!agregar_obra obra día → Asignar día(s) de subida (semana o días del mes).

!cambiar_dia obra día → Cambiar el día de subida de una obra.

!eliminar_obra obra → Eliminar una obra del calendario.

!calendario → Ver el calendario completo.

!hoy → Ver lo que toca hoy (subidas) y qué Caps hay que asignar (para dentro de 7 días).

!mañana → Ver lo que toca mañana (subidas) y qué Caps hay que asignar (para dentro de 7 días).

!asignar_plazo obra Cap persona fecha → Asignar una fecha límite (YYYY-MM-DD) a alguien.

!eliminar_plazo obra Cap → Borrar un plazo.

!ver_atrasos → Ver quién está atrasado según los plazos.

!alias corto nombre_obra → Crear una abreviación para una obra.

!ver_alias → Ver todos los alias registrados.

!comandos → Ver esta lista completa.
""")

# =========================
# RECORDATORIOS AUTOMÁTICOS
# =========================
@tasks.loop(minutes=1)
async def chequeo_automatico():
    # Hora de Perú
    ahora_peru = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    hoy = ahora_peru.date()

    # Solo actuamos a las 6:00 y 18:00
    if ahora_peru.minute != 0 or ahora_peru.hour not in [6, 18]:
        return

    mensajes = []

    # 1) RAW inmediato (siguiente Cap de cada obra)
    raws = detectar_raw()
    if raws:
        lineas = [f"• {obra} → Cap {cap}" for obra, cap in raws]
        msg_raw = "⭑ RAW PENDIENTES ⭑\n\n" + "\n".join(lineas)
        mensajes.append(msg_raw)
    else:
        mensajes.append("⭑ RAW PENDIENTES ⭑\n\n✅ No hay RAW pendientes para el siguiente Cap de cada obra.")

    # 2) RAW 10 días antes según calendario
    fecha_raw_10 = hoy + datetime.timedelta(days=10)
    obras_en_10 = obras_por_fecha(fecha_raw_10)
    hiatus = cargar(ARCHIVO_HIATUS, [])
    solo = cargar(ARCHIVO_SOLO, [])
    avisos_raw_10 = []

    for obra in obras_en_10:
        if obra in IGNORAR_HOJAS or obra in hiatus or obra in solo:
            continue
        hoja, headers, datos = obtener_hoja_y_datos(obra)
        if hoja is None or headers is None:
            continue
        if "raw subida" not in headers or "subido a temple" not in headers:
            continue
        idx_raw = headers.index("raw subida")
        idx_temple = headers.index("subido a temple")

        for fila in datos[2:]:
            if len(fila) <= max(idx_raw, idx_temple):
                continue
            cap = fila[0]
            if not cap:
                continue
            val_raw = fila[idx_raw]
            val_temple = fila[idx_temple]
            if val_temple != "✅":
                if val_raw != "✅":
                    avisos_raw_10.append((obra, cap))
                break

    if avisos_raw_10:
        lineas = [f"• {obra} → Cap {cap}" for obra, cap in avisos_raw_10]
        msg10 = "⭑ RAW PRÓXIMO (dentro de 10 días) ⭑\n\n" + "\n".join(lineas)
        mensajes.append(msg10)

    # 3) Caps por asignar (para dentro de 7 días desde hoy)
    asignar_hoy = obtener_caps_a_asignar_para_fecha(hoy)
    if asignar_hoy:
        lineas = []
        for obra, cap, faltan in asignar_hoy:
            faltas_txt = ", ".join(faltan)
            lineas.append(f"• {obra} → Cap {cap} | {faltas_txt}")
        msg_asig = "⭑ CAPS POR ASIGNAR (para dentro de 7 días) ⭑\n\n" + "\n".join(lineas)
        mensajes.append(msg_asig)

    # 4) Al menos un Cap listo para subir a Temple
    candidato_temple = None
    for hoja in sh.worksheets():
        nombre = hoja.title
        if nombre in IGNORAR_HOJAS:
            continue
        hoja2, headers, datos = obtener_hoja_y_datos(nombre)
        if hoja2 is None or headers is None:
            continue
        for fila in datos[2:]:
            if cap_listo_para_temple(headers, fila):
                cap = fila[0]
                if cap:
                    candidato_temple = (nombre, cap)
                    break
        if candidato_temple:
            break

    if candidato_temple:
        obra_t, cap_t = candidato_temple
        msg_temple = "⭑ LISTO PARA SUBIR A LA WEB ⭑\n\n"
        msg_temple += f"• {obra_t} → Cap {cap_t}"
        mensajes.append(msg_temple)

    # 5) Resumen semanal simple (domingo 18:00)
    if ahora_peru.weekday() == 6 and ahora_peru.hour == 18:
        msg_resumen = "⭑ RESUMEN SEMANAL ⭑\n\n"
        msg_resumen += f"RAW pendientes actuales: {len(raws)}"
        mensajes.append(msg_resumen)

    # Enviar todo por DM en bloques separados
    for m in mensajes:
        await enviar_dm(m)

import time

# =========================
# INICIO
# =========================
mantener_vivo()

backoff = 60  # empieza esperando 60s si Discord bloquea (evita loop de reinicios)

while True:
    try:
        bot.run(DISCORD_TOKEN)
        break  # si por alguna razón bot.run termina "limpio", salimos
    except discord.HTTPException as e:
        # Si Discord/Cloudflare bloquea (429), NO cierres el proceso: espera y reintenta
        if getattr(e, "status", None) == 429:
            print(f"⚠️ Rate limit / bloqueo (429). Reintentando más tarde. backoff={backoff}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 3600)  # máximo 1 hora
            continue
        raise  # otros errores: que sí falle para que lo veas
    except Exception as e:
        # Cualquier otro error inesperado: log y reintenta con un backoff suave
        print(f"❌ Error inesperado: {e}. Reintentando en {backoff}s")
        time.sleep(backoff)
        backoff = min(backoff * 2, 3600)


