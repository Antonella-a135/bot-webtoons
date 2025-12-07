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
    print("✅ Bot COMPLETO activo 24/7 (horario Perú)")
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
        await responder(ctx, "✅ Todos los siguientes capítulos ya tienen RAW.")
    else:
        msg = "⚠️ RAW PENDIENTES:\n"
        for obra, cap in raws:
            msg += f"- {obra} cap {cap}\n"
        await responder(ctx, msg)

# =========================
# VER ESTADO
# =========================
@bot.command()
async def ver_estado(ctx, obra, cap):
    obra = resolver_obra(obra)
    hoja = sh.worksheet(obra)

    datos = hoja.get_all_values()
    headers = [h.lower().strip() for h in datos[1]]

    col_raw = headers.index("raw subida")
    col_trad = headers.index("trad. listo")
    col_clean = headers.index("clean listo")
    col_type = headers.index("type listo")
    col_temple = headers.index("subido a temple")

    fila = next((f for f in datos[2:] if len(f) > 0 and f[0] == cap), None)

    if not fila:
        await responder(ctx, "❌ Capítulo no encontrado.")
        return

    def estado(v):
        return "✅ listo" if v == "✅" else "⏳ pendiente"

    msg = f"📊 ESTADO {obra} cap {cap}\n\n"
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

    if all(ch.isdigit() or ch == "," for ch in valor):
        dias = [int(x) for x in valor.split(",") if x]
        cal[obra] = {"tipo": "mes", "valor": dias}
        guardar(ARCHIVO_CALENDARIO, cal)
        bonito = formatear_calendario_item(cal[obra])
        await responder(ctx, f"📆 {obra} → {bonito}")
        return

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

@bot.command()
async def hoy(ctx):
    ahora = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    fecha = ahora.date()
    obras = obras_por_fecha(fecha)
    if not obras:
        await responder(ctx, "📭 Hoy no hay obras en el calendario.")
    else:
        msg = "📅 HOY:\n" + "\n".join(f"- {o}" for o in obras)
        await responder(ctx, msg)

@bot.command()
async def mañana(ctx):
    ahora = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    fecha = (ahora + datetime.timedelta(days=1)).date()
    obras = obras_por_fecha(fecha)
    if not obras:
        await responder(ctx, "📭 Mañana no hay obras en el calendario.")
    else:
        msg = "📅 MAÑANA:\n" + "\n".join(f"- {o}" for o in obras)
        await responder(ctx, msg)

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
    await responder(ctx, f"✅ Plazo asignado: {obra} cap {cap} → {persona} hasta {fecha}")

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
                atrasos.append(f"{obra} cap {cap} → {info['persona']} ({dias} días tarde)")

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

!raw_pendientes → Ver el siguiente capítulo que falta RAW de cada obra.

!ver_estado obra cap → Ver qué falta en ese capítulo (RAW, tradu, clean, type, Temple).

!hiatus obra → Poner una obra en pausa (no se revisa para recordatorios).

!reactivar obra → Quitar la obra del hiatus.

!ver_hiatus → Ver todas las obras pausadas.

!solo obra → Marcar una obra como solo tuya.

!reactivar_solo obra → Quitar el modo solo.

!ver_solo → Ver obras en modo solo.

!agregar_obra obra día → Asignar día(s) de subida (semana o días del mes).

!cambiar_dia obra día → Cambiar el día de subida de una obra.

!eliminar_obra obra → Eliminar una obra del calendario.

!calendario → Ver el calendario completo.

!hoy → Ver lo que toca hoy según el calendario.

!mañana → Ver lo que toca mañana según el calendario.

!asignar_plazo obra cap persona fecha → Asignar una fecha límite (YYYY-MM-DD) a alguien.

!eliminar_plazo obra cap → Borrar un plazo.

!ver_atrasos → Ver quién está atrasado según los plazos.

!alias corto nombre_obra → Crear una abreviación para una obra.

