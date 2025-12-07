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
OWNER_ID = int(os.environ.get("OWNER_ID"))

cred_dict = json.loads(GOOGLE_CREDENTIALS)
gc = gspread.service_account_from_dict(cred_dict)
sh = gc.open_by_url(GOOGLE_SHEETS_URL)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

IGNORAR_HOJAS = {"CARPETAS", "DIA DE SUBIDA"}

ARCHIVO_HIATUS = "hiatus.json"
ARCHIVO_SOLO = "solo.json"
ARCHIVO_CALENDARIO = "calendario.json"
ARCHIVO_PLAZOS = "plazos.json"

# =========================
# SERVIDOR WEB 24/7
# =========================
app = Flask("")

@app.route("/")
def home():
    return "Bot activo 24/7"

def run_web():
    app.run(host="0.0.0.0", port=10000)

def mantener_vivo():
    t = Thread(target=run_web)
    t.start()

# =========================
# UTILIDADES
# =========================
def cargar(archivo, defecto):
    if not os.path.exists(archivo):
        return defecto
    with open(archivo, "r", encoding="utf-8") as f:
        return json.load(f)

def guardar(archivo, data):
    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

async def responder(ctx, msg):
    if isinstance(ctx.channel, discord.DMChannel):
        await ctx.send(msg)
    else:
        await ctx.send(msg)

async def enviar_dm(msg):
    user = await bot.fetch_user(OWNER_ID)
    await user.send(msg)

TRAD = {
    "monday": "lunes", "tuesday": "martes", "wednesday": "miércoles",
    "thursday": "jueves", "friday": "viernes", "saturday": "sábado", "sunday": "domingo"
}
DIAS_VALIDOS = list(TRAD.values())

# =========================
# DETECTAR RAW (SIGUIENTE)
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
        encabezados = [c.lower().strip() for c in datos[1]]

        idx_raw = idx_temple = None
        for i, c in enumerate(encabezados):
            if "raw" in c:
                idx_raw = i
            if "temple" in c:
                idx_temple = i

        for fila in datos[2:]:
            if fila[idx_temple] != "✅":
                if fila[idx_raw] != "✅":
                    avisos.append((nombre, fila[0]))
                break
    return avisos

# =========================
# READY
# =========================
@bot.event
async def on_ready():
    print("✅ Bot FULL activo 24/7")
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
        for o, c in raws:
            msg += f"- {o} cap {c}\n"
        await responder(ctx, msg)

# =========================
# HIATUS
# =========================
@bot.command()
async def hiatus(ctx, *, obra):
    data = cargar(ARCHIVO_HIATUS, [])
    if obra not in data:
        data.append(obra)
        guardar(ARCHIVO_HIATUS, data)
        await responder(ctx, f"🔕 {obra} en hiatus")

@bot.command()
async def reactivar(ctx, *, obra):
    data = cargar(ARCHIVO_HIATUS, [])
    if obra in data:
        data.remove(obra)
        guardar(ARCHIVO_HIATUS, data)
        await responder(ctx, f"🔔 {obra} reactivada")

@bot.command()
async def ver_hiatus(ctx):
    data = cargar(ARCHIVO_HIATUS, [])
    if not data:
        await responder(ctx, "✅ No hay obras en hiatus.")
    else:
        await responder(ctx, "🔕 HIATUS:\n" + "\n".join(data))

# =========================
# SOLO
# =========================
@bot.command()
async def solo(ctx, *, obra):
    data = cargar(ARCHIVO_SOLO, [])
    if obra not in data:
        data.append(obra)
        guardar(ARCHIVO_SOLO, data)
        await responder(ctx, f"🧍 {obra} en modo SOLO")

@bot.command()
async def reactivar_solo(ctx, *, obra):
    data = cargar(ARCHIVO_SOLO, [])
    if obra in data:
        data.remove(obra)
        guardar(ARCHIVO_SOLO, data)
        await responder(ctx, f"🔔 {obra} salió de SOLO")

@bot.command()
async def ver_solo(ctx):
    data = cargar(ARCHIVO_SOLO, [])
    if not data:
        await responder(ctx, "✅ No hay obras en modo SOLO.")
    else:
        await responder(ctx, "🧍 OBRAS SOLO:\n" + "\n".join(data))

