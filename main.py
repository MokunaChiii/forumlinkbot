import discord
from discord.ext import commands
import json
import os

# ---------------------------------------------------------
#                 TOKEN AUS UMGEBUNG LADEN
# ---------------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")  # wird später auf dem VPS gesetzt

CONFIG_FILE = "config.json"


# ---------------------------------------------------------
#           KONFIGURATION LADEN / SPEICHERN
# ---------------------------------------------------------

def load_config():
    """Lädt die Konfiguration aus config.json."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "guilds" in data:
                # Migration/Defaults für ältere Strukturen
                for gid, gdata in data["guilds"].items():
                    if not isinstance(gdata, dict):
                        data["guilds"][gid] = {}
                        gdata = data["guilds"][gid]
                    gdata.setdefault("forum_pairs", [])
                    gdata.setdefault("follows", {})
                    # alte Einzelrolle -> Liste
                    if "follow_ping_role_ids" not in gdata:
                        gdata["follow_ping_role_ids"] = []
                    if "follow_ping_role_id" in gdata and gdata["follow_ping_role_id"]:
                        if gdata["follow_ping_role_id"] not in gdata["follow_ping_role_ids"]:
                            gdata["follow_ping_role_ids"].append(gdata["follow_ping_role_id"])
                        del gdata["follow_ping_role_id"]
                return data
        except Exception as e:
            print("Fehler beim Laden der config.json:", repr(e))

    # Fallback: leere Struktur
    return {"guilds": {}}


def save_config():
    """Speichert die aktuelle Konfiguration in config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print("Konfiguration gespeichert.")
    except Exception as e:
        print("Fehler beim Speichern der config.json:", repr(e))


config = load_config()


def get_guild_config(guild_id: int) -> dict:
    """
    Liefert die Konfiguration für eine Guild
    und stellt sicher, dass Standard-Struktur existiert.
    """
    gid = str(guild_id)
    if gid not in config["guilds"]:
        config["guilds"][gid] = {
            "forum_pairs": [],           # Liste von {forum_channel_id, target_channel_id}
            "follows": {},               # thread_id(str) -> {target_channel_id, created_by}
            "follow_ping_role_ids": []   # Liste von Rollen-IDs, die bei Follows gepingt werden
        }

    g_cfg = config["guilds"][gid]
    g_cfg.setdefault("forum_pairs", [])
    g_cfg.setdefault("follows", {})
    g_cfg.setdefault("follow_ping_role_ids", [])

    return g_cfg


def format_channel_mention(channel_id: int):
    return f"<#{channel_id}>" if channel_id else "unbekannt"


# ---------------------------------------------------------
#                     BOT INITIALISIEREN
# ---------------------------------------------------------

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True   # wichtig für Prefix-Befehle
intents.messages = True          # wichtig für on_message / Follow-System

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user} (ID: {bot.user.id})")
    print("Aktuelle Konfiguration:", config)


# ---------------------------------------------------------
#                     HILFS-FUNKTIONEN
# ---------------------------------------------------------

def is_guild_admin():
    """Nur Nutzer mit 'Server verwalten'-Recht dürfen bestimmte Befehle nutzen."""
    async def predicate(ctx):
        return ctx.guild is not None and ctx.author.guild_permissions.manage_guild
    return commands.check(predicate)


# ---------------------------------------------------------
#                ADMIN-BEFEHLE: FORUM-PAARE
# ---------------------------------------------------------

@bot.command(name="addpair")
@is_guild_admin()
async def add_pair(ctx,
                   forum: discord.abc.GuildChannel,
                   target: discord.TextChannel):
    """
    Füge ein Forum↔Ziel-Channel-Paar hinzu.
    Nutzung: !addpair #dein-forum #ziel-channel
    """
    if not isinstance(forum, discord.ForumChannel):
        await ctx.send("❌ Bitte gib als erstes einen **Forum-Channel** an.")
        return

    g_cfg = get_guild_config(ctx.guild.id)

    for pair in g_cfg["forum_pairs"]:
        if pair["forum_channel_id"] == forum.id and pair["target_channel_id"] == target.id:
            await ctx.send("ℹ️ Dieses Paar existiert bereits.")
            return

    g_cfg["forum_pairs"].append({
        "forum_channel_id": forum.id,
        "target_channel_id": target.id
    })
    save_config()

    await ctx.send(
        f"✅ Neues Forum-Paar hinzugefügt:\n"
        f"• Forum: {forum.mention}\n"
        f"• Ziel: {target.mention}"
    )


