import os
import re
import time
import threading
import requests
from flask import Flask
import telebot
from telebot import types
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TYER

# Render Port Check Dummy Server
app = Flask(__name__)

@app.route('/')
def home():
    return "Acoustic Vault Online!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
OWNER_ID = os.environ.get('OWNER_ID')

bot = telebot.TeleBot(BOT_TOKEN)

def is_authorized(chat_id):
    if OWNER_ID and str(chat_id) != str(OWNER_ID):
        return False
    return True

def clean_txt(text):
    if not text:
        return ""
    return re.sub(r'<.*?>', '', str(text)).replace('&quot;', '"').replace('&amp;', '&').replace('&copy;', '').strip()

# Jiosaavn Search Core
def saavn_search(query, search_type="song"):
    url = "https://www.jiosaavn.com/api.php"
    params = {
        "__call": "autocomplete.get",
        "_marker": "0",
        "query": query,
        "ctx": "web6dot0",
        "_format": "json"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=6).json()
        if search_type == "album":
            return res.get('albums', {}).get('data', [])
        return res.get('songs', {}).get('data', [])
    except Exception:
        return []

def get_album_details(album_id):
    url = "https://www.jiosaavn.com/api.php"
    params = {
        "__call": "content.getAlbumDetails",
        "_marker": "0",
        "albumid": album_id,
        "ctx": "web6dot0",
        "_format": "json"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        return requests.get(url, params=params, headers=headers, timeout=10).json()
    except Exception:
        return None

def get_song_details(song_id):
    url = "https://www.jiosaavn.com/api.php"
    params = {
        "__call": "song.getDetails",
        "pids": song_id,
        "_marker": "0",
        "ctx": "web6dot0",
        "_format": "json"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10).json()
        return res.get(song_id, {})
    except Exception:
        return None

def extract_direct_url(encrypted_url):
    url = "https://www.jiosaavn.com/api.php"
    params = {
        "__call": "song.generateAuthToken",
        "url": encrypted_url,
        "bitrate": "320",
        "api_version": "4",
        "_format": "json",
        "ctx": "web6dot0",
        "_marker": "0"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10).json()
        auth_url = res.get('auth_url', '')
        if auth_url:
            return auth_url.replace("&amp;", "&").split("?")[0]
    except Exception:
        pass
    return None

def deliver_track(chat_id, s_data):
    title = clean_txt(s_data.get('song') or s_data.get('title', 'Track'))
    artist = clean_txt(s_data.get('primary_artists') or s_data.get('music', 'Unknown'))
    album = clean_txt(s_data.get('album', 'Single'))
    year = str(s_data.get('year', ''))

    enc_url = s_data.get('encrypted_media_url')
    if not enc_url:
        return False

    direct_link = extract_direct_url(enc_url)
    if not direct_link:
        return False

    cover_url = s_data.get('image', '').replace("150x150", "500x500")
    filename = f"track_{chat_id}_{abs(hash(title)) % 100000}.mp3"

    try:
        r = requests.get(direct_link, stream=True, timeout=30)
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        if cover_url:
            try:
                img_data = requests.get(cover_url, timeout=10).content
                audio = ID3(filename)
                audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_data))
                audio.add(TIT2(encoding=3, text=title))
                audio.add(TPE1(encoding=3, text=artist))
                audio.add(TALB(encoding=3, text=album))
                if year:
                    audio.add(TYER(encoding=3, text=year))
                audio.save(filename)
            except Exception:
                pass

        caption = f"🎵 *{title}*\n💿 *Album:* {album}\n🎤 *Singers:* {artist}"
        with open(filename, 'rb') as audio_file:
            bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                title=title,
                performer=artist,
                caption=caption,
                parse_mode="Markdown"
            )

        if os.path.exists(filename):
            os.remove(filename)
        return True
    except Exception:
        if os.path.exists(filename):
            os.remove(filename)
        return False

# --- 1. START COMMAND ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    if not is_authorized(message.chat.id):
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_song = types.InlineKeyboardButton(text="Search song ↗️", switch_inline_query_current_chat="")
    btn_album = types.InlineKeyboardButton(text="Search album ↗️", switch_inline_query_current_chat="album ")
    markup.add(btn_song, btn_album)

    text = (
        "🎧 *Acoustic Vault Audiophile Studio*\n\n"
        "கீழே உள்ள பட்டன்களைத் தொட்டோ அல்லது நேரடியாகப் படத்தின் பெயரை இங்கே மெசேஜாக அனுப்பியோ தேடலாம்:\n"
        "*(எ.கா: Vaaranam Aayiram)*"
    )
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

