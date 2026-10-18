import os
import re
import threading
from flask import Flask
import telebot
from telebot import types
from yt_dlp import YoutubeDL

# Render web port check satisfy panna dummy web server
app = Flask(__name__)

@app.route('/')
def home():
    return "Acoustic Vault is Running Live!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
OWNER_ID = os.environ.get('OWNER_ID')

bot = telebot.TeleBot(BOT_TOKEN)
user_data = {}

def is_authorized(chat_id):
    if OWNER_ID and str(chat_id) != str(OWNER_ID):
        return False
    return True

@bot.message_handler(commands=['start'])
def start_msg(message):
    if not is_authorized(message.chat.id):
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_song = types.InlineKeyboardButton("🔍 Search Song", callback_data="set_song")
    btn_album = types.InlineKeyboardButton("💿 Search Album", callback_data="set_album")
    markup.add(btn_song, btn_album)

    welcome_text = (
        "🎵 **Acoustic Vault - Personal Music Assistant**\n\n"
        "• Paadalkal matrum muzhu album-galai high quality audio-va peralaam.\n"
        "• YouTube, YouTube Music links-aiyum direct-aa anuppalaam.\n\n"
        "Keezhe ulla options-la onna select pannunga:"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def set_search_mode(call):
    if not is_authorized(call.message.chat.id):
        return

    mode = "song" if call.data == "set_song" else "album"
    user_data[call.message.chat.id] = {"mode": mode, "page": 0}
    bot.answer_callback_query(call.id)
    
    if mode == "song":
        bot.send_message(call.message.chat.id, "🔍 **Search Song:** Paadal peyara type panni anupavum:")
    else:
        bot.send_message(call.message.chat.id, "💿 **Search Album:** Movie allathu Album peyara anupavum (Eg: Minnale, Roja):")

def send_album_view(chat_id, query, entries, page=0):
    start_idx = page * 5
    end_idx = start_idx + 5
    current_entries = entries[start_idx:end_idx]

    if not current_entries:
        bot.send_message(chat_id, "Paadalkal kidaikkavillai.")
        return

    thumb = current_entries[0].get('thumbnail')
    if not thumb:
        thumb = f"https://img.youtube.com/vi/{current_entries[0]['id']}/hqdefault.jpg"

    markup = types.InlineKeyboardMarkup(row_width=1)
    for song in current_entries:
        title = song.get('title', 'Play')
        if len(title) > 36:
            title = title[:33] + "..."
        markup.add(types.InlineKeyboardButton(f"🎵 {title}", callback_data=f"ask_{song['id']}"))

    nav_btns = []
    if page > 0:
        nav_btns.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{page - 1}"))
    if end_idx < len(entries):
        nav_btns.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"page_{page + 1}"))
    if nav_btns:
        markup.row(*nav_btns)

    caption = f"💿 **Album:** {query.title()}\n\nKeezhe ulla paadalgalil thevaiyanathai click panni download seiyavum:"
    bot.send_photo(chat_id, photo=thumb, caption=caption, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("page_"))
def handle_pagination(call):
    if not is_authorized(call.message.chat.id):
        return
    page = int(call.data.replace("page_", ""))
    state = user_data.get(call.message.chat.id, {})
    entries = state.get("entries", [])
    query = state.get("query", "Music")
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    send_album_view(call.message.chat.id, query, entries, page)

@bot.callback_query_handler(func=lambda call: call.data.startswith("ask_"))
def ask_format(call):
    if not is_authorized(call.message.chat.id):
        return
    video_id = call.data.replace("ask_", "")
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_mp3 = types.InlineKeyboardButton("⚡ MP3 320kbps", callback_data=f"dl_mp3_{video_id}")
    btn_flac = types.InlineKeyboardButton("🎧 FLAC Lossless", callback_data=f"dl_flac_{video_id}")
    markup.add(btn_mp3, btn_flac)
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Audio Quality-ah select pannunga:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_"))
def handle_download(call):
    if not is_authorized(call.message.chat.id):
        return

    parts = call.data.split("_")
    fmt = parts[1]
    video_id = parts[2]
    url = f"https://www.youtube.com/watch?v={video_id}"

    bot.answer_callback_query(call.id, text="Download thodangugirathu...")
    status = bot.send_message(call.message.chat.id, f"⬇️ {fmt.upper()} quality-la audio ready aagudhu...")

    filename = f"audio_{video_id}"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{filename}.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3' if fmt == 'mp3' else 'flac',
            'preferredquality': '320' if fmt == 'mp3' else None,
        }],
        'quiet': True,
        'noplaylist': True
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Track')

        ext = "mp3" if fmt == "mp3" else "flac"
        final_file = f"{filename}.{ext}"

        bot.edit_message_text(f"⬆️ '{title}' upload seigiren...", chat_id=call.message.chat.id, message_id=status.message_id)

        with open(final_file, 'rb') as audio:
            bot.send_audio(call.message.chat.id, audio, title=title)

        bot.delete_message(call.message.chat.id, status.message_id)
        if os.path.exists(final_file):
            os.remove(final_file)
    except Exception:
        bot.edit_message_text("Mannikkavum! Audio download seiyum podhu error vandhuruchu.", chat_id=call.message.chat.id, message_id=status.message_id)

@bot.message_handler(func=lambda message: True)
def process_text(message):
    if not is_authorized(message.chat.id):
        return

    text = message.text.strip()
    
    if "youtube.com" in text or "youtu.be" in text:
        video_id_match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11})', text)
        if video_id_match:
            video_id = video_id_match.group(1)
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("⚡ MP3 320kbps", callback_data=f"dl_mp3_{video_id}"),
                types.InlineKeyboardButton("🎧 FLAC Lossless", callback_data=f"dl_flac_{video_id}")
            )
            bot.reply_to(message, "Link kedachiruchu! Quality select pannunga:", reply_markup=markup)
            return

    state = user_data.get(message.chat.id, {"mode": "song"})
    mode = state.get("mode", "song")
    status = bot.reply_to(message, f"🔎 '{text}'-ai thedugiren...")

    search_query = f"ytsearch15:{text} full songs jukebox" if mode == "album" else f"ytsearch8:{text} audio"
    ydl_opts = {'quiet': True, 'extract_flat': 'in_playlist', 'skip_download': True}

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            entries = info.get('entries', [])

        bot.delete_message(message.chat.id, status.message_id)
        if not entries:
            bot.reply_to(message, "Paadalkal kidaikkavillai. Vera peyaril try pannunga.")
            return

        user_data[message.chat.id] = {"mode": mode, "entries": entries, "query": text}

        if mode == "album":
            send_album_view(message.chat.id, text, entries, page=0)
        else:
            markup = types.InlineKeyboardMarkup(row_width=1)
            for song in entries[:6]:
                title = song.get('title', 'Play')
                if len(title) > 36:
                    title = title[:33] + "..."
                markup.add(types.InlineKeyboardButton(f"▶️ {title}", callback_data=f"ask_{song['id']}"))
            bot.send_message(message.chat.id, f"🔍 **'{text}' Paadalkal List:**", reply_markup=markup, parse_mode="Markdown")

    except Exception:
        bot.edit_message_text("Thedalil pizhai erpatatadhu. Meendum try pannunga.", chat_id=message.chat.id, message_id=status.message_id)

if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling()
