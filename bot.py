#========================= 
# IMPORTS
# =========================

import discord
from discord.ext import commands
from discord import app_commands

import gspread
import json
import os
import datetime

from flask import Flask
from threading import Thread
from oauth2client.service_account import ServiceAccountCredentials

import sys
import time

# =========================
# VARIABLES DE ENTORNO
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
OWNER_ID = int(OWNER_ID) if OWNER_ID else None

SHEET_PRINCIPAL_ID = "1dnxFvU6wnkIkUhCUoK9Vr_TGtPrnOFdzAnA9pvWn8gY"
SHEET_CONFIG_ID = "1ID3c9Qz0vmqZA0JW8P_Pu9OfCn6gc7VHTRZms3gsdqQ"


# =========================
# DISCORD BOT
# =========================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

tree = bot.tree

# =========================
# SERVIDOR 24/7 (ANTI-SLEEP)
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot activo"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# =========================
# CACHEA
# =========================

obras_cache = []
alias_cache = {}

# =========================
# GOOGLE SHEETS
# =========================

def conectar_sheets():

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    credentials_str = os.getenv("GOOGLE_CREDENTIALS")

    if not credentials_str:
        raise Exception("GOOGLE_CREDENTIALS no está configurado")

    credentials_json = json.loads(credentials_str)

    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        credentials_json,
        scope
    )

    client = gspread.authorize(creds)

    sheet_principal = client.open_by_key(SHEET_PRINCIPAL_ID)
    sheet_config = client.open_by_key(SHEET_CONFIG_ID)

    return sheet_principal, sheet_config

# =========================
# CARGAR OBRAS Y ALIAS
# =========================

def cargar_config():

    global obras_cache
    global alias_cache

    sheet_principal, sheet_config = conectar_sheets()

    obras_sheet = sheet_config.worksheet("OBRAS")
    alias_sheet = sheet_config.worksheet("ALIAS")

    obras = obras_sheet.get_all_records()
    alias = alias_sheet.get_all_records()

    obras_cache = [o["obra"] for o in obras]

    alias_cache = {}

    for a in alias:
        alias_cache[a["alias"].lower()] = a["obra"]

# =========================
# RESOLVER ALIAS
# =========================

def resolver_alias(nombre):

    nombre_lower = nombre.lower()

    if nombre_lower in alias_cache:
        return alias_cache[nombre_lower]

    return nombre

# =========================
# BUSCAR RAW PENDIENTE
# =========================

def buscar_raw_pendiente(obra):

    sheet_principal, _ = conectar_sheets()

    try:
        ws = sheet_principal.worksheet(obra)
    except Exception:
        return None, "❌ No se encontró la pestaña de esa obra."

    data = ws.get_all_records(head=2)

    ultimo_pendiente = None

    for fila in data:

        cap = fila.get("Cap.")
        raw = fila.get("Raw Subida")

        if raw in ["❌", "x", "X", "", None]:

            ultimo_pendiente = cap

    if ultimo_pendiente is None:
        return None, "✅ Todas las RAW están subidas."

    return ultimo_pendiente, None

# =========================
# BUSCAR ESTADO DE OBRA
# =========================

def buscar_estado_obra(obra):

    sheet_principal, _ = conectar_sheets()

    try:
        ws = sheet_principal.worksheet(obra)
    except Exception:
        return None, None, "❌ No se encontró la pestaña de esa obra."

    data = ws.get_all_records(head=2)

    ultimo_cap = 0
    ultima_tarea = None

    for fila in data:

        cap = fila.get("Cap.")

        if not cap:
            continue

        try:
            cap = int(cap)
        except:
            continue

        trad_listo = fila.get("Trad. Listo")
        clean_listo = fila.get("Clean Listo")
        type_listo = fila.get("Type Listo")
        temple = fila.get("Subido a Temple")

        pendiente = None

        if trad_listo in ["❌", "", None]:
            pendiente = "Traducción"

        elif clean_listo in ["❌", "", None]:
            pendiente = "Cleaning"

        elif type_listo in ["❌", "", None]:
            pendiente = "Typesetting"

        elif temple in ["❌", "", None]:
            pendiente = "Subir a Temple"

        if pendiente:

            if cap >= ultimo_cap:

                ultimo_cap = cap
                ultima_tarea = pendiente

    if not ultima_tarea:
        return None, None, "✅ La obra está completamente al día."

    return ultimo_cap, ultima_tarea, None

