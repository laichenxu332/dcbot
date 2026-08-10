from collections import defaultdict, deque
import discord
from discord import app_commands
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True  # 確保包含這行

bot = commands.Bot(command_prefix='!', intents=intents)    

# FFmpeg 與 yt-dlp 設定
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

YTDL_OPTIONS = {
    'format': 'best',  # 改為 best
    'extract_flat': False,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extractor_args': {
        'youtube': {
            'player_client': ['mweb', 'tvhtml5', 'ios']
        }
    }
}
# ==================== 防詐騙與防炸群設定 ====================

# 1. 詐騙關鍵字黑名單
SCAM_KEYWORDS = [
    "nitro-discord.com",
    "discord-airdrop",
    "free-nitro",
    "steamcommunity.ru/gift",
    "free discord nitro",
    "steam-gift.com",
    "airdrop-discord.com",
    "claim your nitro",
    "discord.gifts/"
]

# 2. 防炸群 / 快速洗頻追蹤 (記錄每個使用者最近發送訊息的時間)
# 規則：如果在 4 秒內發送超過 5 則訊息，視為洗頻並自動踢出
message_tracking = defaultdict(deque)
SPAM_TIME_WINDOW = 4.0  # 時間窗口 (秒)
SPAM_LIMIT = 5          # 訊息數量上限

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"已同步 {len(synced)} 個斜線指令！")
    except Exception as e:
        print(f"同步指令失敗: {e}")
    print(f"機器人已成功上線：{bot.user}")

# ==================== 安全防護自動偵測事件 ====================
@bot.event
async def on_message(message: discord.Message):
    # 略過機器人自己發的訊息
    if message.author.bot:
        return

    # 管理員不受防護限制
    if message.author.guild_permissions.administrator:
        await bot.process_commands(message)
        return

    author_id = message.author.id
    current_time = asyncio.get_event_loop().time()

    # --- 防炸群 (Anti-Spam / Raid) 機制：自動踢出 ---
    user_messages = message_tracking[author_id]
    
    # 清除超過時間窗口的舊紀錄
    while user_messages and current_time - user_messages[0] > SPAM_TIME_WINDOW:
        user_messages.popleft()
        
    user_messages.append(current_time)

    # 如果短時間內發送太多訊息（洗頻炸群）
    if len(user_messages) > SPAM_LIMIT:
        try:
            # 刪除當前訊息
            await message.delete()
            
            # 自動踢出 (Kick) 該使用者
            await message.author.kick(reason="防炸群系統：偵測到短時間大量洗頻")
            
            warning_msg = await message.channel.send(
                f"🚨 {message.author.mention} **觸發防炸群系統！因短時間內發送大量訊息已被自動踢出伺服器。**"
            )
            await asyncio.sleep(5)
            await warning_msg.delete()
        except discord.Forbidden:
            print("❌ 權限不足，無法踢出洗頻成員！")
        except Exception:
            pass
        return

    # --- 防詐騙釣魚連結機制 ---
    content_lower = message.content.lower()
    for keyword in SCAM_KEYWORDS:
        if keyword in content_lower:
            try:
                await message.delete()
                warning_msg = await message.channel.send(
                    f"⚠️ {message.author.mention} **偵測到疑似釣魚/詐騙訊息，系統已自動攔截並刪除！**"
                )
                await asyncio.sleep(5)
                await warning_msg.delete()
            except discord.Forbidden:
                print("❌ 權限不足，無法刪除訊息或發送警告！")
            except discord.HTTPException:
                pass
            return

    await bot.process_commands(message)

# ==================== 音樂控制按鈕介面 (UI View) ====================