@bot.command(name="listpairs")
async def list_pairs(ctx):
    """
    Zeigt alle Forum↔Ziel-Channel-Paare dieses Servers.
    Nutzung: !listpairs
    """
    g_cfg = get_guild_config(ctx.guild.id)
    pairs = g_cfg["forum_pairs"]

    if not pairs:
        await ctx.send(
            "ℹ️ Es sind noch keine Forum-Paare für diesen Server konfiguriert.\n"
            "Admins können `!addpair #forum #ziel` verwenden."
        )
        return

    lines = []
    for idx, pair in enumerate(pairs, start=1):
        forum = ctx.guild.get_channel(pair["forum_channel_id"])
        target = ctx.guild.get_channel(pair["target_channel_id"])
        lines.append(
            f"**{idx}.** Forum: {forum.mention if forum else format_channel_mention(pair['forum_channel_id'])} "
            f"→ Ziel: {target.mention if target else format_channel_mention(pair['target_channel_id'])}"
        )

    await ctx.send("📌 **Forum-Paare:**\n" + "\n".join(lines))


@bot.command(name="removepair")
@is_guild_admin()
async def remove_pair(ctx, index: int):
    """
    Entfernt ein Forum-Paar anhand der Nummer aus !listpairs.
    Nutzung: !removepair 1
    """
    g_cfg = get_guild_config(ctx.guild.id)
    pairs = g_cfg["forum_pairs"]

    if not pairs:
        await ctx.send("ℹ️ Es gibt keine Paare zum Löschen.")
        return

    if index < 1 or index > len(pairs):
        await ctx.send(f"❌ Ungültige Nummer. Gültig ist 1–{len(pairs)}.")
        return

    removed = pairs.pop(index - 1)
    save_config()

    forum = ctx.guild.get_channel(removed["forum_channel_id"])
    target = ctx.guild.get_channel(removed["target_channel_id"])

    await ctx.send(
        "🗑️ Forum-Paar gelöscht:\n"
        f"• Forum: {forum.mention if forum else format_channel_mention(removed['forum_channel_id'])}\n"
        f"• Ziel: {target.mention if target else format_channel_mention(removed['target_channel_id'])}"
    )


# ---------------------------------------------------------
#       ADMIN-BEFEHLE: MEHRERE FOLLOW-PING-ROLLEN
# ---------------------------------------------------------

@bot.command(name="addfollowrole")
@is_guild_admin()
async def add_follow_role(ctx, role: discord.Role):
    """
    Fügt eine Rolle zur Liste der Follow-Ping-Rollen hinzu.
    Nutzung: !addfollowrole @Moderatoren
    """
    g_cfg = get_guild_config(ctx.guild.id)
    role_ids = g_cfg["follow_ping_role_ids"]

    if role.id in role_ids:
        await ctx.send(f"ℹ️ {role.mention} ist bereits in der Ping-Liste.")
        return

    role_ids.append(role.id)
    save_config()

    await ctx.send(f"✅ Rolle zur Follow-Ping-Liste hinzugefügt: {role.mention}")


@bot.command(name="removefollowrole")
@is_guild_admin()
async def remove_follow_role(ctx, role: discord.Role):
    """
    Entfernt eine Rolle aus der Follow-Ping-Liste.
    Nutzung: !removefollowrole @Moderatoren
    """
    g_cfg = get_guild_config(ctx.guild.id)
    role_ids = g_cfg["follow_ping_role_ids"]

    if role.id not in role_ids:
        await ctx.send("ℹ️ Diese Rolle ist nicht in der Ping-Liste.")
        return

    role_ids.remove(role.id)
    save_config()

    await ctx.send(f"✅ Rolle aus der Follow-Ping-Liste entfernt: {role.mention}")


@bot.command(name="listfollowroles")
async def list_follow_roles(ctx):
    """
    Zeigt alle Rollen, die bei Follow-Updates gepingt werden.
    Nutzung: !listfollowroles
    """
    g_cfg = get_guild_config(ctx.guild.id)
    role_ids = g_cfg["follow_ping_role_ids"]

    if not role_ids:
        await ctx.send("ℹ️ Es sind derzeit keine Follow-Ping-Rollen konfiguriert.")
        return

    mentions = []
    for rid in role_ids:
        r = ctx.guild.get_role(rid)
        mentions.append(r.mention if r else f"`{rid}` (nicht gefunden)")

    await ctx.send("🎯 **Follow-Ping-Rollen:**\n" + ", ".join(mentions))


