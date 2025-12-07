import discord
from discord.ext import commands, tasks
import gspread
import json
import datetime
import os

# ✅ DESPERTADOR WEB
from flask import Flask
from threading import Thread

# =========================
# CONFIGURACIÓN DESDE RENDER
# =========================
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GOOGLE_SHEETS_URL = os.environ.get("GOOGLE_SHEETS_URL")
GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")

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
# SERVIDOR WEB
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
# READY
# =========================
@bot.event
async def on_ready():
    print("✅ Bot conectado 24/7")
    chequeo_automatico.start()

# =========================
# COMANDOS
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
# AUTOMÁTICO 6 AM Y 6 PM
# =========================
@tasks.loop(minutes=1)
async def chequeo_automatico():
    ahora = datetime.datetime.now()
    if ahora.minute == 0 and ahora.hour in [6, 18]:
        canal = bot.guilds[0].text_channels[0]
        for obra, cap in detectar_raw():
            await canal.send(f"⚠️ Falta RAW del cap {cap} de {obra}")

# =========================
# INICIAR TODO
# =========================
mantener_vivo()
bot.run(DISCORD_TOKEN)

