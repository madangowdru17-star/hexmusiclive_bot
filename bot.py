import os
import asyncio
from datetime import datetime
from typing import Optional, Dict, List
import yt_dlp as youtube_dl
import ffmpeg
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ChatMemberStatus
from pytgcalls import PyTgCalls, StreamType
from pytgcalls.types import Update
from pytgcalls.types.input_stream import AudioPiped, AudioVideoPiped
from pytgcalls.types.input_stream.quality import HighQualityAudio, HighQualityVideo
from pytgcalls.exceptions import GroupCallNotFound, NoActiveGroupCall

# Bot configuration from environment variables
API_ID = int(os.environ.get("36210672"))
API_HASH = os.environ.get("55358a88bde10e465d79913ff4ae0121")
BOT_TOKEN = os.environ.get("8743498360:AAFbCBhzXASAqLoquu0S7sHwqMrdVDHXq3w")

# Initialize Pyrogram client
app = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Initialize PyTgCalls
call = PyTgCalls(app)

# Global variables for queue management
queues: Dict[int, List[Dict]] = {}
current_tracks: Dict[int, Dict] = {}
voice_chat_status: Dict[int, bool] = {}

# YouTube download options
ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'extract_flat': False,
    'geo_bypass': True,
    'nocheckcertificate': True,
    'cookiefile': 'cookies.txt'  # Optional: Add for age-restricted content
}

def get_ydl():
    """Get YouTube DL instance"""
    return youtube_dl.YoutubeDL(ydl_opts)

def format_duration(seconds: int) -> str:
    """Format duration in seconds to mm:ss"""
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes:02d}:{seconds:02d}"

async def get_audio_info(query: str) -> Optional[Dict]:
    """Extract audio information from YouTube"""
    try:
        with get_ydl() as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)
            if 'entries' in info:
                info = info['entries'][0]
            
            return {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'url': info.get('webpage_url', ''),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', 'Unknown')
            }
    except Exception as e:
        print(f"Error getting audio info: {e}")
        return None

async def get_audio_stream_url(url: str) -> Optional[str]:
    """Get best audio stream URL from YouTube"""
    try:
        with get_ydl() as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            # Get best audio-only format
            audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
            if audio_formats:
                best_audio = max(audio_formats, key=lambda f: f.get('abr', 0))
                return best_audio.get('url')
            return None
    except Exception as e:
        print(f"Error getting stream URL: {e}")
        return None

async def play_next(chat_id: int):
    """Play next song in queue"""
    if chat_id in queues and queues[chat_id]:
        next_track = queues[chat_id].pop(0)
        current_tracks[chat_id] = next_track
        
        stream_url = await get_audio_stream_url(next_track['url'])
        if stream_url:
            try:
                await call.change_stream(
                    chat_id,
                    AudioPiped(
                        stream_url,
                        HighQualityAudio()
                    )
                )
                await app.send_message(
                    chat_id,
                    f"🎵 **Now Playing:** {next_track['title']}\n"
                    f"⏱️ **Duration:** {format_duration(next_track['duration'])}\n"
                    f"👤 **Requested by:** {next_track['requester']}"
                )
            except Exception as e:
                print(f"Error playing next: {e}")
                await app.send_message(chat_id, "❌ Error playing next song. Skipping...")
                await play_next(chat_id)
        else:
            await app.send_message(chat_id, "❌ Failed to get stream URL. Skipping...")
            await play_next(chat_id)
    else:
        # No more songs in queue
        current_tracks.pop(chat_id, None)

async def ensure_voice_chat(chat_id: int, message: Message) -> bool:
    """Ensure bot is in voice chat"""
    if chat_id in voice_chat_status and voice_chat_status[chat_id]:
        return True
    
    # Check if bot is already in voice chat
    try:
        await call.get_group_call(chat_id)
        voice_chat_status[chat_id] = True
        return True
    except GroupCallNotFound:
        # Not in voice chat
        return False