@bot.command(name="clearfollowroles")
@is_guild_admin()
async def clear_follow_roles(ctx):
    """
    Löscht alle eingetragenen Follow-Ping-Rollen.
    Nutzung: !clearfollowroles
    """
    g_cfg = get_guild_config(ctx.guild.id)
    g_cfg["follow_ping_role_ids"] = []
    save_config()

    await ctx.send("✅ Alle Follow-Ping-Rollen wurden gelöscht.")


# ---------------------------------------------------------
#                 FOLLOW-BEFEHLE (THREADS)
# ---------------------------------------------------------

@bot.command(name="followhere")
async def follow_here(ctx, target: discord.TextChannel):
    """
    Folge dem aktuellen Forum-Thread und leite neue Antworten
    in den angegebenen Ziel-Channel weiter.
    Nutzung (im Thread): !followhere #ziel-channel
    """
    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("❌ Dieser Befehl muss **innerhalb eines Forum-Threads** benutzt werden.")
        return

    thread = ctx.channel
    guild = ctx.guild
    g_cfg = get_guild_config(guild.id)

    g_cfg["follows"][str(thread.id)] = {
        "target_channel_id": target.id,
        "created_by": ctx.author.id
    }
    save_config()

    await ctx.send(
        f"✅ Ich folge jetzt diesem Thread.\n"
        f"Neue Antworten werden nach {target.mention} gemeldet."
    )


@bot.command(name="unfollowhere")
async def unfollow_here(ctx):
    """
    Entfernt das Follow für den aktuellen Thread.
    Nutzung (im Thread): !unfollowhere
    """
    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("❌ Dieser Befehl muss **innerhalb eines Forum-Threads** benutzt werden.")
        return

    guild = ctx.guild
    g_cfg = get_guild_config(guild.id)
    key = str(ctx.channel.id)

    if key in g_cfg["follows"]:
        del g_cfg["follows"][key]
        save_config()
        await ctx.send("🛑 Ich folge diesem Thread nicht mehr.")
    else:
        await ctx.send("ℹ️ Für diesen Thread war kein Follow aktiv.")


@bot.command(name="listfollows")
async def list_follows(ctx):
    """
    Zeigt alle Threads, denen der Bot aktuell folgt.
    Nutzung: !listfollows
    """
    guild = ctx.guild
    g_cfg = get_guild_config(ctx.guild.id)
    follows = g_cfg["follows"]

    if not follows:
        await ctx.send("ℹ️ Derzeit werden keine Threads auf diesem Server verfolgt.")
        return

    lines = []
    for thread_id_str, info in follows.items():
        thread_id = int(thread_id_str)
        thread = guild.get_thread(thread_id) or guild.get_channel(thread_id)
        target = guild.get_channel(info["target_channel_id"])
        creator = guild.get_member(info.get("created_by", 0))

        lines.append(
            f"• Thread: {thread.mention if thread else f'`{thread_id}` (nicht gefunden)'}\n"
            f"  → Ziel: {target.mention if target else format_channel_mention(info['target_channel_id'])}\n"
            f"  (angelegt von {creator.mention if creator else 'unbekannt'})"
        )

    await ctx.send("📡 **Aktive Follows:**\n" + "\n\n".join(lines))


# ---------------------------------------------------------
#                       HILFE-BEFEHL
# ---------------------------------------------------------

@bot.command(name="fhelp")
async def forum_help(ctx):
    """
    Zeigt eine Übersicht der wichtigsten Befehle.
    Nutzung: !fhelp
    """
    text = (
        "📘 **ForumLinkBot – Hilfe**\n\n"
        "__Allgemein:__\n"
        "`!fhelp` – zeigt diese Hilfe\n"
        "`!listpairs` – zeigt alle Forum↔Ziel-Channel-Paare\n"
        "`!listfollows` – zeigt alle Threads, denen der Bot folgt\n"
        "`!listfollowroles` – zeigt alle Rollen, die bei Follow-Updates gepingt werden\n\n"
        "__Admin (Server verwalten):__\n"
        "`!addpair #forum #ziel` – neues Forum-Paar hinzufügen\n"
        "`!removepair <Nummer>` – Forum-Paar löschen (Nummer aus !listpairs)\n"
        "`!addfollowrole @Rolle` – Rolle zur Follow-Ping-Liste hinzufügen\n"
        "`!removefollowrole @Rolle` – Rolle aus der Follow-Ping-Liste entfernen\n"
        "`!clearfollowroles` – alle Follow-Ping-Rollen löschen\n\n"
        "__Follow (im Thread benutzen):__\n"
        "`!followhere #ziel-channel` – diesem Thread folgen und Updates in #ziel-channel schicken\n"
        "`!unfollowhere` – Follow für diesen Thread beenden\n"
    )
    await ctx.send(text)


