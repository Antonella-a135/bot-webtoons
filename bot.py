import discord
from discord.ext import commands, tasks
import gspread
import json
import datetime
import os

# ✅ DESPERTADOR WEB (FLASK)
from flask import Flask
from threading import Thread

# =========================
# CONFIGURACIÓN
# =========================
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

DISCORD_TOKEN = config["DISCORD_TOKEN"]
GOOGLE_SHEETS_URL = config["GOOGLE_SHEETS_URL"]
SERVICE_ACCOUNT_FILE = config["SERVICE_ACCOUNT_FILE"]

gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
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
# SERVIDOR WEB PARA MANTENER VIVO EL BOT
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

TRAD = {
    "monday": "lunes", "tuesday": "martes", "wednesday": "miércoles",
    "thursday": "jueves", "friday": "viernes", "saturday": "sábado", "sunday": "domingo"
}
DIAS_VALIDOS = list(TRAD.values())

# =========================
# DETECTAR RAW
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
# OBRAS POR FECHA
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

# =========================
# EVENTO READY
# =========================
@bot.event
async def on_ready():
    print("✅ Bot conectado")
    chequeo_automatico.start()

# =========================
# COMANDOS BÁSICOS
# =========================
@bot.command()
async def ping(ctx):
    await ctx.send("pong 🏓")

@bot.command()
async def raw_pendientes(ctx):
    raws = detectar_raw()
    if not raws:
        await ctx.send("✅ Todos los siguientes capítulos ya tienen RAW.")
    else:
        for obra, cap in raws:
            await ctx.send(f"⚠️ Falta RAW del cap {cap} de {obra}")

# =========================
# HIATUS
# =========================
@bot.command()
async def hiatus(ctx, *, obra):
    data = cargar(ARCHIVO_HIATUS, [])
    if obra not in data:
        data.append(obra)
        guardar(ARCHIVO_HIATUS, data)
        await ctx.send(f"🔕 {obra} en hiatus")

@bot.command()
async def reactivar(ctx, *, obra):
    data = cargar(ARCHIVO_HIATUS, [])
    if obra in data:
        data.remove(obra)
        guardar(ARCHIVO_HIATUS, data)
        await ctx.send(f"🔔 {obra} reactivada")

# =========================
# SOLO
# =========================
@bot.command()
async def solo(ctx, *, obra):
    data = cargar(ARCHIVO_SOLO, [])
    if obra not in data:
        data.append(obra)
        guardar(ARCHIVO_SOLO, data)
        await ctx.send(f"🧍 {obra} en modo SOLO")

@bot.command()
async def reactivar_solo(ctx, *, obra):
    data = cargar(ARCHIVO_SOLO, [])
    if obra in data:
        data.remove(obra)
        guardar(ARCHIVO_SOLO, data)
        await ctx.send(f"🔔 {obra} salió de SOLO")

# =========================
# CALENDARIO UNIVERSAL
# =========================
@bot.command()
async def agregar_obra(ctx, obra, valor):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    valor = valor.lower().replace(" ", "")

    if all(x.isdigit() for x in valor.replace(",", "")):
        dias_lista = [int(x) for x in valor.split(",")]
        cal[obra] = {"tipo": "mes", "valor": dias_lista}
        guardar(ARCHIVO_CALENDARIO, cal)
        await ctx.send(f"📆 {obra} asignada a los días {', '.join(map(str, dias_lista))}")
        return

    if "," in valor:
        dias = valor.split(",")
        for d in dias:
            if d not in DIAS_VALIDOS:
                await ctx.send("❌ Día inválido.")
                return
        cal[obra] = {"tipo": "semana_multiple", "valor": dias}
        guardar(ARCHIVO_CALENDARIO, cal)
        await ctx.send(f"📅 {obra} asignada a {', '.join(dias)}")
        return

    if valor in DIAS_VALIDOS:
        cal[obra] = {"tipo": "semana", "valor": valor}
        guardar(ARCHIVO_CALENDARIO, cal)
        await ctx.send(f"📅 {obra} asignada a cada {valor}")
        return

    await ctx.send("❌ Formato inválido.")

@bot.command()
async def calendario(ctx):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    texto = "📅 CALENDARIO:\n"
    for obra, datos in cal.items():
        texto += f"- {obra} → {datos}\n"
    await ctx.send(texto)

# =========================
# HOY Y MAÑANA
# =========================
@bot.command()
async def hoy(ctx):
    obras = obras_por_fecha(datetime.date.today())
    await ctx.send("📅 HOY:\n" + "\n".join(obras) if obras else "📭 Hoy no hay obras")

@bot.command()
async def mañana(ctx):
    obras = obras_por_fecha(datetime.date.today() + datetime.timedelta(days=1))
    await ctx.send("📅 MAÑANA:\n" + "\n".join(obras) if obras else "📭 Mañana no hay obras")

# =========================
# AUTOMÁTICO 6 AM / 6 PM + DOMINGO
# =========================
@tasks.loop(minutes=1)
async def chequeo_automatico():
    ahora = datetime.datetime.now()
    if ahora.minute == 0 and ahora.hour in [6, 18]:
        canal = bot.guilds[0].text_channels[0]

        raws = detectar_raw()
        for obra, cap in raws:
            await canal.send(f"⚠️ Falta RAW del cap {cap} de {obra}")

        # DOMINGO 6 PM → RESUMEN SEMANAL
        if ahora.weekday() == 6 and ahora.hour == 18:
            obras_semana = []
            for i in range(7):
                obras_semana += obras_por_fecha(datetime.date.today() + datetime.timedelta(days=i))

            await canal.send(
                f"📊 **RESUMEN SEMANAL**\n"
                f"⚠️ RAW pendientes: {len(raws)}\n"
                f"📅 Obras esta semana:\n" + "\n".join(f"- {o}" for o in set(obras_semana))
            )

# =========================
# INICIAR TODO
# =========================
mantener_vivo()
bot.run(DISCORD_TOKEN)