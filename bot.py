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
    """Responde donde se llamó el comando (DM o servidor)."""
    await ctx.send(msg)

async def enviar_dm(msg: str):
    """Envía DM directamente a la dueña (OWNER_ID)."""
    user = await bot.fetch_user(OWNER_ID)
    await user.send(msg)

# =========================
# ALIAS DE OBRAS
# =========================
def resolver_obra(nombre_entrada: str) -> str:
    """
    Si 'nombre_entrada' es alias, devuelve el nombre real.
    Si no es alias, lo devuelve igual.
    """
    alias = cargar(ARCHIVO_ALIAS, {})
    return alias.get(nombre_entrada, nombre_entrada)

@bot.command()
async def alias(ctx, corto, *, completo):
    """
    Registrar alias:
    !alias director el-director-de-produccion-basura-tiene-que-sobrevivir-como-idol
    Luego podrás usar solo 'director' en todos los demás comandos.
    """
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
    """Ver si el bot está vivo."""
    await responder(ctx, "pong 🏓")

@bot.command()
async def raw_pendientes(ctx):
    """Ver solo el RAW que falta (siguiente cap) de cada obra."""
    raws = detectar_raw()
    if not raws:
        await responder(ctx, "✅ Todos los siguientes capítulos ya tienen RAW.")
    else:
        msg = "⚠️ RAW PENDIENTES:\n"
        for obra, cap in raws:
            msg += f"- {obra} cap {cap}\n"
        await responder(ctx, msg)

# =========================
# HIATUS
# =========================
@bot.command()
async def hiatus(ctx, *, obra):
    """Pausar una obra."""
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
    """Reactivar una obra en hiatus."""
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
    """Ver lista de obras pausadas."""
    data = cargar(ARCHIVO_HIATUS, [])
    if not data:
        await responder(ctx, "✅ No hay obras en hiatus.")
    else:
        msg = "🔕 OBRAS EN HIATUS:\n" + "\n".join(f"- {o}" for o in data)
        await responder(ctx, msg)

# =========================
# SOLO (OBRAS QUE HACES TÚ SOLA)
# =========================
@bot.command()
async def solo(ctx, *, obra):
    """Marcar obra como solo tuya."""
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
    """Quitar modo solo de una obra."""
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
    """Ver obras que haces solo tú."""
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
    """
    datos = {"tipo": "...", "valor": ...}
    Lo convierte en texto corto y bonito.
    """
    tipo = datos.get("tipo")
    valor = datos.get("valor")

    if tipo == "semana":
        return str(valor)
    if tipo == "semana_multiple":
        return ", ".join(valor)
    if tipo == "mes":
        return ", ".join(str(x) for x in valor)
    # fallback
    return str(datos)

@bot.command()
async def agregar_obra(ctx, obra, *, valor):
    """
    Asignar día de subida.
    Ejemplos:
    !agregar_obra yang-ilwoo-y-yo miércoles
    !agregar_obra director lunes, jueves
    !agregar_obra director 4,14,24
    """
    obra = resolver_obra(obra)
    cal = cargar(ARCHIVO_CALENDARIO, {})
    valor = valor.lower().replace(" ", "")

    # Solo números y comas → días del mes
    if all(ch.isdigit() or ch == "," for ch in valor):
        dias = [int(x) for x in valor.split(",") if x]
        cal[obra] = {"tipo": "mes", "valor": dias}
        guardar(ARCHIVO_CALENDARIO, cal)
        bonito = formatear_calendario_item(cal[obra])
        await responder(ctx, f"📆 {obra} → {bonito}")
        return

    # Varios días de la semana: lunes,viernes,domingo
    if "," in valor:
        dias = valor.split(",")
        for d in dias:
            if d not in DIAS_VALIDOS:
                await responder(ctx, "❌ Día inválido. Usa cosas como: lunes, martes, miércoles...")
                return
        cal[obra] = {"tipo": "semana_multiple", "valor": dias}
        guardar(ARCHIVO_CALENDARIO, cal)
        bonito = formatear_calendario_item(cal[obra])
        await responder(ctx, f"📅 {obra} → {bonito}")
        return

    # Un solo día de semana
    if valor in DIAS_VALIDOS:
        cal[obra] = {"tipo": "semana", "valor": valor}
        guardar(ARCHIVO_CALENDARIO, cal)
        bonito = formatear_calendario_item(cal[obra])
        await responder(ctx, f"📅 {obra} → {bonito}")
        return

    await responder(ctx, "❌ Formato inválido. Ejemplo: lunes / lunes,viernes / 4,14,24")

@bot.command()
async def cambiar_dia(ctx, obra, *, nuevo_valor):
    """
    Cambiar el día o días de subida de una obra.
    Usa el mismo formato que agregar_obra.
    """
    obra = resolver_obra(obra)
    cal = cargar(ARCHIVO_CALENDARIO, {})
    if obra not in cal:
        await responder(ctx, "❌ Esa obra no está en el calendario.")
        return
    # Reutilizamos la lógica de agregar_obra
    ctx.message.content = f"!agregar_obra {obra} {nuevo_valor}"
    await agregar_obra(ctx, obra, valor=nuevo_valor)

@bot.command()
async def eliminar_obra(ctx, *, obra):
    """Eliminar una obra del calendario."""
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
    """Ver calendario de subida en formato corto."""
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
    """Ver lo que toca hoy según el calendario."""
    # Usamos fecha de Perú (UTC-5)
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
    """Ver lo que toca mañana según el calendario."""
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
    """
    Asignar plazo:
    !asignar_plazo director 7 maria 2025-12-10
    (fecha en formato YYYY-MM-DD)
    """
    obra = resolver_obra(obra)
    data = cargar(ARCHIVO_PLAZOS, {})
    data.setdefault(obra, {})
    data[obra][cap] = {"persona": persona, "fecha": fecha}
    guardar(ARCHIVO_PLAZOS, data)
    await responder(ctx, f"✅ Plazo asignado: {obra} cap {cap} → {persona} hasta {fecha}")

@bot.command()
async def eliminar_plazo(ctx, obra, cap):
    """Borrar un plazo concreto."""
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
    """Ver atrasos según la fecha límite asignada."""
    data = cargar(ARCHIVO_PLAZOS, {})
    if not data:
        await responder(ctx, "✅ No hay plazos registrados.")
        return

    # Fecha de hoy en Perú
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
# RECORDATORIOS AUTOMÁTICOS (HORARIO PERÚ)
# =========================
@tasks.loop(minutes=1)
async def chequeo_automatico():
    # Hora de Perú = UTC - 5
    ahora_peru = datetime.datetime.utcnow() - datetime.timedelta(hours=5)

    # 6 AM y 6 PM (hora Perú)
    if ahora_peru.minute == 0 and ahora_peru.hour in [6, 18]:
        raws = detectar_raw()
        if raws:
            await enviar_dm("⚠️ RAW PENDIENTES:")
            for obra, cap in raws:
                await enviar_dm(f"- {obra} cap {cap}")
        else:
            await enviar_dm("✅ No hay RAW pendientes.")

        # Domingo 6 PM → resumen semanal
        if ahora_peru.weekday() == 6 and ahora_peru.hour == 18:
            await enviar_dm("📊 RESUMEN SEMANAL")
            await enviar_dm(f"RAW pendientes: {len(raws)}")

# =========================
# INICIO
# =========================
mantener_vivo()
bot.run(DISCORD_TOKEN)