# ---------------------------------------------------------
#           EVENT: NEUE FORUM-THREADS (PAARE)
# ---------------------------------------------------------

@bot.event
async def on_thread_create(thread: discord.Thread):
    """
    Reagiert auf neue Threads in Forum-Channels und postet
    Infos in alle passenden Ziel-Channels der konfigurierten Paare.
    """
    try:
        guild = thread.guild
        if guild is None:
            return

        g_cfg = get_guild_config(guild.id)
        pairs = g_cfg["forum_pairs"]

        if not pairs:
            return

        matching_pairs = [
            p for p in pairs if p["forum_channel_id"] == thread.parent_id
        ]
        if not matching_pairs:
            return

        link = thread.jump_url

        embed = discord.Embed(
            title="🔔 Neuer Forum-Beitrag",
            description=f"📝 **{thread.name}**\n[🔗 Zum Beitrag öffnen]({link})",
            color=0x00FF99,
        )

        owner = getattr(thread, "owner", None)
        if owner:
            embed.set_footer(text=f"Erstellt von {owner.display_name}")

        for pair in matching_pairs:
            target_channel = guild.get_channel(pair["target_channel_id"])
            if target_channel:
                await target_channel.send(embed=embed)
                print(
                    f"Neuer Thread '{thread.name}' aus Forum {pair['forum_channel_id']} "
                    f"nach Channel {target_channel.id} gemeldet."
                )

    except Exception as e:
        print("Fehler in on_thread_create:", repr(e))


# ---------------------------------------------------------
#           EVENT: NEUE NACHRICHTEN (FOLLOW-UPDATES)
# ---------------------------------------------------------

@bot.event
async def on_message(message: discord.Message):
    """
    Prüft, ob eine neue Nachricht in einem verfolgten Thread geschrieben wurde
    und sendet ggf. ein Update in den zugehörigen Ziel-Channel.

    NEU:
    - Wenn der Autor eine der Follow-Ping-Rollen hat (z. B. Mod/Admin),
      wird KEINE Benachrichtigung geschickt.
    """
    # Erst Commands verarbeiten, damit !followhere etc. funktionieren
    await bot.process_commands(message)

    # Bots-Nachrichten danach ignorieren
    if message.author.bot:
        return

    guild = message.guild
    channel = message.channel

    # Nur interessant, wenn Thread in einer Guild
    if not (guild and isinstance(channel, discord.Thread)):
        return

    g_cfg = get_guild_config(guild.id)
    follow_info = g_cfg["follows"].get(str(channel.id))

    if not follow_info:
        # Thread wird nicht verfolgt
        return

    # Wenn Autor eine der Follow-Rollen hat → keine Benachrichtigung schicken
    staff_role_ids = set(g_cfg.get("follow_ping_role_ids", []))
    if staff_role_ids:
        author_roles = getattr(message.author, "roles", [])
        if any(role.id in staff_role_ids for role in author_roles):
            # Autor ist Mod/Admin o.ä. → keine Meldung
            return

    target_channel = guild.get_channel(follow_info["target_channel_id"])
    if not target_channel:
        return

    # Rollen-Mentions erstellen
    role_ids = g_cfg.get("follow_ping_role_ids", [])
    mentions = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            mentions.append(role.mention)

    ping_text = " ".join(mentions) if mentions else None

    # Kurzer Ausschnitt der Nachricht
    snippet = message.content.strip()
    if len(snippet) > 200:
        snippet = snippet[:200] + "…"
    if not snippet:
        snippet = "*ohne Text*"

    embed = discord.Embed(
        title="💬 Neue Antwort im verfolgten Thread",
        description=f"[{channel.name}]({message.jump_url})",
        color=0x00BFFF,
    )
    embed.add_field(name="Autor", value=message.author.mention, inline=True)
    embed.add_field(name="Ausschnitt", value=snippet, inline=False)

    await target_channel.send(content=ping_text, embed=embed)
    print(
        f"Follow-Update aus Thread {channel.id} nach Channel {target_channel.id} gesendet."
    )


# ---------------------------------------------------------
#                 BOT STARTEN
# ---------------------------------------------------------

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("Fehler: BOT_TOKEN ist nicht gesetzt! Bitte als Umgebungsvariable setzen.")
    else:
        print("Starte Bot.run...")
        try:
            bot.run(BOT_TOKEN)
        except Exception as e:
            print("Fehler beim Starten des Bots:", repr(e))