# =========================
# OBTENER SHEET PLAZOS
# =========================

def obtener_sheet_plazos():

    _, sheet_config = conectar_sheets()

    return sheet_config.worksheet("PLAZOS")

# =========================
# VER ALIAS
# =========================

def ver_alias():

    _, sheet_config = conectar_sheets()

    ws = sheet_config.worksheet("ALIAS")

    data = ws.get_all_records()

    if not data:
        return "No hay alias registrados."

    texto = ""

    for fila in data:

        obra = fila.get("obra")
        alias = fila.get("alias")

        texto += f"{alias} → {obra}\n"

    return texto

# =========================
# AGREGAR ALIAS
# =========================

def agregar_alias(obra, alias):

    _, sheet_config = conectar_sheets()

    ws = sheet_config.worksheet("ALIAS")

    ws.append_row([
        obra,
        alias
    ])

    cargar_config()

# =========================
# ELIMINAR ALIAS
# =========================

def eliminar_alias(alias):

    _, sheet_config = conectar_sheets()

    ws = sheet_config.worksheet("ALIAS")

    data = ws.get_all_records()

    for i, fila in enumerate(data, start=2):

        if fila.get("alias").lower() == alias.lower():

            ws.delete_rows(i)

            cargar_config()

            return True

    return False

# =========================
# AGREGAR PLAZO
# =========================

def agregar_plazo(obra, cap, tarea, usuario, fecha):

    ws = obtener_sheet_plazos()

    ws.append_row([
        obra,
        cap,
        tarea,
        usuario,
        fecha,
        "pendiente"
    ])

# =========================
# ELIMINAR PLAZO
# =========================

def eliminar_plazo(obra, cap, tarea):

    ws = obtener_sheet_plazos()

    data = ws.get_all_records()

    for i, fila in enumerate(data, start=2):

        if (
            fila["obra"] == obra
            and str(fila["cap"]) == str(cap)
            and fila["tarea"] == tarea
        ):

            ws.delete_rows(i)
            return True

    return False

# =========================
# TERMINAR PLAZO
# =========================

def terminar_plazo(obra, cap, tarea):

    ws = obtener_sheet_plazos()

    data = ws.get_all_records()

    for i, fila in enumerate(data, start=2):

        if (
            fila["obra"] == obra
            and str(fila["cap"]) == str(cap)
            and fila["tarea"] == tarea
        ):

            ws.update_cell(i, 6, "terminado")
            return True

    return False

# =========================
# VER PLAZOS ATRASADOS
# =========================

def ver_atrasos():

    ws = obtener_sheet_plazos()

    data = ws.get_all_records()

    hoy = datetime.date.today()

    atrasos = []

    for fila in data:

        if fila["estado"] != "pendiente":
            continue

        fecha = datetime.datetime.strptime(
            fila["plazo"],
            "%Y-%m-%d"
        ).date()

        if fecha < hoy:

            atrasos.append(
                f'{fila["obra"]} Cap {fila["cap"]} — {fila["tarea"]}'
            )

    return atrasos

# =========================
# CAMBIAR ESTADO OBRA
# =========================

def cambiar_estado_obra(obra, estado):

    _, sheet_config = conectar_sheets()

    ws = sheet_config.worksheet("OBRAS")

    data = ws.get_all_records()

    for i, fila in enumerate(data, start=2):

        if fila["obra"] == obra:

            ws.update_cell(i, 3, estado)

            return True

    return False

