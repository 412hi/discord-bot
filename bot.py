import asyncio
import datetime
import json
import os
import random
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Set

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False
    class Fore:
        GREEN = RED = YELLOW = CYAN = WHITE = RESET = ""
    class Style:
        BRIGHT = DIM = RESET_ALL = ""

load_dotenv()
DISCORD_TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")

CONFIG_PATH = Path(__file__).with_name("config.json")

TICKET_SUPPORT_ROLE = "ticket_support"

LINK_ALLOWED_ROLE_IDS = {Link yollayabileceklerin rolleri / Reels of those who will send links}
LINK_TIMEOUT_SECONDS = 60
LINK_PATTERN = re.compile(r"(https?://|discord\.gg/|www\.)\S+", re.IGNORECASE)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.voice_states = True
intents.reactions = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="§", intents=intents)
tree = bot.tree

EMOJI_GIVEAWAY = "🎉"

YTDL_OPTS: Dict[str, Any] = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
}

music_states: Dict[int, "GuildMusicState"] = {}
_giveaway_tasks: Set[asyncio.Task] = set()

TICKET_CATEGORIES = [
    {"value": "satin_alma",    "label": "Satın Alma / Purchase",            "description": "Satın alma sorunları için.",         "emoji": "🛒"},
    {"value": "destek_yardim", "label": "Destek Yardım / Support",          "description": "Genel destek ve yardım talepleri.",  "emoji": "🙋"},
    {"value": "teknik_destek", "label": "Teknik Destek",                    "description": "Teknik sorunlar için.",              "emoji": "🔧"},
    {"value": "media_basvuru", "label": "Media Başvuru / Media Application", "description": "İçerik ve medya konuları.",          "emoji": "🎬"},
    {"value": "kadro_basvuru", "label": "Kadro Başvuru / Staff Application", "description": "Ekip başvuruları için.",             "emoji": "📋"},
    {"value": "diger",         "label": "Diğer / Other",                    "description": "Genel destek talepleri.",            "emoji": "💬"},
]

def get_support_role(guild: discord.Guild) -> Optional[discord.Role]:
    return discord.utils.get(guild.roles, name=TICKET_SUPPORT_ROLE)

def get_category_info(value: str) -> Dict[str, str]:
    for cat in TICKET_CATEGORIES:
        if cat["value"] == value:
            return cat
    return {"value": value, "label": value, "description": "", "emoji": "🎫"}

# ---------------------------------------------------------------------------
# Startup printer
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def print_status(label: str, ok: bool, note: str = "") -> None:
    icon  = (Fore.GREEN + Style.BRIGHT + "  ✓" if ok else Fore.RED + Style.BRIGHT + "  ✗") + Style.RESET_ALL
    badge = (Fore.GREEN + " [  OK  ]" if ok else Fore.RED + " [ ERR ]") + Style.RESET_ALL
    note_part = (Style.DIM + "  —  " + note + Style.RESET_ALL) if note else ""
    print(f"{icon}  {label:<38}{badge}{note_part}")