!ver_alias → Ver todos los alias registrados.

!comandos → Ver esta lista completa.
""")

# =========================
# RECORDATORIOS AUTOMÁTICOS (RAW, RAW 10 DÍAS, TEMPLE)
# =========================
@tasks.loop(minutes=1)
async def chequeo_automatico():
    # Hora de Perú = UTC - 5
    ahora_peru = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    hoy = ahora_peru.date()

    # Solo actuamos a las 6:00 y 18:00
    if ahora_peru.minute == 0 and ahora_peru.hour in [6, 18]:
        # 1) RAW normal (lo que ya tenías)
        raws = detectar_raw()
        if raws:
            await enviar_dm("⚠️ RAW PENDIENTES (siguiente capítulo de cada obra):")
            for obra, cap in raws:
                await enviar_dm(f"- {obra} cap {cap}")
        else:
            await enviar_dm("✅ No hay RAW pendientes para el siguiente capítulo de cada obra.")

        # 2) RAW 10 días antes según calendario
        fecha_objetivo = hoy + datetime.timedelta(days=10)
        obras_en_10_dias = obras_por_fecha(fecha_objetivo)
        hiatus = cargar(ARCHIVO_HIATUS, [])
        solo = cargar(ARCHIVO_SOLO, [])
        avisos_raw_10 = []

        for obra in obras_en_10_dias:
            if obra in IGNORAR_HOJAS or obra in hiatus or obra in solo:
                continue
            try:
                hoja = sh.worksheet(obra)
            except Exception:
                continue

            datos = hoja.get_all_values()
            if len(datos) < 3:
                continue
            headers = [h.lower().strip() for h in datos[1]]
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
            await enviar_dm("⏰ Dentro de 10 días se suben estas obras y les falta RAW:")
            for obra, cap in avisos_raw_10:
                await enviar_dm(f"- {obra} cap {cap}")

        # 3) Recordatorio de al menos UN capítulo listo para subir a Temple
        candidato_temple = None
        for hoja in sh.worksheets():
            nombre = hoja.title
            if nombre in IGNORAR_HOJAS:
                continue
            datos = hoja.get_all_values()
            if len(datos) < 3:
                continue
            headers = [h.lower().strip() for h in datos[1]]
            necesarios = ["raw subida", "trad. listo", "clean listo", "type listo", "subido a temple"]
            if not all(n in headers for n in necesarios):
                continue
            idx_raw = headers.index("raw subida")
            idx_trad = headers.index("trad. listo")
            idx_clean = headers.index("clean listo")
            idx_type = headers.index("clean listo") if False else headers.index("type listo")
            idx_temple = headers.index("subido a temple")

            for fila in datos[2:]:
                if len(fila) <= max(idx_raw, idx_trad, idx_clean, idx_type, idx_temple):
                    continue
                cap = fila[0]
                if not cap:
                    continue
                val_raw = fila[idx_raw]
                val_trad = fila[idx_trad]
                val_clean = fila[idx_clean]
                val_type = fila[idx_type]
                val_temple = fila[idx_temple]

                if (val_raw == "✅" and val_trad == "✅" and
                    val_clean == "✅" and val_type == "✅" and
                    val_temple != "✅"):
                    candidato_temple = (nombre, cap)
                    break

            if candidato_temple:
                break

        if candidato_temple:
            obra_t, cap_t = candidato_temple
            await enviar_dm(f"⬆️ Tienes al menos un capítulo listo para subir a Temple:\n- {obra_t} cap {cap_t}")

        # 4) Domingo 6 PM → resumen semanal simple
        if ahora_peru.weekday() == 6 and ahora_peru.hour == 18:
            await enviar_dm("📊 RESUMEN SEMANAL")
            await enviar_dm(f"RAW pendientes actuales: {len(raws)}")

# =========================
# INICIO
# =========================
mantener_vivo()
bot.run(DISCORD_TOKEN)