# =========================
# VER CALENDARIO
# =========================

def ver_calendario():

    _, sheet_config = conectar_sheets()

    ws = sheet_config.worksheet("OBRAS")

    data = ws.get_all_records()

    if not data:
        return "No hay obras registradas."

    texto = ""

    for fila in data:

        obra = fila.get("obra")
        dia = fila.get("dia")
        estado = fila.get("estado")

        texto += f"{obra} — {dia} ({estado})\n"

    return texto

# =========================
# AGREGAR OBRA
# =========================

def agregar_obra(obra, dia):

    sheet_principal, sheet_config = conectar_sheets()

    ws_config = sheet_config.worksheet("OBRAS")

    ws_config.append_row([
        obra,
        dia,
        "activo"
    ])

    try:

        sheet_principal.worksheet(obra)

        print("⚠️ La pestaña ya existe")

    except:

        sheet_principal.add_worksheet(
            title=obra,
            rows=300,
            cols=12
        )

        ws = sheet_principal.worksheet(obra)

        ws.append_row([""] * 12)

        ws.append_row([
            "Cap.",
            "Raw Subida",
            "Traductor",
            "Usuario asig.",
            "Trad. Listo",
            "Cleaner",
            "Usuario asig.",
            "Clean Listo",
            "Typer",
            "Usuario asig.",
            "Type Listo",
            "Subido a Temple"
        ])

    cargar_config()

# =========================
# CAMBIAR DIA
# =========================

def cambiar_dia_obra(obra, dia):

    _, sheet_config = conectar_sheets()

    ws = sheet_config.worksheet("OBRAS")

    data = ws.get_all_records()

    for i, fila in enumerate(data, start=2):

        if fila["obra"] == obra:

            ws.update_cell(i, 2, dia)

            return True

    return False

# =========================
# ELIMINAR OBRA
# =========================

def eliminar_obra(obra):

    _, sheet_config = conectar_sheets()

    ws = sheet_config.worksheet("OBRAS")

    data = ws.get_all_records()

    for i, fila in enumerate(data, start=2):

        if fila["obra"] == obra:

            ws.delete_rows(i)

            cargar_config()

            return True

    return False


# =========================
# DIA ACTU
# =========================

def obras_por_dia(dia):

    _, sheet_config = conectar_sheets()

    ws = sheet_config.worksheet("OBRAS")

    data = ws.get_all_records()

    lista = []

    for fila in data:

        dia_sheet = fila.get("dia")
        estado = fila.get("estado")

        if not dia_sheet:
            continue

        if dia_sheet.lower() == dia.lower() and estado == "activo":

            lista.append(fila.get("obra"))

    return lista

# =========================
# CREDITOS
# =========================

def obtener_creditos_cap(obra, cap):

    sheet_principal, _ = conectar_sheets()

    try:
        ws = sheet_principal.worksheet(obra)
    except Exception:
        return None, "❌ No se encontró la obra."

    data = ws.get_all_records(head=2)

    for fila in data:

        if str(fila.get("Cap.")) == str(cap):

            traductor = fila.get("Usuario asig.")
            cleaner = fila.get("Usuario asig._1")
            typer = fila.get("Usuario asig._2")

            return {
                "traductor": traductor,
                "cleaner": cleaner,
                "typer": typer
            }, None

    return None, "❌ No se encontró ese capítulo."

# =========================
# MARCAR TAREA EN OBRA
# =========================

def marcar_asignacion_obra(obra, cap, tarea, usuario):

    sheet_principal, _ = conectar_sheets()

    try:
        ws = sheet_principal.worksheet(obra)
    except Exception:
        return

    data = ws.get_all_records(head=2)

    fila_index = None

    for i, fila in enumerate(data, start=3):

        if str(fila.get("Cap.")) == str(cap):
            fila_index = i
            break

    if not fila_index:
        return

    if tarea.lower() == "traductor":

        ws.update(f"C{fila_index}", "✅")
        ws.update(f"D{fila_index}", usuario)

    elif tarea.lower() == "cleaner":

        ws.update(f"F{fila_index}", "✅")
        ws.update(f"G{fila_index}", usuario)

    elif tarea.lower() == "typer":

        ws.update(f"I{fila_index}", "✅")
        ws.update(f"J{fila_index}", usuario)