async def join_voice_chat(chat_id: int, message: Message) -> bool:
    """Join voice chat"""
    try:
        # Check if user is in voice chat
        sender = await app.get_chat_member(chat_id, message.from_user.id)
        if not sender.voice_chat:
            await message.reply("❌ You need to be in a voice chat first!")
            return False
        
        # Join voice chat
        await call.join_group_call(
            chat_id,
            AudioPiped(
                "https://filesamples.com/samples/audio/mp3/sample3.mp3",  # Dummy stream
                HighQualityAudio()
            ),
            stream_type=StreamType().pulse_stream
        )
        voice_chat_status[chat_id] = True
        return True
    except Exception as e:
        print(f"Error joining voice chat: {e}")
        await message.reply("❌ Failed to join voice chat. Make sure I have admin permissions!")
        return False

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    await message.reply(
        "🎵 **Music Bot**\n\n"
        "I can play music in group voice chats!\n\n"
        "**Commands:**\n"
        "/join - Join voice chat\n"
        "/leave - Leave voice chat\n"
        "/play [song] - Play a song\n"
        "/skip - Skip current song\n"
        "/pause - Pause music\n"
        "/resume - Resume music\n"
        "/stop - Stop music\n\n"
        "**Usage:**\n"
        "1. Add me to your group\n"
        "2. Make me admin\n"
        "3. Join voice chat\n"
        "4. Send /join\n"
        "5. Send /play [song name or YouTube URL]",
        disable_web_page_preview=True
    )

@app.on_message(filters.command("join") & filters.group)
async def join_command(client: Client, message: Message):
    """Handle /join command"""
    chat_id = message.chat.id
    
    if await ensure_voice_chat(chat_id, message):
        await message.reply("✅ Already connected to voice chat!")
        return
    
    if await join_voice_chat(chat_id, message):
        await message.reply("✅ Joined voice chat! Ready to play music.")
    else:
        await message.reply("❌ Failed to join voice chat!")

@app.on_message(filters.command("leave") & filters.group)
async def leave_command(client: Client, message: Message):
    """Handle /leave command"""
    chat_id = message.chat.id
    
    if not await ensure_voice_chat(chat_id, message):
        await message.reply("❌ I'm not in a voice chat!")
        return
    
    try:
        await call.leave_group_call(chat_id)
        voice_chat_status[chat_id] = False
        # Clear queue for this chat
        queues.pop(chat_id, None)
        current_tracks.pop(chat_id, None)
        await message.reply("👋 Left voice chat!")
    except Exception as e:
        print(f"Error leaving voice chat: {e}")
        await message.reply("❌ Failed to leave voice chat!")

@app.on_message(filters.command("play") & filters.group)
async def play_command(client: Client, message: Message):
    """Handle /play command"""
    chat_id = message.chat.id
    
    # Check if user provided a query
    if len(message.command) < 2:
        await message.reply("❌ Please provide a song name or YouTube URL!\n\nExample: `/play Despacito`")
        return
    
    query = " ".join(message.command[1:])
    requester = message.from_user.first_name
    
    # Ensure bot is in voice chat
    if not await ensure_voice_chat(chat_id, message):
        if not await join_voice_chat(chat_id, message):
            return
    
    # Send searching message
    search_msg = await message.reply(f"🔍 Searching: `{query}`...")
    
    # Get audio information
    audio_info = await get_audio_info(query)
    if not audio_info:
        await search_msg.edit("❌ Failed to find song! Please try another query.")
        return
    
    # Prepare track info
    track = {
        'title': audio_info['title'],
        'duration': audio_info['duration'],
        'url': audio_info['url'],
        'requester': requester,
        'thumbnail': audio_info['thumbnail'],
        'uploader': audio_info['uploader']
    }
    
    # Check if something is playing
    if chat_id in current_tracks:
        # Add to queue
        if chat_id not in queues:
            queues[chat_id] = []
        queues[chat_id].append(track)
        
        await search_msg.edit(
            f"✅ **Added to queue:**\n"
            f"🎵 {track['title']}\n"
            f"⏱️ Duration: {format_duration(track['duration'])}\n"
            f"👤 Requester: {track['requester']}\n"
            f"📊 Position: {len(queues[chat_id])}"
        )
    else:
        # Play immediately
        current_tracks[chat_id] = track
        stream_url = await get_audio_stream_url(track['url'])
        
        if stream_url:
            try:
                await call.change_stream(
                    chat_id,
                    AudioPiped(
                        stream_url,
                        HighQualityAudio()
                    )
                )
                await search_msg.edit(
                    f"🎵 **Now Playing:**\n"
                    f"{track['title']}\n"
                    f"⏱️ Duration: {format_duration(track['duration'])}\n"
                    f"👤 Requested by: {track['requester']}"
                )
            except Exception as e:
                print(f"Error playing: {e}")
                await search_msg.edit("❌ Failed to play song!")
                current_tracks.pop(chat_id, None)
        else:
            await search_msg.edit("❌ Failed to get stream URL!")
            current_tracks.pop(chat_id, None)