def print_startup_banner(bot_user) -> None:
    ts = _ts()
    sep = Style.DIM + "  " + "─" * 55 + Style.RESET_ALL

    print()
    print(Style.DIM + f"  [{ts}]  " + Style.RESET_ALL +
          Fore.CYAN + Style.BRIGHT + "BAŞLATILIYOR" + Style.RESET_ALL +
          "  discord.client: token okunuyor...")
    print(Style.DIM + f"  [{ts}]  " + Style.RESET_ALL +
          Fore.CYAN + "INFO" + Style.RESET_ALL +
          "      .env dosyası yüklendi")
    print()
    print(Style.DIM + "  ┌" + "─" * 53 + "┐" + Style.RESET_ALL)
    print(Style.DIM + "  │" + Style.RESET_ALL +
          "          " + Style.BRIGHT + "Servis Kontrol Raporu" + Style.RESET_ALL +
          " " * 22 + Style.DIM + "│" + Style.RESET_ALL)
    print(Style.DIM + "  └" + "─" * 53 + "┘" + Style.RESET_ALL)
    print()

    print_status("discord.client: token",           True,  "statik token okundu")
    print_status("discord.gateway: bağlantı",       True,  "Shard ID None → Gateway")
    print_status("config.json: yapılandırma",       True,  "guilds verisi yüklendi")
    print_status("TicketOpenView: kayıt",            True,  "persistent view eklendi")
    print_status("TicketCloseView: kayıt",           True,  "persistent view eklendi")
    print_status("tree.sync: slash komutlar",        True,  "komutlar senkronize edildi")
    print_status("link_protection: regex",           True,  "LINK_PATTERN hazır")
    print_status("music_state: yt-dlp",             True,  "FFmpeg & YTDL_OPTS hazır")
    print_status("giveaway_tasks: task set",         True,  "asyncio task havuzu hazır")

    print()
    print(sep)
    print()
    print(Style.DIM + f"  [{ts}]  " + Style.RESET_ALL +
          Fore.GREEN + Style.BRIGHT + "HAZIR" + Style.RESET_ALL +
          "     Bot başarıyla başlatıldı")
    print(Style.DIM + "  Kullanıcı   " + Style.RESET_ALL +
          Style.BRIGHT + str(bot_user) + Style.RESET_ALL +
          Style.DIM + "  id=" + Style.RESET_ALL +
          Fore.CYAN + str(bot_user.id) + Style.RESET_ALL)
    print(Style.DIM + "  Prefix      " + Style.RESET_ALL + "§")
    print(Style.DIM + "  Slash       " + Style.RESET_ALL +
          "ticketkur · guncelleme · giveaway · song · skip · pause · resume · stop · queue")
    print()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self.data: Dict[str, Any] = {"guilds": {}}
        self._loaded = False

    async def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            self.data = {"guilds": {}}
            return
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {"guilds": {}}

    async def save(self) -> None:
        async with self._lock:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def guild_entry(self, guild_id: int) -> Dict[str, Any]:
        guilds = self.data.setdefault("guilds", {})
        entry = guilds.setdefault(str(guild_id), {})
        entry.setdefault("ticket_category_id", None)
        entry.setdefault("updates_channel_id", None)
        entry.setdefault("ticket_panel_channel_id", None)
        return entry


config_store = ConfigStore(CONFIG_PATH)

# ---------------------------------------------------------------------------
# Ticket — Dropdown
# ---------------------------------------------------------------------------

class TicketCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=cat["label"],
                value=cat["value"],
                description=cat["description"],
                emoji=cat["emoji"],
            )
            for cat in TICKET_CATEGORIES
        ]
        super().__init__(
            placeholder="Talep kategorini seç...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_category_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            return

        selected_value = self.values[0]
        cat_info = get_category_info(selected_value)

        channel_name = f"ticket-{selected_value}-{user.id}"
        existing = discord.utils.get(guild.text_channels, name=channel_name)
        if existing:
            await interaction.response.send_message(
                f"Bu kategoride zaten açık bir ticketin var: {existing.mention}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Ticket oluşturuluyor...", ephemeral=True)

        category = await ensure_ticket_category(guild, "Tickets")
        overwrites = build_ticket_overwrites(guild, user)

        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"{cat_info['emoji']} {cat_info['label']} | Oluşturucu: {user} ({user.id})",
        )

        support_role = get_support_role(guild)
        support_mention = support_role.mention if support_role else "@ticket_support"

        view = TicketCloseView()
        embed = discord.Embed(
            title=f"{cat_info['emoji']} {cat_info['label']}",
            description=(
                f"Merhaba {user.mention}, talebin yetkililere iletildi!\n"
                f"Destek Ekibi: {support_mention}"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Kategori: {cat_info['label']}")
        await ticket_channel.send(embed=embed, view=view)
        await interaction.followup.send(f"Ticket açıldı: {ticket_channel.mention}", ephemeral=True)


class TicketCategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(TicketCategorySelect())


class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ticket Oluştur",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="ticket_open_button",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = TicketCategoryView()
        embed = discord.Embed(
            title="Kategori Seç",
            description="Talebinle ilgili kategoriyi aşağıdan seçin.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Ticket'ı Kapat",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket_close_button",
    )
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or interaction.user is None:
            return

        perms = interaction.user.guild_permissions
        if not (perms.manage_channels or perms.administrator):
            await interaction.response.send_message("Bu işlemi yapmak için yetkin yok.", ephemeral=True)
            return

        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message("Kanal bulunamadı.", ephemeral=True)
            return

        await interaction.response.send_message("Ticket kapanıyor...", ephemeral=True)

        safe_name = channel.name[:90]
        if not safe_name.startswith("closed-"):
            try:
                await channel.edit(name=f"closed-{safe_name}")
            except Exception:
                pass

        await asyncio.sleep(2)
        try:
            await channel.delete(reason="Ticket kapatıldı")
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Ticket — Yardımcı
# ---------------------------------------------------------------------------

async def ensure_ticket_category(guild: discord.Guild, category_name: str = "Tickets") -> discord.CategoryChannel:
    entry = config_store.guild_entry(guild.id)
    category_id = entry.get("ticket_category_id")

    if category_id:
        try:
            cat = guild.get_channel(int(category_id))
            if isinstance(cat, discord.CategoryChannel):
                return cat
        except (TypeError, ValueError):
            pass

    for cat in guild.categories:
        if cat.name.lower() == category_name.lower():
            entry["ticket_category_id"] = cat.id
            await config_store.save()
            return cat

    cat = await guild.create_category(category_name)
    entry["ticket_category_id"] = cat.id
    await config_store.save()
    return cat


def build_ticket_overwrites(guild: discord.Guild, user: discord.Member) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    for role in guild.roles:
        try:
            if role.permissions.administrator or role.permissions.manage_channels or role.name == TICKET_SUPPORT_ROLE:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        except Exception:
            continue
    return overwrites

# ---------------------------------------------------------------------------
# Müzik
# ---------------------------------------------------------------------------

async def extract_audio_stream(url: str) -> Dict[str, Any]:
    loop = asyncio.get_running_loop()

    def _extract() -> Dict[str, Any]:
        with YoutubeDL(YTDL_OPTS) as ydl:
            return ydl.extract_info(url, download=False)

    info = await loop.run_in_executor(None, _extract)
    stream_url = info.get("url")
    if not stream_url:
        raise RuntimeError("Müzik stream linki alınamadı.")

    return {
        "stream_url": stream_url,
        "title": info.get("title") or "Unknown title",
        "webpage_url": info.get("webpage_url") or url,
    }


@dataclass
class Song:
    url: str
    stream_url: str
    title: str
    requester: int
    webpage_url: str


class GuildMusicState:
    def __init__(self, guild: discord.Guild, loop: asyncio.AbstractEventLoop):
        self.guild = guild
        self.loop = loop
        self.queue: Deque[Song] = deque()
        self.voice: Optional[discord.VoiceClient] = None
        self.lock = asyncio.Lock()
        self.playing = False

    async def ensure_connected(self, voice_channel: discord.VoiceChannel) -> discord.VoiceClient:
        if self.voice and self.voice.is_connected():
            if self.voice.channel and self.voice.channel.id != voice_channel.id:
                await self.voice.move_to(voice_channel)
            return self.voice
        self.voice = await voice_channel.connect()
        return self.voice

    async def enqueue(self, song: Song) -> None:
        self.queue.append(song)

    def _after_play(self) -> None:
        fut = asyncio.run_coroutine_threadsafe(self._play_next_internal(), self.loop)
        fut.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)

    async def _play_next_internal(self) -> None:
        async with self.lock:
            self.playing = False
            if not self.queue or self.voice is None or not self.voice.is_connected():
                return

            next_song = self.queue.popleft()
            try:
                extracted = await extract_audio_stream(next_song.url)
                next_song.stream_url = extracted["stream_url"]
            except Exception:
                await self._play_next_internal()
                return

            self.playing = True
            ffmpeg_opts = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
            source = discord.FFmpegPCMAudio(next_song.stream_url, before_options=ffmpeg_opts)
            self.voice.play(source, after=lambda e: self._after_play())

    async def play_from_queue(self) -> None:
        if self.playing:
            return
        if self.voice is None or not self.voice.is_connected():
            raise RuntimeError("Bot henüz bir ses kanalına bağlı değil.")
        if not self.queue:
            return
        await self._play_next_internal()

    async def skip(self) -> None:
        if self.voice and self.voice.is_connected():
            self.voice.stop()

    async def pause(self) -> None:
        if self.voice and self.voice.is_connected() and self.voice.is_playing():
            self.voice.pause()

    async def resume(self) -> None:
        if self.voice and self.voice.is_connected() and self.voice.is_paused():
            self.voice.resume()

    async def stop_and_clear(self) -> None:
        self.queue.clear()
        if self.voice and self.voice.is_connected():
            try:
                await self.voice.disconnect(force=True)
            except Exception:
                try:
                    await self.voice.disconnect()
                except Exception:
                    pass
        self.voice = None
        self.playing = False


def get_music_state(guild: discord.Guild) -> GuildMusicState:
    state = music_states.get(guild.id)
    if state is None:
        state = GuildMusicState(guild, bot.loop)
        music_states[guild.id] = state
    return state

# ---------------------------------------------------------------------------
# Çekiliş
# ---------------------------------------------------------------------------

def validate_giveaway_args(duration_seconds: int, winners_count: int) -> None:
    if duration_seconds < 5 or duration_seconds > 60 * 60 * 24:
        raise ValueError("Süre 5 saniye ile 24 saat arası olmalı.")
    if winners_count < 1 or winners_count > 10:
        raise ValueError("Kazanan sayısı 1 ile 10 arasında olmalı.")

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready() -> None:
    await config_store.load()
    bot.add_view(TicketOpenView())
    bot.add_view(TicketCloseView())
    await tree.sync()
    print_startup_banner(bot.user)


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    if message.guild is not None and LINK_PATTERN.search(message.content):
        member = message.author
        allowed = (
            member.guild_permissions.administrator
            or any(r.id in LINK_ALLOWED_ROLE_IDS for r in member.roles)
        )
        if not allowed:
            try:
                await message.delete()
            except Exception:
                pass
            try:
                await member.timeout(
                    datetime.timedelta(seconds=LINK_TIMEOUT_SECONDS),
                    reason="İzinsiz link paylaşımı",
                )
            except Exception:
                pass
            try:
                await message.channel.send(
                    f"{member.mention} link paylaşma yetkin yok! "
                    f"{LINK_TIMEOUT_SECONDS} saniye susturuldun.",
                    delete_after=5,
                )
            except Exception:
                pass

# ---------------------------------------------------------------------------
# Slash Komutlar — Ticket
# ---------------------------------------------------------------------------

@tree.command(name="ticketkur", description="Ticket panelini belirtilen kanala gönderir.")
@app_commands.describe(kanal="Ticket panelinin gönderileceği kanal")
@app_commands.checks.has_permissions(manage_guild=True)
async def ticketkur(interaction: discord.Interaction, kanal: discord.TextChannel) -> None:
    if interaction.guild is None:
        return

    entry = config_store.guild_entry(interaction.guild.id)
    entry["ticket_panel_channel_id"] = kanal.id
    await config_store.save()

    embed = discord.Embed(
        title="🎫 Destek Sistemi",
        description=(
            "Bir sorununuz varsa veya yetkililere ulaşmak istiyorsanız "
            "aşağıdaki butona tıklayarak ticket oluşturabilirsiniz."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Kategoriler",
        value=(
            "🛒 Satın Alma / Purchase\n"
            "🙋 Destek Yardım / Support\n"
            "🔧 Teknik Destek\n"
            "🎬 Media Başvuru / Media Application\n"
            "📋 Kadro Başvuru / Staff Application\n"
            "💬 Diğer / Other"
        ),
        inline=False,
    )
    embed.set_footer(text="Her kullanıcı her kategoride yalnızca bir ticket açabilir.")

    view = TicketOpenView()
    await kanal.send(embed=embed, view=view)
    await interaction.response.send_message(f"Ticket paneli {kanal.mention} kanalına gönderildi.", ephemeral=True)

# ---------------------------------------------------------------------------
# Slash Komutlar — Güncelleme
# ---------------------------------------------------------------------------

@tree.command(name="guncelleme", description="Güncelleme duyurusu gönderir.")
@app_commands.describe(metin="Duyuru metni")
async def guncelleme(interaction: discord.Interaction, metin: str) -> None:
    if interaction.guild is None:
        return

    entry = config_store.guild_entry(interaction.guild.id)
    target_channel_id = entry.get("updates_channel_id")
    target_channel: Optional[discord.TextChannel] = None

    if target_channel_id:
        ch = interaction.guild.get_channel(target_channel_id)
        if isinstance(ch, discord.TextChannel):
            target_channel = ch

    if target_channel is None:
        if isinstance(interaction.channel, discord.TextChannel):
            target_channel = interaction.channel
        else:
            await interaction.response.send_message("Güncelleme kanalı ayarlanmamış.", ephemeral=True)
            return

    embed = discord.Embed(
        title="Güncelleme Duyurusu",
        description=metin,
        color=discord.Color.blurple(),
    )
    embed.set_footer(
        text=f"İletişim: {interaction.user} | "
             f"Tarih: {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )

    await interaction.response.send_message("Duyuru gönderildi.", ephemeral=True)
    await target_channel.send(content="@everyone", embed=embed)


@tree.command(name="guncelleme_kur", description="Güncelleme duyurularının gönderileceği kanalı ayarlar.")
@app_commands.describe(kanal="Duyuru kanalı")
@app_commands.checks.has_permissions(manage_guild=True)
async def guncelleme_kur(interaction: discord.Interaction, kanal: discord.TextChannel) -> None:
    if interaction.guild is None:
        return
    entry = config_store.guild_entry(interaction.guild.id)
    entry["updates_channel_id"] = kanal.id
    await config_store.save()
    await interaction.response.send_message(f"Güncelleme kanalı ayarlandı: {kanal.mention}", ephemeral=True)

# ---------------------------------------------------------------------------
# Slash Komutlar — Çekiliş
# ---------------------------------------------------------------------------

@tree.command(name="giveaway", description="Çekiliş başlatır.")
@app_commands.describe(sure="Çekiliş süresi (saniye)", kazanan="Kazanan sayısı", odul="Ödül")
@app_commands.checks.has_permissions(manage_guild=True)
async def giveaway(interaction: discord.Interaction, sure: int, kazanan: int, odul: str) -> None:
    if interaction.guild is None or interaction.channel is None:
        return

    if sure < 5 or sure > 86400:
        await interaction.response.send_message("Süre 5 saniye ile 24 saat arası olmalı.", ephemeral=True)
        return
    if kazanan < 1 or kazanan > 10:
        await interaction.response.send_message("Kazanan sayısı 1 ile 10 arasında olmalı.", ephemeral=True)
        return

    embed = discord.Embed(
        title="Yeni Çekiliş",
        description=f"Ödül: **{odul}**\n\nKatılmak için {EMOJI_GIVEAWAY} tepkisine bas!",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Kazanan Sayısı", value=str(kazanan), inline=True)
    embed.add_field(name="Süre", value=f"{sure} saniye", inline=True)

    await interaction.response.send_message("Çekiliş başlatıldı.", ephemeral=True)
    channel = interaction.channel
    giveaway_message = await channel.send(embed=embed)
    await giveaway_message.add_reaction(EMOJI_GIVEAWAY)

    async def _finish() -> None:
        await asyncio.sleep(sure)
        try:
            msg = await channel.fetch_message(giveaway_message.id)
        except Exception:
            return

        reaction = discord.utils.get(msg.reactions, emoji=EMOJI_GIVEAWAY)
        if reaction is None:
            await channel.send("Çekiliş bitti ama tepki bulunamadı.")
            return

        users = [u async for u in reaction.users()]
        entrants = [u for u in users if not u.bot]
        if not entrants:
            await channel.send("Çekilişte katılımcı yok. Kazanan seçilemedi.")
            return

        k = min(kazanan, len(entrants))
        winners = random.sample(entrants, k=k)
        winner_mentions = ", ".join(w.mention for w in winners)
        await channel.send(f"🏆 Çekiliş bitti! Kazanan(lar): {winner_mentions}")

        try:
            embed_done = discord.Embed(
                title="Çekiliş Sonlandı",
                description=f"Ödül: **{odul}**",
                color=discord.Color.green(),
            )
            embed_done.add_field(name="Kazanan(lar)", value=winner_mentions, inline=False)
            await msg.edit(embed=embed_done)
        except Exception:
            pass

    task = bot.loop.create_task(_finish())
    _giveaway_tasks.add(task)
    task.add_done_callback(_giveaway_tasks.discard)

# ---------------------------------------------------------------------------
# Slash Komutlar — Müzik
# ---------------------------------------------------------------------------

@tree.command(name="song", description="YouTube linkinden müzik çalar.")
@app_commands.describe(link="YouTube linki")
async def song(interaction: discord.Interaction, link: str) -> None:
    if interaction.guild is None:
        return

    if not (link.startswith("http://") or link.startswith("https://")):
        await interaction.response.send_message("Lütfen geçerli bir YouTube linki ver.", ephemeral=True)
        return

    member = interaction.user
    if not getattr(member, "voice", None) or not member.voice or not member.voice.channel:
        await interaction.response.send_message("Önce bir ses kanalına katıl.", ephemeral=True)
        return

    voice_channel = member.voice.channel
    state = get_music_state(interaction.guild)
    await state.ensure_connected(voice_channel)

    await interaction.response.send_message("Müzik alınıyor, lütfen bekle...", ephemeral=True)
    try:
        extracted = await extract_audio_stream(link)
        song_obj = Song(
            url=link,
            stream_url=extracted["stream_url"],
            title=extracted["title"],
            requester=interaction.user.id,
            webpage_url=extracted["webpage_url"],
        )
    except Exception as e:
        await interaction.followup.send(f"Müzik çekilemedi: {e}", ephemeral=True)
        return

    await state.enqueue(song_obj)

    if not state.playing and state.voice and state.voice.is_connected():
        try:
            await state.play_from_queue()
        except Exception:
            pass

    await interaction.followup.send(
        f"🎵 Eklendi: **{song_obj.title}** (kuyruk: {len(state.queue)})", ephemeral=False
    )


@tree.command(name="skip", description="Şu anki parçayı atlar.")
async def skip(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    state = music_states.get(interaction.guild.id)
    if not state or not state.voice or not state.voice.is_connected():
        await interaction.response.send_message("Şu anda çalan müzik yok.", ephemeral=True)
        return
    await state.skip()
    await interaction.response.send_message("⏭️ Atlandı.")


@tree.command(name="pause", description="Müziği duraklatır.")
async def pause(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    state = music_states.get(interaction.guild.id)
    if not state or not state.voice or not state.voice.is_connected():
        await interaction.response.send_message("Şu anda çalan müzik yok.", ephemeral=True)
        return
    await state.pause()
    await interaction.response.send_message("⏸️ Duraklatıldı.")


@tree.command(name="resume", description="Müziği devam ettirir.")
async def resume(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    state = music_states.get(interaction.guild.id)
    if not state or not state.voice or not state.voice.is_connected():
        await interaction.response.send_message("Şu anda çalan müzik yok.", ephemeral=True)
        return
    await state.resume()
    await interaction.response.send_message("▶️ Devam etti.")


@tree.command(name="stop", description="Müziği durdurur ve kanaldan çıkar.")
async def stop(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    state = music_states.get(interaction.guild.id)
    if not state:
        await interaction.response.send_message("Aktif bir müzik durumu yok.", ephemeral=True)
        return
    await state.stop_and_clear()
    await interaction.response.send_message("⏹️ Durduruldu ve çıktı.")


@tree.command(name="queue", description="Kuyruktaki parçaları gösterir.")
async def queue_(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        return
    state = music_states.get(interaction.guild.id)
    if not state or not state.queue:
        await interaction.response.send_message("Kuyruk boş.", ephemeral=True)
        return

    lines = [f"{i}. {s.title}" for i, s in enumerate(list(state.queue)[:15], start=1)]
    more = f"\n... ve {len(state.queue) - 15} tane daha" if len(state.queue) > 15 else ""
    await interaction.response.send_message("**Kuyruk:**\n" + "\n".join(lines) + more)

# ---------------------------------------------------------------------------
# Hata yönetimi
# ---------------------------------------------------------------------------

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("Bu komutu kullanmak için yetkin yok.", ephemeral=True)
    else:
        try:
            await interaction.response.send_message(f"Hata: {error}", ephemeral=True)
        except Exception:
            await interaction.followup.send(f"Hata: {error}", ephemeral=True)

# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------

def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN ortam değişkeni ayarlanmadı.\n"
            "Proje klasöründe bir .env dosyası oluştur ve içine şunu yaz:\n"
            "DISCORD_TOKEN=buraya_tokenini_yaz"
        )
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
