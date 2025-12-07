import discord
from discord.ext import commands
import json
import os
from typing import Dict, Any, List

# =====================================================
#                KONFIG & GRUNDSETUP
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CONFIG_FILE = "config.json"


def load_config() -> Dict[str, Any]:
    """Lädt die Konfiguration aus config.json oder liefert eine Grundstruktur."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception as e:
            print("Fehler beim Laden der config.json:", repr(e))
            data = {}
    else:
        data = {}

    # Grundstruktur
    data.setdefault("guilds", {})

    # Migration älterer Strukturen
    for gid, gcfg in data["guilds"].items():
        # forum_pairs als Liste sicherstellen
        gcfg.setdefault("forum_pairs", [])
        gcfg.setdefault("follow_roles", [])
        gcfg.setdefault("follow_threads", [])

        # alte Paare mit nur "target_id" auf neue Struktur heben
        new_pairs = []
        for pair in gcfg["forum_pairs"]:
            if not isinstance(pair, dict):
                continue
            forum_id = pair.get("forum_id")
            new_target = pair.get("new_target_id")
            follow_target = pair.get("follow_target_id")
            old_target = pair.get("target_id")

            if forum_id is None:
                continue

            if new_target is None and follow_target is None and old_target is not None:
                new_target = old_target
                follow_target = old_target

            if new_target is None:
                new_target = follow_target
            if follow_target is None:
                follow_target = new_target

            new_pairs.append(
                {
                    "forum_id": forum_id,
                    "new_target_id": new_target,
                    "follow_target_id": follow_target,
                }
            )
        gcfg["forum_pairs"] = new_pairs

    return data


def save_config() -> None:
    """Speichert die Konfiguration nach config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print("Konfiguration gespeichert.")
    except Exception as e:
        print("Fehler beim Speichern der config.json:", repr(e))


config: Dict[str, Any] = load_config()


def get_guild_cfg(guild_id: int) -> Dict[str, Any]:
    """Gibt die Konfiguration für eine Guild zurück (oder legt sie an)."""
    gid = str(guild_id)
    if gid not in config["guilds"]:
        config["guilds"][gid] = {
            "forum_pairs": [],
            "follow_roles": [],
            "follow_threads": [],
        }
    g = config["guilds"][gid]
    g.setdefault("forum_pairs", [])
    g.setdefault("follow_roles", [])
    g.setdefault("follow_threads", [])
    return g


# =====================================================
#                 BOT & INTENTS
# =====================================================

intents = discord.Intents.default()
intents.guilds = True
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)


# =====================================================
#                     EVENTS
# =====================================================

@bot.event
async def on_ready():
    print(f"Bot eingeloggt als {bot.user} (ID: {bot.user.id})")
    print("Aktuelle Konfiguration:", config)


@bot.event
async def on_message(message: discord.Message):
    """Verarbeitet Commands & Follow-Benachrichtigungen."""
    await bot.process_commands(message)

    # DMs / Bots ignorieren
    if message.guild is None or message.author.bot:
        return

    guild = message.guild
    gcfg = get_guild_cfg(guild.id)

    # Nur in Threads
    if not isinstance(message.channel, discord.Thread):
        return

    thread: discord.Thread = message.channel

    # Nur Threads, die in follow_threads eingetragen sind
    if thread.id not in gcfg["follow_threads"]:
        return

    # Wenn Autor eine Follow-Rolle hat -> keine Benachrichtigung
    follow_roles_ids: List[int] = gcfg.get("follow_roles", [])
    if follow_roles_ids:
        for r in getattr(message.author, "roles", []):
            if r.id in follow_roles_ids:
                return

    parent_id = thread.parent_id
    if parent_id is None:
        return

    # Passende Follow-Target-Channels für dieses Forum
    follow_targets: List[discord.TextChannel] = []
    for pair in gcfg.get("forum_pairs", []):
        if pair.get("forum_id") == parent_id:
            t_id = pair.get("follow_target_id") or pair.get("new_target_id")
            ch = guild.get_channel(t_id)
            if isinstance(ch, discord.TextChannel):
                follow_targets.append(ch)

    if not follow_targets:
        return

    # Ping-Rollen
    roles_to_ping = [
        guild.get_role(rid) for rid in follow_roles_ids
        if guild.get_role(rid) is not None
    ]
    mention_text = " ".join(r.mention for r in roles_to_ping) if roles_to_ping else ""

    jump = message.jump_url
    content_preview = (message.content[:150] + "…") if len(message.content) > 150 else message.content

    embed = discord.Embed(
        title="📩 Neue Antwort in beobachtetem Thread",
        description=(
            f"Thread: **{thread.name}**\n"
            f"Autor: {message.author.mention}\n\n"
            f"**Auszug:**\n{content_preview or '*ohne Text*'}\n\n"
            f"[🔗 Zur Nachricht springen]({jump})"
        ),
        color=0x00BFFF
    )

    for target in follow_targets:
        try:
            if mention_text:
                await target.send(content=mention_text, embed=embed)
            else:
                await target.send(embed=embed)
        except Exception as e:
            print(f"Fehler beim Senden der Follow-Benachrichtigung in {target}: {e}")