# =========================
# MARCAR TAREA TERMINADA
# =========================

def marcar_terminado_obra(obra, cap, tarea):

    sheet_principal, _ = conectar_sheets()

    try:
        ws = sheet_principal.worksheet(obra)
    except Exception:
        return

    data = ws.get_all_records(head=2)

    fila_index = None

    for i, fila in enumerate(data, start=3):

        if str(fila.get("Cap.")) == str(cap):
            fila_index = i
            break

    if not fila_index:
        return

    if tarea.lower() == "traductor":

        ws.update(f"E{fila_index}", "✅")

    elif tarea.lower() == "cleaner":

        ws.update(f"H{fila_index}", "✅")

    elif tarea.lower() == "typer":

        ws.update(f"K{fila_index}", "✅")

# =========================
# AUTOCOMPLETADO DE OBRAS
# =========================

async def autocomplete_obras(
    interaction: discord.Interaction,
    current: str
):

    resultados = []

    for obra in obras_cache:

        if current.lower() in obra.lower():

            resultados.append(
                app_commands.Choice(
                    name=obra,
                    value=obra
                )
            )

    return resultados[:25]

# =========================
# EVENTO READY
# =========================

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")
    cargar_config()

# =========================
# UTILIDADES
# =========================

async def enviar_dm(msg):

    if OWNER_ID is None:
        return

    try:
        user = await bot.fetch_user(OWNER_ID)
        await user.send(msg)
    except Exception:
        pass


# =========================
# COMANDOS SLASH
# =========================

@tree.command(name="ping", description="Ver si el bot está activo")
async def ping(interaction: discord.Interaction):

    print("PING RECIBIDO")
    
    await interaction.response.send_message("🏓 Pong! Bot activo.")

@tree.command(name="sync_obras", description="Actualizar lista de obras y alias")
async def sync_obras(interaction: discord.Interaction):

    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ Solo el dueño puede usar este comando.",
            ephemeral=True
        )
        return

    try:

        cargar_config()

        await interaction.response.send_message(
            "✅ Obras y alias actualizados."
        )

    except Exception as e:

        await interaction.response.send_message(
            f"❌ Error actualizando obras:\n{e}"
        )

@tree.command(name="hoy", description="Ver qué obras se suben hoy")
async def hoy(interaction: discord.Interaction):

    await interaction.response.send_message(
        "📅 Comando /hoy aún no implementado."
    )


@tree.command(name="manana", description="Ver qué obras se suben mañana")
async def manana(interaction: discord.Interaction):

    await interaction.response.send_message(
        "📅 Comando /mañana aún no implementado."
    )