# =========================
# CALENDARIO
# =========================
@bot.command()
async def agregar_obra(ctx, obra, valor):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    valor = valor.lower().replace(" ", "")

    if all(x.isdigit() or x == "," for x in valor):
        dias = [int(x) for x in valor.split(",")]
        cal[obra] = {"tipo": "mes", "valor": dias}
        guardar(ARCHIVO_CALENDARIO, cal)
        await responder(ctx, f"📆 {obra} → {dias}")
        return

    if "," in valor:
        dias = valor.split(",")
        cal[obra] = {"tipo": "semana_multiple", "valor": dias}
        guardar(ARCHIVO_CALENDARIO, cal)
        await responder(ctx, f"📅 {obra} → {dias}")
        return

    if valor in DIAS_VALIDOS:
        cal[obra] = {"tipo": "semana", "valor": valor}
        guardar(ARCHIVO_CALENDARIO, cal)
        await responder(ctx, f"📅 {obra} → cada {valor}")
        return

@bot.command()
async def cambiar_dia(ctx, obra, nuevo):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    if obra in cal:
        cal[obra] = {"tipo": "semana", "valor": nuevo}
        guardar(ARCHIVO_CALENDARIO, cal)
        await responder(ctx, "✅ Día actualizado")

@bot.command()
async def eliminar_obra(ctx, obra):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    if obra in cal:
        del cal[obra]
        guardar(ARCHIVO_CALENDARIO, cal)
        await responder(ctx, "🗑️ Obra eliminada del calendario")

@bot.command()
async def calendario(ctx):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    txt = "📅 CALENDARIO:\n"
    for o, v in cal.items():
        txt += f"- {o} → {v}\n"
    await responder(ctx, txt)

# =========================
# HOY Y MAÑANA
# =========================
def obras_por_fecha(fecha):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    dia_semana = TRAD.get(fecha.strftime("%A").lower(), "")
    dia_mes = fecha.day
    resultado = []

    for obra, datos in cal.items():
        if datos["tipo"] == "semana" and datos["valor"] == dia_semana:
            resultado.append(obra)
        elif datos["tipo"] == "semana_multiple" and dia_semana in datos["valor"]:
            resultado.append(obra)
        elif datos["tipo"] == "mes" and dia_mes in datos["valor"]:
            resultado.append(obra)
    return resultado

@bot.command()
async def hoy(ctx):
    obras = obras_por_fecha(datetime.date.today())
    await responder(ctx, "\n".join(obras) if obras else "📭 Hoy no hay obras")

@bot.command()
async def mañana(ctx):
    obras = obras_por_fecha(datetime.date.today() + datetime.timedelta(days=1))
    await responder(ctx, "\n".join(obras) if obras else "📭 Mañana no hay obras")

# =========================
# PLAZOS
# =========================
@bot.command()
async def asignar_plazo(ctx, obra, cap, persona, fecha):
    data = cargar(ARCHIVO_PLAZOS, {})
    data.setdefault(obra, {})
    data[obra][cap] = {"persona": persona, "fecha": fecha}
    guardar(ARCHIVO_PLAZOS, data)
    await responder(ctx, "✅ Plazo asignado")

@bot.command()
async def eliminar_plazo(ctx, obra, cap):
    data = cargar(ARCHIVO_PLAZOS, {})
    if obra in data and cap in data[obra]:
        del data[obra][cap]
        guardar(ARCHIVO_PLAZOS, data)
        await responder(ctx, "🗑️ Plazo eliminado")

@bot.command()
async def ver_atrasos(ctx):
    data = cargar(ARCHIVO_PLAZOS, {})
    hoy = datetime.date.today()
    atrasos = []

    for obra, caps in data.items():
        for cap, info in caps.items():
            f = datetime.datetime.strptime(info["fecha"], "%Y-%m-%d").date()
            if hoy > f:
                dias = (hoy - f).days
                atrasos.append(f"{obra} cap {cap} → {info['persona']} ({dias} días tarde)")
    await responder(ctx, "\n".join(atrasos) if atrasos else "✅ No hay atrasos")

# =========================
# AUTOMÁTICO POR DM
# =========================
@tasks.loop(minutes=1)
async def chequeo_automatico():
    ahora = datetime.datetime.now()

    if ahora.minute == 0 and ahora.hour in [6, 18]:
        raws = detectar_raw()
        if raws:
            await enviar_dm("⚠️ RAW PENDIENTES:")
            for o, c in raws:
                await enviar_dm(f"- {o} cap {c}")
        else:
            await enviar_dm("✅ No hay RAW pendientes.")

        if ahora.weekday() == 6 and ahora.hour == 18:
            await enviar_dm("📊 RESUMEN SEMANAL")
            await enviar_dm(f"RAW pendientes: {len(raws)}")

# =========================
# INICIO
# =========================
mantener_vivo()
bot.run(DISCORD_TOKEN)