class MusicControlView(discord.ui.View):
    def __init__(self, vc, title, uploader, duration, thumbnail):
        super().__init__(timeout=None)
        self.vc = vc
        self.title = title
        self.uploader = uploader
        self.duration = duration
        self.thumbnail = thumbnail

    def create_embed(self):
        vol = int(self.vc.source.volume * 100) if (self.vc and self.vc.source) else 100
        
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**[{self.title}]**",
            color=discord.Color.blue()
        )
        embed.add_field(name="👤 Author", value=self.uploader, inline=True)
        embed.add_field(name="⌛ Duration", value=self.duration, inline=True)
        embed.add_field(name="🔊 Volume", value=f"{vol}%", inline=True)
        
        if self.thumbnail:
            embed.set_thumbnail(url=self.thumbnail)
            
        return embed

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary)
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.vc or not self.vc.is_connected():
            await interaction.response.send_message("機器人不在語音頻道中！", ephemeral=True)
            return

        if self.vc.is_playing():
            self.vc.pause()
            await interaction.response.send_message("⏸️ 已暫停播放", ephemeral=True)
        elif self.vc.is_paused():
            self.vc.resume()
            await interaction.response.send_message("▶️ 繼續播放", ephemeral=True)
        else:
            await interaction.response.send_message("目前沒有音樂在播放", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.vc and self.vc.is_connected():
            await self.vc.disconnect()
            await interaction.response.send_message("⏹️ 已停止播放並離開頻道！")
            self.stop()
        else:
            await interaction.response.send_message("機器人不在語音頻道中！", ephemeral=True)

    @discord.ui.button(emoji="🔉", style=discord.ButtonStyle.secondary)
    async def vol_down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.vc and self.vc.source and isinstance(self.vc.source, discord.PCMVolumeTransformer):
            current_vol = int(self.vc.source.volume * 100)
            new_vol = max(0, current_vol - 25)
            self.vc.source.volume = new_vol / 100.0
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.send_message("無法調整音量！", ephemeral=True)

    @discord.ui.button(emoji="🔊", style=discord.ButtonStyle.secondary)
    async def vol_up_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.vc and self.vc.source and isinstance(self.vc.source, discord.PCMVolumeTransformer):
            current_vol = int(self.vc.source.volume * 100)
            new_vol = min(200, current_vol + 25)
            self.vc.source.volume = new_vol / 100.0
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.send_message("無法調整音量！", ephemeral=True)

# ==================== 斜線指令區域 ====================

@bot.tree.command(name="play", description="播放 YouTube 音樂並開啟面板")
@app_commands.describe(url="YouTube 網址")
async def play(interaction: discord.Interaction, url: str):
    if not interaction.user.voice:
        await interaction.response.send_message("請先加入一個語音頻道！", ephemeral=True)
        return

    await interaction.response.defer()

    channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client

    if vc is None:
        vc = await channel.connect()
    elif vc.channel != channel:
        await vc.move_to(channel)

    try:
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
            info = ytdl.extract_info(url, download=False)
            audio_url = info['url']
            title = info.get('title', '未知歌名')
            uploader = info.get('uploader', '未知歌手')
            duration_sec = info.get('duration', 0)
            thumbnail = info.get('thumbnail', None)
            duration = str(datetime.timedelta(seconds=duration_sec))

        ffmpeg_source = discord.FFmpegPCMAudio(audio_url, executable=imageio_ffmpeg.get_ffmpeg_exe(), **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(ffmpeg_source, volume=1.0)

        vc.play(source)

        view = MusicControlView(vc, title, uploader, duration, thumbnail)
        await interaction.followup.send(embed=view.create_embed(), view=view)

    except Exception as e:
        await interaction.followup.send("❌ 無法讀取該網址，請確認是否為有效的 YouTube 連結！")

@bot.tree.command(name="volume", description="調整音樂音量 (+25, -25 或直接輸入 0~200)")
@app_commands.describe(change="輸入音量變化，例如 +25、-25 或目標音量數值 (0~200)")
async def volume(interaction: discord.Interaction, change: str):
    vc = interaction.guild.voice_client

    if not vc or not vc.is_playing():
        await interaction.response.send_message("目前沒有正在播放的音樂！", ephemeral=True)
        return

    if not isinstance(vc.source, discord.PCMVolumeTransformer):
        await interaction.response.send_message("當前的音訊不支援音量調整！", ephemeral=True)
        return

    current_volume = int(vc.source.volume * 100)
    change_str = change.strip()

    try:
        if change_str.startswith('+') or change_str.startswith('-'):
            new_volume = current_volume + int(change_str)
        else:
            new_volume = int(change_str)

        new_volume = max(0, min(200, new_volume))
        vc.source.volume = new_volume / 100.0

        await interaction.response.send_message(f"🔊 音量已調整為：**{new_volume}%** (原本: {current_volume}%)")
    except ValueError:
        await interaction.response.send_message("請輸入有效的數字，例如 `+25`、`-25` 或 `80`！", ephemeral=True)

@bot.tree.command(name="leave", description="讓機器人離開語音頻道")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        await interaction.response.send_message("👋 已離開語音頻道！")
    else:
        await interaction.response.send_message("機器人目前不在任何語音頻道中！", ephemeral=True)

# ==================== 管理員斜線指令 ====================

@bot.tree.command(name="warn", description="警告成員並透過私訊通知內容")
@app_commands.describe(member="要警告的成員", reason="警告原因")
@app_commands.checks.has_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    try:
        embed = discord.Embed(
            title="⚠️ 伺服器警告通知",
            description=f"你在 **{interaction.guild.name}** 收到了一條警告！",
            color=discord.Color.gold()
        )
        embed.add_field(name="警告原因", value=reason, inline=False)
        embed.add_field(name="執行管理員", value=interaction.user.mention, inline=False)
        
        await member.send(embed=embed)
        dm_status = "（已成功發送私訊通知）"
    except discord.Forbidden:
        dm_status = "（⚠️ 該成員已關閉私訊，無法傳送私訊通知）"

    await interaction.response.send_message(
        f"✅ 已成功警告 {member.mention}！\n**原因：** {reason} {dm_status}"
    )

@bot.tree.command(name="ban", description="將成員停權（封鎖）")
@app_commands.describe(member="要停權的成員", reason="停權原因")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "未提供原因"):
    try:
        embed = discord.Embed(
            title="🚫 伺服器停權通知",
            description=f"你已被 **{interaction.guild.name}** 停權（封鎖）！",
            color=discord.Color.red()
        )
        embed.add_field(name="停權原因", value=reason, inline=False)
        await member.send(embed=embed)
    except discord.Forbidden:
        pass

    try:
        await member.ban(reason=reason)
        await interaction.response.send_message(f"⛔ 已將成員 {member.mention} 停權！\n**原因：** {reason}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ 機器人權限不足，無法將該成員停權（請檢查機器人身分組順序）！", ephemeral=True)

@warn.error
@ban.error
async def admin_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ 你沒有權限使用此管理指令！", ephemeral=True)

import os

bot.run(os.getenv('DISCORD_TOKEN'))