@tree.command(name="raw", description="Ver RAW pendientes")
@app_commands.describe(
    obra="Nombre de la obra"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def raw(
    interaction: discord.Interaction,
    obra: str
):

    obra = resolver_alias(obra)

    cap, error = buscar_raw_pendiente(obra)

    if error:

        await interaction.response.send_message(error)
        return

    await interaction.response.send_message(
        f"📦 **RAW pendiente**\n"
        f"Obra: **{obra}**\n"
        f"Último capítulo sin RAW: **{cap}**"
    )

@tree.command(name="estado", description="Ver estado de una obra")
@app_commands.describe(
    obra="Nombre o alias de la obra"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def estado(
    interaction: discord.Interaction,
    obra: str
):

    obra = resolver_alias(obra)

    await interaction.response.send_message(
        f"📊 Estado de **{obra}** aún no implementado."
    )


@tree.command(name="estado_obra", description="Ver última tarea pendiente de una obra")
@app_commands.describe(
    obra="Nombre de la obra"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def estado_obra(
    interaction: discord.Interaction,
    obra: str
):

    obra = resolver_alias(obra)

    cap, tarea, error = buscar_estado_obra(obra)

    if error:

        await interaction.response.send_message(error)
        return

    await interaction.response.send_message(
        f"📊 **Estado de obra**\n"
        f"Obra: **{obra}**\n\n"
        f"Última tarea pendiente:\n"
        f"**{tarea} — Capítulo {cap}**"
    )

@tree.command(name="plazos", description="Sistema de plazos")
@app_commands.describe(
    accion="asignar, eliminar, terminado o ver",
    obra="obra",
    cap="capitulo",
    tarea="tipo de tarea",
    usuario="usuario responsable",
    fecha="fecha YYYY-MM-DD"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def plazos(
    interaction: discord.Interaction,
    accion: str,
    obra: str = None,
    cap: int = None,
    tarea: str = None,
    usuario: str = None,
    fecha: str = None
):

    obra = resolver_alias(obra) if obra else None

    if accion == "asignar":

        if not obra or not cap or not tarea or not usuario or not fecha:

            await interaction.response.send_message(
                "❌ Debes indicar obra, cap, tarea, usuario y fecha."
            )
            return
        try:
            datetime.datetime.strptime(fecha, "%Y-%m-%d")
        except ValueError:
            await interaction.response.send_message(
                "❌ La fecha debe tener formato YYYY-MM-DD\nEjemplo: 2026-03-20"
            )
            return

        agregar_plazo(obra, cap, tarea, usuario, fecha)

        marcar_asignacion_obra(obra, cap, tarea, usuario)

        await interaction.response.send_message(
            f"⏰ Plazo asignado\n"
            f"{obra} Cap {cap} — {tarea}\n"
            f"👤 {usuario}\n"
            f"📅 {fecha}"
        )

    elif accion == "eliminar":

        if not obra or not cap or not tarea:

            await interaction.response.send_message(
                "❌ Debes indicar obra, cap y tarea."
            )
            return

        ok = eliminar_plazo(obra, cap, tarea)

        if ok:
            msg = "🗑️ Plazo eliminado"
        else:
            msg = "❌ No se encontró el plazo"

        await interaction.response.send_message(msg)

    elif accion == "terminado":

        if not obra or not cap or not tarea:

            await interaction.response.send_message(
                "❌ Debes indicar obra, cap y tarea."
            )
            return

        ok = terminar_plazo(obra, cap, tarea)

        if ok:
            marcar_terminado_obra(obra, cap, tarea)

            msg = "✅ Plazo marcado como terminado"
        else:
            msg = "❌ No se encontró el plazo"

        await interaction.response.send_message(msg)

    elif accion == "ver":

        atrasos = ver_atrasos()

        if not atrasos:

            await interaction.response.send_message(
                "✅ No hay plazos atrasados."
            )

        else:

            texto = "\n".join(atrasos)

            await interaction.response.send_message(
                f"⚠️ **Plazos atrasados**\n\n{texto}"
            )

    else:

        await interaction.response.send_message(
            "❌ Acción no válida"
        )

@tree.command(name="alias", description="Sistema de alias")
@app_commands.describe(
    accion="ver, agregar o eliminar",
    obra="obra relacionada",
    alias="alias"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def alias(
    interaction: discord.Interaction,
    accion: str,
    obra: str = None,
    alias: str = None
):

    if accion == "ver":

        texto = ver_alias()

        await interaction.response.send_message(
            f"🎭 Alias registrados:\n\n{texto}"
        )

    elif accion == "agregar":

        if not obra or not alias:

            await interaction.response.send_message(
                "❌ Debes indicar obra y alias."
            )
            return

        agregar_alias(obra, alias)

        await interaction.response.send_message(
            f"✅ Alias agregado\n{alias} → {obra}"
        )

    elif accion == "eliminar":

        if not alias:

            await interaction.response.send_message(
                "❌ Debes indicar el alias."
            )
            return

        ok = eliminar_alias(alias)

        if ok:

            msg = f"🗑️ Alias eliminado: {alias}"

        else:

            msg = "❌ No se encontró ese alias."

        await interaction.response.send_message(msg)

    else:

        await interaction.response.send_message(
            "❌ Acción inválida."
        )

@tree.command(name="modo_obra", description="Cambiar modo de una obra")
@app_commands.describe(
    obra="Nombre de la obra",
    accion="hiatus, reactivar, solo o reactivar_solo"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def modo_obra(
    interaction: discord.Interaction,
    obra: str,
    accion: str
):

    obra = resolver_alias(obra)

    estados = {
        "hiatus": "hiatus",
        "reactivar": "activo",
        "solo": "solo",
        "reactivar_solo": "activo"
    }

    if accion not in estados:

        await interaction.response.send_message(
            "❌ Acción inválida."
        )
        return

    ok = cambiar_estado_obra(obra, estados[accion])

    if not ok:

        await interaction.response.send_message(
            "❌ No se encontró la obra."
        )
        return

    await interaction.response.send_message(
        f"⚙️ Estado actualizado\n{obra} → {estados[accion]}"
    )

@tree.command(name="calendario", description="Sistema de calendario")
@app_commands.describe(
    accion="ver, agregar o cambiar",
    obra="nombre de la obra",
    dia="día de publicación"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def calendario(
    interaction: discord.Interaction,
    accion: str,
    obra: str = None,
    dia: str = None
):

    if accion == "ver":

        texto = ver_calendario()

        await interaction.response.send_message(
            f"📅 Calendario de obras\n\n{texto}"
        )

    elif accion == "agregar":

        if not obra or not dia:

            await interaction.response.send_message(
                "❌ Debes indicar obra y día."
            )
            return

        agregar_obra(obra, dia)

        await interaction.response.send_message(
            f"✅ Obra agregada\n{obra} → {dia}"
        )

    elif accion == "cambiar":

        if not obra or not dia:

            await interaction.response.send_message(
                "❌ Debes indicar obra y nuevo día."
            )
            return

        ok = cambiar_dia_obra(obra, dia)

        if ok:

            msg = f"📅 Día actualizado\n{obra} → {dia}"

        else:

            msg = "❌ No se encontró la obra."

        await interaction.response.send_message(msg)

    else:

        await interaction.response.send_message(
            "❌ Acción inválida."
        )

@tree.command(name="eliminar_obra", description="Eliminar una obra del sistema")
@app_commands.describe(
    obra="Nombre de la obra"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def eliminar_obra_cmd(
    interaction: discord.Interaction,
    obra: str
):

    obra = resolver_alias(obra)

    ok = eliminar_obra(obra)

    if ok:

        msg = f"🗑️ Obra eliminada: {obra}"

    else:

        msg = "❌ No se encontró la obra."

    await interaction.response.send_message(msg)

@tree.command(name="comandos", description="Ver lista de comandos")
async def comandos(interaction: discord.Interaction):

    texto = (
        "📜 **Comandos del bot**\n\n"
        "📅 **Publicaciones**\n"
        "/dia_actu — Obras que salen hoy o mañana\n"
        "/calendario — Ver o editar calendario\n\n"

        "📦 **Producción**\n"
        "/raw — Ver RAW pendiente\n"
        "/estado_obra — Última tarea pendiente\n"
        "/crear_caps — Crear capítulos automáticamente\n\n"

        "🎭 **Sistema**\n"
        "/alias — Gestionar alias\n"
        "/modo_obra — Cambiar estado de obra\n\n"

        "⏰ **Plazos**\n"
        "/plazos — Gestionar plazos\n\n"

        "⚙️ **Administración**\n"
        "/eliminar_obra — Eliminar obra\n"
        "/sync_obras — Recargar obras\n"
        "/ping — Ver si el bot está activo\n"
        "/creditos_cap — Ver créditos de un capítulo"
    )

    await interaction.response.send_message(texto)

@tree.command(name="dia_actu", description="Ver obras de hoy o mañana")
@app_commands.describe(dia="hoy o mañana")
async def dia_actu(interaction: discord.Interaction, dia: str):

    dias = [
        "lunes",
        "martes",
        "miercoles",
        "jueves",
        "viernes",
        "sabado",
        "domingo"
    ]

    hoy = datetime.date.today()

    if dia == "hoy":

        dia_nombre = dias[hoy.weekday()]

    elif dia == "mañana":

        manana = hoy + datetime.timedelta(days=1)
        dia_nombre = dias[manana.weekday()]

    else:

        await interaction.response.send_message(
            "❌ Usa 'hoy' o 'mañana'"
        )
        return

    obras = obras_por_dia(dia_nombre)

    if not obras:

        await interaction.response.send_message(
            f"📭 No hay obras para {dia}."
        )
        return

    texto = "\n".join(obras)

    await interaction.response.send_message(
        f"📅 Obras para {dia}:\n\n{texto}"
    )

@tree.command(name="creditos_cap", description="Ver créditos de un capítulo")
@app_commands.describe(
    obra="Nombre de la obra",
    cap="Número de capítulo"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def creditos_cap(
    interaction: discord.Interaction,
    obra: str,
    cap: int
):

    obra = resolver_alias(obra)

    creditos, error = obtener_creditos_cap(obra, cap)

    if error:

        await interaction.response.send_message(error)
        return

    trad = creditos["traductor"] or "—"
    clean = creditos["cleaner"] or "—"
    type_ = creditos["typer"] or "—"

    await interaction.response.send_message(
        f"📜 **Créditos**\n"
        f"Obra: **{obra}**\n"
        f"Capítulo: **{cap}**\n\n"
        f"Traductor: **{trad}**\n"
        f"Cleaner: **{clean}**\n"
        f"Typer: **{type_}**"
    )

# =========================
# CREAR CAPS AUTOMÁTICOS
# =========================

@tree.command(name="crear_caps", description="Crear capítulos automáticamente en una obra")
@app_commands.describe(
    obra="Nombre de la obra",
    hasta="Número máximo de capítulos a crear"
)
@app_commands.autocomplete(obra=autocomplete_obras)
async def crear_caps(
    interaction: discord.Interaction,
    obra: str,
    hasta: int
):

    obra = resolver_alias(obra)

    sheet_principal, _ = conectar_sheets()

    try:
        ws = sheet_principal.worksheet(obra)
    except Exception:

        await interaction.response.send_message(
            "❌ No se encontró la pestaña de esa obra."
        )
        return

    data = ws.get_all_records(head=2)

    caps_existentes = set()

    for fila in data:

        cap = fila.get("Cap.")

        if cap:

            try:
                caps_existentes.add(int(cap))
            except:
                pass

    nuevas_filas = []

    for cap in range(1, hasta + 1):

        if cap in caps_existentes:
            continue

        nuevas_filas.append([
            cap,
            "❌",
            "❌",
            "",
            "❌",
            "❌",
            "",
            "❌",
            "❌",
            "",
            "❌",
            "❌"
        ])

    if not nuevas_filas:

        await interaction.response.send_message(
            "✅ No hay capítulos nuevos para crear."
        )
        return

    ws.append_rows(nuevas_filas)

    await interaction.response.send_message(
        f"✅ Se agregaron **{len(nuevas_filas)} capítulos** a **{obra}**."
    )

# =========================
# INICIO BOT
# =========================

if __name__ == "__main__":

    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN no está definido.")
        sys.exit(1)

    keep_alive()

    print("🚀 Iniciando bot...")

    try:
        time.sleep(10)
        bot.run(DISCORD_TOKEN)

    except KeyboardInterrupt:
        print("🛑 Bot detenido manualmente.")

    except Exception as e:
        print(f"❌ Error iniciando el bot: {e}")










