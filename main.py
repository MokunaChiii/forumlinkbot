import discord
from discord.ext import commands
import json
import os

CONFIG_FILE = "config.json"

# ----------------------------------------------------
#   CONFIG LADEN / SPEICHERN
# ----------------------------------------------------
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({}, f)

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

config = load_config()

# ----------------------------------------------------
#   BOT GRUNDKONFIG
# ----------------------------------------------------
intents = discord.Intents.default()
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ----------------------------------------------------
#   COMMANDS FÜR SERVER-ADMINISTRATOREN
# ----------------------------------------------------

@bot.command()
@commands.has_permissions(administrator=True)
async def setforum(ctx, channel: discord.ForumChannel):
    """Legt fest, WELCHES Forum überwacht wird."""
    gid = str(ctx.guild.id)

    if gid not in config:
        config[gid] = {}

    config[gid]["forum"] = channel.id
    save_config(config)

    await ctx.send(f"✅ Forum-Channel gesetzt: {channel.mention} (ID: {channel.id})")


@bot.command()
@commands.has_permissions(administrator=True)
async def settarget(ctx, channel: discord.TextChannel):
    """Legt fest, WO der Bot die Meldungen posten soll."""
    gid = str(ctx.guild.id)

    if gid not in config:
        config[gid] = {}

    config[gid]["target"] = channel.id
    save_config(config)

    await ctx.send(f"✅ Ziel-Channel gesetzt: {channel.mention} (ID: {channel.id})")


@bot.command()
@commands.has_permissions(administrator=True)
async def showconfig(ctx):
    """Zeigt die aktuelle Konfiguration für diesen Server."""
    gid = str(ctx.guild.id)
    conf = config.get(gid, {})

    forum_id = conf.get("forum")
    target_id = conf.get("target")

    forum = ctx.guild.get_channel(forum_id) if forum_id else None
    target = ctx.guild.get_channel(target_id) if target_id else None

    msg = [
        "🔧 **Aktuelle Konfiguration:**",
        f"• Forum:  {forum.mention if forum else '`nicht gesetzt`'}",
        f"• Ausgabe: {target.mention if target else '`nicht gesetzt`'}"
    ]
    await ctx.send("\n".join(msg))


# ----------------------------------------------------
#   BOT START MELDUNG
# ----------------------------------------------------

@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user} ({bot.user.id})")


# ----------------------------------------------------
#   THREAD-ÜBERWACHUNG (Forum-Beiträge)
# ----------------------------------------------------

@bot.event
async def on_thread_create(thread: discord.Thread):

    if thread.guild is None:
        return

    gid = str(thread.guild.id)

    # Server hat keine Konfiguration
    if gid not in config:
        return

    forum_id = config[gid].get("forum")
    target_id = config[gid].get("target")

    if forum_id is None or target_id is None:
        return

    # Thread ist nicht im richtigen Forum → ignorieren
    if thread.parent_id != forum_id:
        return

    target_channel = thread.guild.get_channel(target_id)
    if target_channel is None:
        return

    link = thread.jump_url
    title = thread.name

    embed = discord.Embed(
        title="🔔 Neuer Forum-Beitrag",
        description=f"📝 **{title}**\n[🔗 Zum Beitrag öffnen]({link})",
        color=0x00FF99
    )

    if thread.owner:
        embed.set_footer(text=f"Erstellt von {thread.owner.display_name}")

    await target_channel.send(embed=embed)
    print(f"Neuer Beitrag → gesendet nach {target_channel.name}")


# ----------------------------------------------------
#   START – TOKEN AUS ENV-VARIABLE
# ----------------------------------------------------

token = os.getenv("BOT_TOKEN")
if not token:
    raise RuntimeError("Umgebungsvariable BOT_TOKEN ist nicht gesetzt!")

bot.run(token)
