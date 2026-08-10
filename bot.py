from collections import defaultdict, deque
import asyncio
import os
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

# 設定機器人 Intents (開啟語音、訊息內容與成員權限)
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# FFmpeg 與 yt-dlp 設定
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

YTDL_OPTIONS = {
    'format': 'bestaudio/best',
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

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# 播放清單
song_queues = defaultdict(deque)

# ==================== 防詐騙與防炸群設定 ====================
SCAM_KEYWORDS = [
    "nitro-discord.com",
    "discord-airdrop",
    "free-nitro",
    "steamcommunity.ru/gift",
    "free discord nitro",
]

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"已同步 {len(synced)} 個斜線指令")
    except Exception as e:
        print(f"同步斜線指令失敗: {e}")
    print(f"機器人已成功上線：{bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content_lower = message.content.lower()
    for keyword in SCAM_KEYWORDS:
        if keyword in content_lower:
            try:
                await message.delete()
                await message.channel.send(f"⚠️ 偵測到疑似可疑連結/關鍵字，已自動刪除 {message.author.mention} 的訊息。", delete_after=5)
            except Exception as e:
                print(f"刪除詐騙訊息失敗: {e}")
            return

    await bot.process_commands(message)

# ==================== 音樂播放功能 ====================
async def play_next(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if song_queues[guild_id]:
        next_song = song_queues[guild_id].popleft()
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            source = discord.FFmpegPCMAudio(next_song['url'], **FFMPEG_OPTIONS)
            voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop))
            await interaction.channel.send(f"🎵 正在播放：**{next_song['title']}**")
    else:
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()

@bot.tree.command(name="play", description="播放 YouTube 音樂或加入佇列")
@app_commands.guild_only()
@app_commands.describe(url="YouTube 網址或搜尋關鍵字")
async def play(interaction: discord.Interaction, url: str):
    await interaction.response.defer()
    
    # 強制向 Discord API 精確抓取當前成員的語音狀態
    member = interaction.guild.get_member(interaction.user.id)
    if not member or not member.voice:
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except Exception:
            pass

    if not member or not member.voice or not member.voice.channel:
        await interaction.followup.send("❌ 請先加入一個語音頻道！")
        return

    voice_channel = member.voice.channel
    voice_client = interaction.guild.voice_client

    if not voice_client:
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)

    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        if 'entries' in data:
            data = data['entries'][0]
    except Exception as e:
        await interaction.followup.send(f"❌ 解析歌曲失敗：{e}")
        return

    song_info = {
        'url': data['url'],
        'title': data.get('title', '未知歌曲')
    }

    if voice_client.is_playing() or voice_client.is_paused():
        song_queues[interaction.guild_id].append(song_info)
        await interaction.followup.send(f"✅ 已加入佇列：**{song_info['title']}**")
    else:
        source = discord.FFmpegPCMAudio(song_info['url'], **FFMPEG_OPTIONS)
        voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop))
        await interaction.followup.send(f"🎵 開始播放：**{song_info['title']}**")

@bot.tree.command(name="skip", description="跳過當前播放的歌曲")
@app_commands.guild_only()
async def skip(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("⏭️ 已跳過當前歌曲！")
    else:
        await interaction.response.send_message("❌ 目前沒有正在播放的歌曲！")

@bot.tree.command(name="queue", description="查看當前的待播放佇列")
@app_commands.guild_only()
async def queue(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    que = song_queues[guild_id]
    
    if not que:
        await interaction.response.send_message("📜 目前播放佇列是空的！")
        return

    queue_list = "\n".join([f"**{i+1}.** {song['title']}" for i, song in enumerate(que)])
    embed = discord.Embed(title="🎵 播放佇列", description=queue_list, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="stop", description="停止播放並清空佇列，讓機器人退出頻道")
@app_commands.guild_only()
async def stop(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        song_queues[interaction.guild_id].clear()
        voice_client.stop()
        await voice_client.disconnect()
        await interaction.response.send_message("⏹️ 已停止播放、清空佇列並離開頻道。")
    else:
        await interaction.response.send_message("❌ 機器人目前不在任何語音頻道中。")

# 啟動機器人
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ 錯誤：未找到 DISCORD_TOKEN 環境變數")