@bot.event
async def on_thread_create(thread: discord.Thread):
    """Benachrichtigt bei neuen Threads in den verknüpften Foren."""
    if thread.guild is None:
        return

    guild = thread.guild
    gcfg = get_guild_cfg(guild.id)

    parent_id = thread.parent_id
    if parent_id is None:
        return

    # New-thread-Targets für dieses Forum
    new_targets: List[discord.TextChannel] = []
    for pair in gcfg.get("forum_pairs", []):
        if pair.get("forum_id") == parent_id:
            t_id = pair.get("new_target_id") or pair.get("follow_target_id")
            ch = guild.get_channel(t_id)
            if isinstance(ch, discord.TextChannel):
                new_targets.append(ch)

    if not new_targets:
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

    for ch in new_targets:
        try:
            await ch.send(embed=embed)
        except Exception as e:
            print(f"Fehler beim Senden des Thread-Embeds in {ch}: {e}")


# =====================================================
#                 PERMISSIONS / CHECKS
# =====================================================

def is_guild_admin():
    async def predicate(ctx: commands.Context):
        return ctx.guild is not None and ctx.author.guild_permissions.manage_guild
    return commands.check(predicate)


# =====================================================
#                    BEFEHLE
# =====================================================

@bot.command(name="helpbot")
async def help_bot(ctx: commands.Context):
    """Zeigt eine Hilfe für den ForumLinkBot."""
    prefix = ctx.prefix
    desc = (
        f"**ForumLinkBot – Hilfe**\n\n"
        f"**Allgemein**\n"
        f"`{prefix}helpbot` – Zeigt diese Hilfe\n\n"
        f"**Forum / Zielchannel Paare** (Server-Admin):\n"
        f"`{prefix}addpair #forum #neu-channel #follow-channel` – "
        f"Forum mit zwei Zielchannels verknüpfen (neue Threads / Follow-Pings)\n"
        f"`{prefix}listpairs` – Listet alle Paare\n"
        f"`{prefix}delpair <index>` – Löscht ein Paar (Index aus `listpairs`)\n\n"
        f"**Follow – Rollen & Threads**\n"
        f"`{prefix}setfollowroles @Rolle1 [@Rolle2 …]` – Rollen, die bei Antworten gepingt werden\n"
        f"`{prefix}showfollowroles` – Zeigt aktuelle Follow-Rollen\n"
        f"`{prefix}clearfollowroles` – Entfernt alle Follow-Rollen\n\n"
        f"`{prefix}follow` – (im Thread) Diesen Thread beobachten\n"
        f"`{prefix}unfollow` – Beobachtung beenden\n"
        f"`{prefix}showfollow` – Zeigt, ob der Thread beobachtet wird\n\n"
        f"**Hinweise**\n"
        f"- Follow funktioniert nur in Threads von Foren, die mit `{prefix}addpair` verknüpft wurden.\n"
        f"- Antworten von Nutzern mit Follow-Rolle lösen **keine** Benachrichtigung aus."
    )
    embed = discord.Embed(description=desc, color=0x7289DA)
    await ctx.send(embed=embed)