# --- 2. INLINE SEARCH HANDLER ---
@bot.inline_handler(func=lambda query: True)
def inline_query(query):
    raw = query.query.strip()
    if not raw:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    is_album = raw.lower().startswith("album ")
    term = raw[6:].strip() if is_album else raw

    if not term:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    results = []
    if is_album:
        albums = saavn_search(term, "album")
        for alb in albums[:8]:
            alb_id = alb.get('id')
            name = clean_txt(alb.get('title'))
            desc = clean_txt(alb.get('description', 'Tamil Album'))
            year = alb.get('year', '')
            thumb = alb.get('image', '').replace("50x50", "150x150")

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(text="📥 Download Entire Album", callback_data=f"alb_{alb_id}"))

            msg_text = f"💿 *Album:* {name}\n👤 *Info:* {desc}\n📅 *Year:* {year}\n\n[⁠]({thumb})"
            results.append(
                types.InlineQueryResultArticle(
                    id=f"alb_{alb_id}",
                    title=f"💿 {name} ({year})",
                    description=desc,
                    thumb_url=thumb,
                    input_message_content=types.InputTextMessageContent(msg_text, parse_mode="Markdown"),
                    reply_markup=markup
                )
            )
    else:
        songs = saavn_search(term, "song")
        for sng in songs[:10]:
            s_id = sng.get('id')
            title = clean_txt(sng.get('title'))
            desc = clean_txt(sng.get('description', 'Single Track'))
            thumb = sng.get('image', '').replace("50x50", "150x150")

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(text="⬇️ Download 320kbps MP3", callback_data=f"sng_{s_id}"))

            msg_text = f"🎵 *{title}*\n📝 {desc}"
            results.append(
                types.InlineQueryResultArticle(
                    id=f"sng_{s_id}",
                    title=f"🎵 {title}",
                    description=desc,
                    thumb_url=thumb,
                    input_message_content=types.InputTextMessageContent(msg_text, parse_mode="Markdown"),
                    reply_markup=markup
                )
            )

    bot.answer_inline_query(query.id, results, cache_time=1)

# --- 3. CALLBACK HANDLERS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("alb_"))
def callback_album(call):
    alb_id = call.data.replace("alb_", "")
    bot.answer_callback_query(call.id, text="ஆல்பம் தகவல்கள் பெறப்படுகின்றன...")

    details = get_album_details(alb_id)
    songs = details.get('list', []) if details else []

    if not songs:
        bot.send_message(call.message.chat.id, "❌ பாடல்கள் கிடைக்கவில்லை.")
        return

    status = bot.send_message(call.message.chat.id, f"⬇️ *{len(songs)} பாடல்களும் பதிவிறக்கம் ஆகின்றன...*", parse_mode="Markdown")

    for s in songs:
        deliver_track(call.message.chat.id, s)

    bot.delete_message(call.message.chat.id, status.message_id)
    bot.send_message(call.message.chat.id, "✅ *முழு ஆல்பமும் வெற்றிகரமாக அனுப்பப்பட்டது!*", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("sng_"))
def callback_song(call):
    s_id = call.data.replace("sng_", "")
    bot.answer_callback_query(call.id, text="பாடல் பதிவிறக்கம் ஆகிறது...")

    s_data = get_song_details(s_id)
    if s_data:
        deliver_track(call.message.chat.id, s_data)
    else:
        bot.send_message(call.message.chat.id, "❌ பாடல் பதிவிறக்கம் தோல்வியடைந்தது.")

# --- 4. DIRECT CHAT SEARCH ---
@bot.message_handler(func=lambda msg: True)
def direct_text(message):
    if not is_authorized(message.chat.id):
        return

    text = message.text.strip()
    status = bot.reply_to(message, f"🔎 *'{text}'* தேடுகிறேன்...", parse_mode="Markdown")

    albums = saavn_search(text, "album")
    songs = saavn_search(text, "song")

    bot.delete_message(message.chat.id, status.message_id)

    if not albums and not songs:
        bot.reply_to(message, "❌ பாடல்களோ ஆல்பங்களோ கிடைக்கவில்லை.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    if albums:
        alb = albums[0]
        markup.add(types.InlineKeyboardButton(text=f"💿 Download Album: {clean_txt(alb.get('title'))}", callback_data=f"alb_{alb.get('id')}"))

    for s in songs[:6]:
        markup.add(types.InlineKeyboardButton(text=f"🎵 {clean_txt(s.get('title'))}", callback_data=f"sng_{s.get('id')}"))

    bot.send_message(message.chat.id, f"🎧 *'{text}' முடிவுகள்:*", reply_markup=markup, parse_mode="Markdown")

# --- 5. CRASH-PROOF SAFE POLLER ---
if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    
    # பழைய Session-களைத் துண்டித்து 3 நொடிகள் அமைதி காக்கும்
    try:
        bot.remove_webhook()
    except Exception:
        pass
    time.sleep(3)

    # Infinite Reconnect Loop (எந்த 409 எரர் வந்தாலும் பாட் நிற்காது)
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception:
            time.sleep(3)