@app.on_message(filters.command("skip") & filters.group)
async def skip_command(client: Client, message: Message):
    """Handle /skip command"""
    chat_id = message.chat.id
    
    if not await ensure_voice_chat(chat_id, message):
        await message.reply("❌ I'm not in a voice chat!")
        return
    
    if chat_id not in current_tracks:
        await message.reply("❌ No song is currently playing!")
        return
    
    # Skip current song
    current_tracks.pop(chat_id, None)
    await play_next(chat_id)
    await message.reply("⏭️ Skipped current song!")

@app.on_message(filters.command("pause") & filters.group)
async def pause_command(client: Client, message: Message):
    """Handle /pause command"""
    chat_id = message.chat.id
    
    if not await ensure_voice_chat(chat_id, message):
        await message.reply("❌ I'm not in a voice chat!")
        return
    
    try:
        await call.pause_stream(chat_id)
        await message.reply("⏸️ Paused music!")
    except Exception as e:
        print(f"Error pausing: {e}")
        await message.reply("❌ Failed to pause music!")

@app.on_message(filters.command("resume") & filters.group)
async def resume_command(client: Client, message: Message):
    """Handle /resume command"""
    chat_id = message.chat.id
    
    if not await ensure_voice_chat(chat_id, message):
        await message.reply("❌ I'm not in a voice chat!")
        return
    
    try:
        await call.resume_stream(chat_id)
        await message.reply("▶️ Resumed music!")
    except Exception as e:
        print(f"Error resuming: {e}")
        await message.reply("❌ Failed to resume music!")

@app.on_message(filters.command("stop") & filters.group)
async def stop_command(client: Client, message: Message):
    """Handle /stop command"""
    chat_id = message.chat.id
    
    if not await ensure_voice_chat(chat_id, message):
        await message.reply("❌ I'm not in a voice chat!")
        return
    
    try:
        # Clear queue and stop
        queues.pop(chat_id, None)
        current_tracks.pop(chat_id, None)
        await call.stop_stream(chat_id)
        await message.reply("⏹️ Stopped music and cleared queue!")
    except Exception as e:
        print(f"Error stopping: {e}")
        await message.reply("❌ Failed to stop music!")

@call.on_stream_end()
async def stream_end_handler(chat_id: int):
    """Handle when stream ends"""
    await play_next(chat_id)

@call.on_kicked()
async def kicked_handler(chat_id: int):
    """Handle when bot is kicked from voice chat"""
    voice_chat_status[chat_id] = False
    queues.pop(chat_id, None)
    current_tracks.pop(chat_id, None)

async def main():
    """Main function to run the bot"""
    print("Starting Music Bot...")
    await call.start()
    await app.start()
    print("Bot is running!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())