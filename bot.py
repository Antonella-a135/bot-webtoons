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

        idx_raw = idx_temple = None
        for i, c in enumerate(encabezados):
            if "raw" in c:
                idx_raw = i
            if "temple" in c:
                idx_temple = i

        if idx_raw is None or idx_temple is None:
            continue

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
    print("✅ Bot DEFINITIVO activo 24/7 (horario Perú)")
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
# VER ESTADO (NUEVO)
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

    fila = next((f for f in datos[2:] if f[0] == cap), None)

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
# COMANDOS (NUEVO)
# =========================
@bot.command()
async def comandos(ctx):
    await responder(ctx, """
📌 COMANDOS DEL BOT

!ping → Ver si el bot está activo.

!raw_pendientes → Ver el siguiente capítulo que falta RAW de cada obra.

!hiatus obra → Poner una obra en pausa.

!reactivar obra → Quitar la obra del hiatus.

!ver_hiatus → Ver todas las obras pausadas.

!solo obra → Marcar una obra como solo tuya.

!reactivar_solo obra → Quitar el modo solo.

!ver_solo → Ver obras en modo solo.

!agregar_obra obra día → Asignar día(s) de subida.

!calendario → Ver calendario completo.

!cambiar_dia obra día → Cambiar día de subida.

!eliminar_obra obra → Eliminar obra del calendario.

!asignar_plazo obra cap persona fecha → Asignar plazo.

!eliminar_plazo obra cap → Borrar un plazo.

!ver_atrasos → Ver atrasos.

!hoy → Ver lo de hoy.

!mañana → Ver lo de mañana.

!alias corto nombre → Crear alias.

!ver_alias → Ver alias registrados.

!ver_estado obra cap → Ver qué falta en ese capítulo.

!comandos → Ver esta lista completa.
""")

# =========================
# RECORDATORIOS AUTOMÁTICOS
# =========================
@tasks.loop(minutes=1)
async def chequeo_automatico():
    ahora_peru = datetime.datetime.utcnow() - datetime.timedelta(hours=5)

    if ahora_peru.minute == 0 and ahora_peru.hour in [6, 18]:
        raws = detectar_raw()
        if raws:
            await enviar_dm("⚠️ RAW PENDIENTES:")
            for obra, cap in raws:
                await enviar_dm(f"- {obra} cap {cap}")
        else:
            await enviar_dm("✅ No hay RAW pendientes.")

        if ahora_peru.weekday() == 6 and ahora_peru.hour == 18:
            await enviar_dm("📊 RESUMEN SEMANAL")
            await enviar_dm(f"RAW pendientes: {len(raws)}")

# =========================
# INICIO
# =========================
mantener_vivo()
bot.run(DISCORD_TOKEN)
