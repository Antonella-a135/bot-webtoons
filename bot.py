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
ARCHIVO_ALIAS = "alias.json"

TRAD = {
    "monday": "lunes", "tuesday": "martes", "wednesday": "miércoles",
    "thursday": "jueves", "friday": "viernes",
    "saturday": "sábado", "sunday": "domingo"
}
DIAS_VALIDOS = list(TRAD.values())

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
    Thread(target=run_web, daemon=True).start()

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
    await ctx.send(msg)

async def enviar_dm(msg):
    user = await bot.fetch_user(OWNER_ID)
    await user.send(msg)

def resolver_obra(nombre):
    alias = cargar(ARCHIVO_ALIAS, {})
    return alias.get(nombre, nombre)

# =========================
# ALIAS
# =========================
@bot.command()
async def alias(ctx, corto, *, completo):
    data = cargar(ARCHIVO_ALIAS, {})
    data[corto] = completo
    guardar(ARCHIVO_ALIAS, data)
    await responder(ctx, f"✅ Alias agregado: {corto} → {completo}")

@bot.command()
async def ver_alias(ctx):
    data = cargar(ARCHIVO_ALIAS, {})
    if not data:
        await responder(ctx, "📂 No hay alias.")
        return
    msg = "📂 ALIAS:\n"
    for k, v in data.items():
        msg += f"- {k} → {v}\n"
    await responder(ctx, msg)

# =========================
# RAW
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
        headers = [h.lower() for h in datos[1]]

        idx_raw = headers.index("raw subida")
        idx_temple = headers.index("subido a temple")

        for fila in datos[2:]:
            if fila[idx_temple] != "✅":
                if fila[idx_raw] != "✅":
                    avisos.append((nombre, fila[0]))
                break
    return avisos

@bot.command()
async def raw_pendientes(ctx):
    raws = detectar_raw()
    if not raws:
        await responder(ctx, "✅ Todos los RAW están listos.")
    else:
        msg = "⚠️ RAW PENDIENTES:\n"
        for o, c in raws:
            msg += f"- {o} cap {c}\n"
        await responder(ctx, msg)

# =========================
# VER ESTADO
# =========================
@bot.command()
async def ver_estado(ctx, obra, cap):
    obra = resolver_obra(obra)
    hoja = sh.worksheet(obra)
    datos = hoja.get_all_values()
    headers = [h.lower() for h in datos[1]]

    col_raw = headers.index("raw subida")
    col_trad = headers.index("trad. listo")
    col_clean = headers.index("clean listo")
    col_type = headers.index("type listo")
    col_temple = headers.index("subido a temple")

    fila = next((f for f in datos[2:] if f[0] == cap), None)
    if not fila:
        await responder(ctx, "❌ Capítulo no encontrado.")
        return

    def e(v): return "✅" if v == "✅" else "⏳"

    msg = f"📊 ESTADO {obra} cap {cap}\n"
    msg += f"{e(fila[col_raw])} RAW\n"
    msg += f"{e(fila[col_trad])} Traducción\n"
    msg += f"{e(fila[col_clean])} Clean\n"
    msg += f"{e(fila[col_type])} Type\n"
    msg += f"{e(fila[col_temple])} Temple\n"
    await responder(ctx, msg)

# =========================
# HIATUS / SOLO
# =========================
@bot.command()
async def hiatus(ctx, *, obra):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_HIATUS, [])
    if obra not in data:
        data.append(obra)
        guardar(ARCHIVO_HIATUS, data)
    await responder(ctx, f"🔕 {obra} en hiatus")

@bot.command()
async def reactivar(ctx, *, obra):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_HIATUS, [])
    if obra in data:
        data.remove(obra); guardar(ARCHIVO_HIATUS, data)
    await responder(ctx, f"🔔 {obra} reactivada")

@bot.command()
async def ver_hiatus(ctx):
    data = cargar(ARCHIVO_HIATUS, [])
    await responder(ctx, "🔕 HIATUS:\n" + "\n".join(data) if data else "✅ Sin hiatus")

@bot.command()
async def solo(ctx, *, obra):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_SOLO, [])
    if obra not in data:
        data.append(obra); guardar(ARCHIVO_SOLO, data)
    await responder(ctx, f"🧍 {obra} en SOLO")

@bot.command()
async def reactivar_solo(ctx, *, obra):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_SOLO, [])
    if obra in data:
        data.remove(obra); guardar(ARCHIVO_SOLO, data)
    await responder(ctx, f"✅ {obra} ya no es SOLO")

@bot.command()
async def ver_solo(ctx):
    data = cargar(ARCHIVO_SOLO, [])
    await responder(ctx, "🧍 SOLO:\n" + "\n".join(data) if data else "✅ Sin obras solo")

# =========================
# CALENDARIO
# =========================
@bot.command()
async def agregar_obra(ctx, obra, *, valor):
    obra = resolver_obra(obra)
    cal = cargar(ARCHIVO_CALENDARIO, {})
    valor = valor.lower().replace(" ", "")

    if all(x.isdigit() or x == "," for x in valor):
        cal[obra] = {"tipo": "mes", "valor": [int(i) for i in valor.split(",")]}
    elif "," in valor:
        cal[obra] = {"tipo": "semana_multiple", "valor": valor.split(",")}
    else:
        cal[obra] = {"tipo": "semana", "valor": valor}

    guardar(ARCHIVO_CALENDARIO, cal)
    await responder(ctx, f"📅 {obra} agregada al calendario")