# ---------- Forum / Target – Paare ----------

@bot.command(name="addpair")
@is_guild_admin()
async def add_pair(ctx: commands.Context,
                   forum_channel: discord.ForumChannel,
                   new_thread_channel: discord.TextChannel,
                   follow_channel: discord.TextChannel):
    """
    Verknüpft ein Forum mit zwei Zielchannels:
    - new_thread_channel: Meldung bei neuen Threads
    - follow_channel: Follow-Benachrichtigungen bei Antworten
    """
    gcfg = get_guild_cfg(ctx.guild.id)
    gcfg["forum_pairs"].append(
        {
            "forum_id": forum_channel.id,
            "new_target_id": new_thread_channel.id,
            "follow_target_id": follow_channel.id,
        }
    )
    save_config()
    await ctx.send(
        "✅ Paar hinzugefügt:\n"
        f"Forum: {forum_channel.mention}\n"
        f"Neue Threads → {new_thread_channel.mention}\n"
        f"Follow-Pings → {follow_channel.mention}"
    )


@bot.command(name="listpairs")
async def list_pairs(ctx: commands.Context):
    """Listet alle Forum→Ziel-Paare dieses Servers."""
    gcfg = get_guild_cfg(ctx.guild.id)
    pairs = gcfg.get("forum_pairs", [])
    if not pairs:
        await ctx.send("ℹ️ Es sind noch keine Forum-Paare konfiguriert.")
        return

    lines = []
    for idx, pair in enumerate(pairs, start=1):
        forum = ctx.guild.get_channel(pair.get("forum_id", 0))
        new_ch = ctx.guild.get_channel(pair.get("new_target_id", 0))
        follow_ch = ctx.guild.get_channel(pair.get("follow_target_id", 0))
        lines.append(
            f"**{idx}.** Forum: {forum.mention if forum else pair.get('forum_id')}\n"
            f"   Neue Threads → {new_ch.mention if new_ch else pair.get('new_target_id')}\n"
            f"   Follow-Pings → {follow_ch.mention if follow_ch else pair.get('follow_target_id')}"
        )

    await ctx.send("\n".join(lines))


@bot.command(name="delpair")
@is_guild_admin()
async def delete_pair(ctx: commands.Context, index: int):
    """Löscht ein Forum-Paar anhand des Index aus `listpairs`."""
    gcfg = get_guild_cfg(ctx.guild.id)
    pairs = gcfg.get("forum_pairs", [])

    if index < 1 or index > len(pairs):
        await ctx.send("❌ Ungültiger Index. Nutze zuerst `!listpairs`, um die Nummer zu sehen.")
        return

    removed = pairs.pop(index - 1)
    save_config()

    await ctx.send(
        "✅ Paar gelöscht:\n"
        f"Forum-ID: `{removed.get('forum_id')}`\n"
        f"Neue Threads → `{removed.get('new_target_id')}`\n"
        f"Follow-Pings → `{removed.get('follow_target_id')}`"
    )


# ---------- Follow-Rollen ----------

@bot.command(name="setfollowroles")
@is_guild_admin()
async def set_follow_roles(ctx: commands.Context, *roles: discord.Role):
    """Setzt die Rollen, die bei Antworten gepingt werden sollen."""
    if not roles:
        await ctx.send("❌ Bitte gib mindestens eine Rolle an, z.B. `!setfollowroles @Moderatoren @Admins`.")
        return

    gcfg = get_guild_cfg(ctx.guild.id)
    gcfg["follow_roles"] = [r.id for r in roles]
    save_config()

    await ctx.send(
        "✅ Folgende Rollen werden jetzt bei Antworten gepingt:\n" +
        ", ".join(r.mention for r in roles)
    )


@bot.command(name="showfollowroles")
async def show_follow_roles(ctx: commands.Context):
    """Zeigt, welche Rollen aktuell für Follow-Benachrichtigungen gesetzt sind."""
    gcfg = get_guild_cfg(ctx.guild.id)
    ids = gcfg.get("follow_roles", [])
    if not ids:
        await ctx.send("ℹ️ Es sind aktuell **keine** Follow-Rollen gesetzt.")
        return

    roles = [ctx.guild.get_role(rid) for rid in ids]
    roles = [r for r in roles if r is not None]

    if not roles:
        await ctx.send("ℹ️ Es sind IDs gespeichert, aber keine der Rollen existiert mehr.")
        return

    await ctx.send(
        "👥 Aktuelle Follow-Rollen:\n" +
        ", ".join(r.mention for r in roles)
    )


@bot.command(name="clearfollowroles")
@is_guild_admin()
async def clear_follow_roles(ctx: commands.Context):
    """Entfernt alle Follow-Rollen."""
    gcfg = get_guild_cfg(ctx.guild.id)
    gcfg["follow_roles"] = []
    save_config()
    await ctx.send("✅ Alle Follow-Rollen wurden entfernt.")


# ---------- Follow / Unfollow pro Thread ----------

def _ensure_thread_ctx(ctx: commands.Context) -> discord.Thread | None:
    if isinstance(ctx.channel, discord.Thread):
        return ctx.channel
    return None


@bot.command(name="follow")
async def follow_thread(ctx: commands.Context):
    """Markiert den aktuellen Thread als beobachtet (Follow)."""
    thread = _ensure_thread_ctx(ctx)
    if thread is None:
        await ctx.send("❌ Dieser Befehl muss **in einem Thread** ausgeführt werden.")
        return

    gcfg = get_guild_cfg(ctx.guild.id)

    parent_id = thread.parent_id
    if parent_id is None:
        await ctx.send("❌ Dieser Thread hat kein Forum als Elternkanal.")
        return

    valid_forum_ids = [p.get("forum_id") for p in gcfg.get("forum_pairs", [])]
    if parent_id not in valid_forum_ids:
        await ctx.send(
            "❌ Dieser Thread gehört nicht zu einem Forum, "
            "das mit `!addpair` verknüpft wurde."
        )
        return

    if thread.id in gcfg["follow_threads"]:
        await ctx.send("ℹ️ Dieser Thread wird bereits beobachtet.")
        return

    gcfg["follow_threads"].append(thread.id)
    save_config()

    await ctx.send(
        "✅ Dieser Thread wird nun beobachtet.\n"
        "Wenn jemand **ohne Follow-Rolle** antwortet, werden die Follow-Rollen "
        "im Follow-Channel dieses Forums benachrichtigt."
    )


@bot.command(name="unfollow")
async def unfollow_thread(ctx: commands.Context):
    """Entfernt die Beobachtung für den aktuellen Thread."""
    thread = _ensure_thread_ctx(ctx)
    if thread is None:
        await ctx.send("❌ Dieser Befehl muss **in einem Thread** ausgeführt werden.")
        return

    gcfg = get_guild_cfg(ctx.guild.id)

    if thread.id not in gcfg["follow_threads"]:
        await ctx.send("ℹ️ Dieser Thread wird aktuell nicht beobachtet.")
        return

    gcfg["follow_threads"].remove(thread.id)
    save_config()

    await ctx.send("✅ Beobachtung für diesen Thread wurde beendet.")


@bot.command(name="showfollow")
async def show_follow_status(ctx: commands.Context):
    """Zeigt, ob der aktuelle Thread beobachtet wird."""
    thread = _ensure_thread_ctx(ctx)
    if thread is None:
        await ctx.send("❌ Dieser Befehl muss **in einem Thread** ausgeführt werden.")
        return

    gcfg = get_guild_cfg(ctx.guild.id)

    if thread.id in gcfg["follow_threads"]:
        await ctx.send("👀 Dieser Thread **wird** aktuell beobachtet.")
    else:
        await ctx.send("ℹ️ Dieser Thread wird **nicht** beobachtet.")


# =====================================================
#                    BOT STARTEN
# =====================================================

if __name__ == "__main__":
    if not BOT_TOKEN or BOT_TOKEN == "DEIN_DISCORD_BOT_TOKEN_HIER":
        print("❌ Kein gültiger BOT_TOKEN gesetzt! Bitte Umgebungsvariable BOT_TOKEN oder Konstanten oben anpassen.")
    else:
        print("Starte Bot.run …")
        bot.run(BOT_TOKEN)