@bot.command()
async def cambiar_dia(ctx, obra, *, nuevo):
    ctx.message.content = f"!agregar_obra {obra} {nuevo}"
    await agregar_obra(ctx, obra, valor=nuevo)

@bot.command()
async def eliminar_obra(ctx, *, obra):
    obra = resolver_obra(obra)
    cal = cargar(ARCHIVO_CALENDARIO, {})
    if obra in cal:
        del cal[obra]; guardar(ARCHIVO_CALENDARIO, cal)
    await responder(ctx, f"🗑️ {obra} eliminada del calendario")

@bot.command()
async def calendario(ctx):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    if not cal:
        await responder(ctx, "📅 Calendario vacío.")
        return
    msg = "📅 CALENDARIO:\n"
    for o, d in cal.items():
        msg += f"- {o} → {d['valor']}\n"
    await responder(ctx, msg)

# =========================
# HOY / MAÑANA
# =========================
def obras_por_fecha(fecha):
    cal = cargar(ARCHIVO_CALENDARIO, {})
    dia_sem = TRAD.get(fecha.strftime("%A").lower(), "")
    dia_mes = fecha.day
    r = []
    for o, d in cal.items():
        if d["tipo"] == "semana" and d["valor"] == dia_sem: r.append(o)
        if d["tipo"] == "semana_multiple" and dia_sem in d["valor"]: r.append(o)
        if d["tipo"] == "mes" and dia_mes in d["valor"]: r.append(o)
    return r

@bot.command()
async def hoy(ctx):
    f = (datetime.datetime.utcnow() - datetime.timedelta(hours=5)).date()
    r = obras_por_fecha(f)
    await responder(ctx, "📅 HOY:\n" + "\n".join(r) if r else "📭 Hoy no hay obras.")

@bot.command()
async def mañana(ctx):
    f = (datetime.datetime.utcnow() - datetime.timedelta(hours=5) + datetime.timedelta(days=1)).date()
    r = obras_por_fecha(f)
    await responder(ctx, "📅 MAÑANA:\n" + "\n".join(r) if r else "📭 Mañana no hay obras.")

# =========================
# PLAZOS
# =========================
@bot.command()
async def asignar_plazo(ctx, obra, cap, persona, fecha):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_PLAZOS, {})
    data.setdefault(obra, {})
    data[obra][cap] = {"persona": persona, "fecha": fecha}
    guardar(ARCHIVO_PLAZOS, data)
    await responder(ctx, "✅ Plazo asignado")

@bot.command()
async def eliminar_plazo(ctx, obra, cap):
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_PLAZOS, {})
    try:
        del data[obra][cap]; guardar(ARCHIVO_PLAZOS, data)
        await responder(ctx, "🗑️ Plazo eliminado")
    except:
        await responder(ctx, "❌ No existe ese plazo")

@bot.command()
async def ver_atrasos(ctx):
    data = cargar(ARCHIVO_PLAZOS, {})
    hoy = (datetime.datetime.utcnow() - datetime.timedelta(hours=5)).date()
    r = []
    for o, caps in data.items():
        for c, info in caps.items():
            f = datetime.datetime.strptime(info["fecha"], "%Y-%m-%d").date()
            if hoy > f:
                r.append(f"{o} cap {c} → {info['persona']}")
    await responder(ctx, "⏰ ATRASOS:\n" + "\n".join(r) if r else "✅ Sin atrasos.")

# =========================
# COMANDOS
# =========================
@bot.command()
async def comandos(ctx):
    await responder(ctx, """
!ping → Ver si el bot está activo.
!raw_pendientes → Ver RAW faltante.
!ver_estado obra cap → Ver qué falta en un capítulo.
!hiatus obra → Pausar obra.
!reactivar obra → Reactivar obra.
!ver_hiatus → Ver pausadas.
!solo obra → Modo solo.
!reactivar_solo obra → Quitar modo solo.
!ver_solo → Ver obras solo.
!agregar_obra obra día → Agregar calendario.
!cambiar_dia obra día → Cambiar día.
!eliminar_obra obra → Quitar del calendario.
!calendario → Ver calendario.
!hoy → Ver hoy.
!mañana → Ver mañana.
!asignar_plazo obra cap persona fecha → Asignar plazo.
!eliminar_plazo obra cap → Borrar plazo.
!ver_atrasos → Ver atrasos.
!alias corto nombre → Crear alias.
!ver_alias → Ver alias.
!comandos → Ver esta lista.
""")

# =========================
# RECORDATORIOS
# =========================
@tasks.loop(minutes=1)
async def chequeo_automatico():
    ahora = datetime.datetime.utcnow() - datetime.timedelta(hours=5)
    if ahora.minute == 0 and ahora.hour in [6, 18]:
        r = detectar_raw()
        if r:
            for o, c in r:
                await enviar_dm(f"⚠️ RAW pendiente: {o} cap {c}")
        if ahora.weekday() == 6 and ahora.hour == 18:
            await enviar_dm("📊 Resumen semanal enviado.")

@bot.command()
async def ping(ctx):
    await responder(ctx, "pong 🏓")

@bot.event
async def on_ready():
    chequeo_automatico.start()
    print("✅ Bot completo restaurado y activo")

mantener_vivo()
bot.run(DISCORD_TOKEN)
