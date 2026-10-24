import os
import re
import time
import base64
import threading
import requests
from flask import Flask
import telebot
from telebot import types
from mutagen.mp4 import MP4, MP4Cover
from Crypto.Cipher import DES

# --- 1. WEB SERVER & RENDER KEEP-ALIVE ---
app = Flask(__name__)

RENDER_APP_URL = "https://my-music-bot-lnw7.onrender.com"

@app.route('/')
def home():
    return "Acoustic Vault Online & Active 24/7!", 200

@app.route('/healthz')
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive_ping():
    """Render Free Tier 15-minute sleep-ah thadukkum background auto-ping."""
    time.sleep(30)
    while True:
        try:
            requests.get(f"{RENDER_APP_URL}/healthz", timeout=10)
        except Exception:
            pass
        time.sleep(600)  # Every 10 minutes once ping pannum

# --- 2. BOT INITIALIZATION ---
BOT_TOKEN = os.environ.get('BOT_TOKEN')
# num_threads=4: Parallel inline search and downloads freeze aagama run aaga
bot = telebot.TeleBot(BOT_TOKEN, num_threads=4)

album_token_store = {}
user_quality_pref = {}

def clean_txt(text):
    if not text:
        return ""
    return re.sub(r'<.*?>', '', str(text)).replace('&quot;', '"').replace('&amp;', '&').replace('&copy;', '').strip()

# --- 3. JIOSAAVN AUTOCOMPLETE & DETAILS ---
def saavn_search(query, search_type="album"):
    url = "https://www.jiosaavn.com/api.php"
    params = {
        "__call": "autocomplete.get",
        "_marker": "0",
        "query": query,
        "ctx": "web6dot0",
        "_format": "json"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=5).json()
        if search_type == "album":
            return res.get('albums', {}).get('data', [])
        return res.get('songs', {}).get('data', [])
    except Exception:
        return []

def fetch_album_details_by_token(token_or_id):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = "https://www.jiosaavn.com/api.php"

    params_token = {
        "__call": "webapi.get",
        "token": str(token_or_id),
        "type": "album",
        "includeMetaTags": "0",
        "ctx": "web6dot0",
        "_format": "json",
        "_marker": "0"
    }
    try:
        r = requests.get(url, params=params_token, headers=headers, timeout=8).json()
        songs = r.get('list', []) or r.get('songs', [])
        if songs:
            return r, songs
    except Exception:
        pass

    params_id = {
        "__call": "content.getAlbumDetails",
        "_marker": "0",
        "albumid": str(token_or_id),
        "ctx": "web6dot0",
        "_format": "json"
    }
    try:
        r2 = requests.get(url, params=params_id, headers=headers, timeout=8).json()
        songs2 = r2.get('list', []) or r2.get('songs', [])
        if songs2:
            return r2, songs2
    except Exception:
        pass

    return None, []

# --- 4. MEDIA URL DECRYPTION ---
def decrypt_media_url(enc_url, bitrate="320"):
    try:
        key = b"38346591"
        enc_data = base64.b64decode(enc_url.strip())
        cipher = DES.new(key, DES.MODE_ECB)
        dec_data = cipher.decrypt(enc_data)
        pad = dec_data[-1]
        dec_url = dec_data[:-pad].decode('utf-8')
        
        target_br = f"_{bitrate}.mp4" if bitrate in ["320", "160", "96"] else "_320.mp4"
        dec_url = dec_url.replace("_96.mp4", target_br)
        return dec_url
    except Exception:
        pass
    return None

# --- 5. AUDIO PROCESSOR & TRANSMITTER ---
def send_audio_track(chat_id, s_data):
    title = clean_txt(s_data.get('song') or s_data.get('title', 'Track'))
    artist = clean_txt(s_data.get('primary_artists') or s_data.get('music', 'Unknown Artist'))
    album = clean_txt(s_data.get('album', 'Single'))
    year = str(s_data.get('year', ''))
    
    # Exact duration extraction for Telegram Player
    raw_duration = s_data.get('duration') or 0
    try:
        duration = int(raw_duration)
    except Exception:
        duration = 0

    enc_url = s_data.get('encrypted_media_url')
    if not enc_url and s_data.get('id'):
        url = "https://www.jiosaavn.com/api.php"
        params = {
            "__call": "song.getDetails",
            "pids": str(s_data.get('id')),
            "_marker": "0",
            "ctx": "web6dot0",
            "_format": "json"
        }
        try:
            r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=6).json()
            s_obj = r.get(str(s_data.get('id')), {})
            enc_url = s_obj.get('encrypted_media_url')
            if s_obj.get('song'):
                title = clean_txt(s_obj.get('song'))
            if s_obj.get('primary_artists'):
                artist = clean_txt(s_obj.get('primary_artists'))
            if s_obj.get('duration'):
                try:
                    duration = int(s_obj.get('duration'))
                except Exception:
                    pass
        except Exception:
            pass

    if not enc_url:
        return False

    user_br = user_quality_pref.get(chat_id, "320")
    direct_link = decrypt_media_url(enc_url, bitrate=user_br)
    if not direct_link:
        return False

    cover_url = s_data.get('image', '').replace("150x150", "500x500").replace("50x50", "500x500")
    
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
    # Unique file identifiers to stop overwrite collisions
    req_uid = f"{chat_id}_{int(time.time() * 1000)}"
    filename = f"{safe_title}_{req_uid}.m4a"
    thumb_file = f"thumb_{req_uid}.jpg"

    try:
        r = requests.get(direct_link, stream=True, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=32768):
                if chunk:
                    f.write(chunk)

        if not os.path.exists(filename) or os.path.getsize(filename) < 200000:
            return False

        has_thumb = False
        img_data = None
        if cover_url:
            try:
                img_data = requests.get(cover_url, timeout=10).content
                with open(thumb_file, 'wb') as f_thumb:
                    f_thumb.write(img_data)
                has_thumb = True
            except Exception:
                pass

        # Native MP4/M4A ID3 Tags
        try:
            audio = MP4(filename)
            audio['\xa9nam'] = [title]
            audio['\xa9ART'] = [artist]
            audio['\xa9alb'] = [album]
            if year:
                audio['\xa9day'] = [year]
            if img_data:
                audio['covr'] = [MP4Cover(img_data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
        except Exception:
            pass

        caption = f"Title: {title}\nAlbum: {album}\nSingers: {artist}"

        with open(filename, 'rb') as audio_file:
            t_file = open(thumb_file, 'rb') if (has_thumb and os.path.exists(thumb_file)) else None
            try:
                bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    thumb=t_file,
                    title=title,
                    performer=artist,
                    duration=duration if duration > 0 else None,
                    caption=caption
                )
            finally:
                if t_file:
                    t_file.close()
        return True
    except Exception:
        return False
    finally:
        # Guaranteed cleanup: stops disk space leaks on Render
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass
        if os.path.exists(thumb_file):
            try:
                os.remove(thumb_file)
            except Exception:
                pass

def process_album_download(songs, chat_id):
    for s in songs:
        send_audio_track(chat_id, s)
        time.sleep(1)

# --- 6. /START COMMAND & QUALITY PREFERENCES ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = message.chat.id
    current_q = user_quality_pref.get(chat_id, "320")
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_sng = types.InlineKeyboardButton("Search song ↗️", switch_inline_query_current_chat="song: ")
    btn_alb = types.InlineKeyboardButton("Search album ↗️", switch_inline_query_current_chat="album: ")
    btn_quality = types.InlineKeyboardButton(f"⚙️ Audio Quality: {current_q}kbps", callback_data="open_quality_menu")
    markup.add(btn_sng, btn_alb)
    markup.add(btn_quality)

    bot.send_message(message.chat.id, "🔎 Search Song in Inline Mode", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "open_quality_menu")
def quality_menu(call):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("⚡ 320kbps Extreme (Default / Best)", callback_data="set_q_320"),
        types.InlineKeyboardButton("🎧 160kbps High Quality (Balanced)", callback_data="set_q_160"),
        types.InlineKeyboardButton("💾 96kbps Medium (Data Saver)", callback_data="set_q_96")
    )
    bot.edit_message_text(
        "🎚 **விருப்பமான ஆடியோ தரத்தைத் தேர்வு செய்யவும்:**",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_q_"))
def apply_quality(call):
    q_val = call.data.replace("set_q_", "")
    user_quality_pref[call.message.chat.id] = q_val
    bot.answer_callback_query(call.id, text=f"Audio quality {q_val}kbps-ஆக அமைக்கப்பட்டது!")
    start_cmd(call.message)

# --- 7. LIGHTNING FAST INLINE QUERY HANDLER ---
@bot.inline_handler(func=lambda query: True)
def handle_inline(query):
    raw = query.query.strip()
    if not raw:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    is_album = raw.lower().startswith("album:") or raw.lower().startswith("album ")
    if is_album:
        term = raw.split(":", 1)[-1].strip() if ":" in raw else raw[6:].strip()
    elif raw.lower().startswith("song:"):
        term = raw.split(":", 1)[-1].strip()
    else:
        term = raw

    if not term:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    # Memory Leak Protection: Auto-trim cache if exceeds 150 entries
    if len(album_token_store) > 150:
        for _ in range(50):
            album_token_store.pop(next(iter(album_token_store)), None)

    results = []
    if is_album:
        albums = saavn_search(term, "album")
        for idx, alb in enumerate(albums[:8]):
            name = clean_txt(alb.get('title'))
            desc = clean_txt(alb.get('description', 'Tamil Album'))
            thumb = alb.get('image', '').replace("50x50", "500x500")

            year = alb.get('year', '')
            if not year and desc:
                year_match = re.search(r'\b(19\d{2}|20\d{2})\b', desc)
                if year_match:
                    year = year_match.group(1)

            url_part = alb.get('url', '')
            token = url_part.split('/')[-1] if url_part else (alb.get('id') or name)

            short_key = f"alb_{idx}_{abs(hash(token)) % 10000}"
            album_token_store[short_key] = {"token": token, "name": name, "year": year}

            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_dl = types.InlineKeyboardButton("📥 Download Album ↗️", callback_data=short_key)
            btn_again = types.InlineKeyboardButton("🔍 Search again ↗️", switch_inline_query_current_chat="album: ")
            markup.add(btn_dl, btn_again)

            year_str = f"Year: {year}" if year else "Year: 2008"

            msg = (
                f"Album: {name}\n"
                f"Description: {desc}\n"
                f"Language: Tamil\n"
                f"Total songs: Click Download to Fetch\n"
                f"{year_str}"
            )

            results.append(
                types.InlineQueryResultArticle(
                    id=short_key,
                    title=name,
                    description=f"{year} · {desc}" if year else desc,
                    thumbnail_url=thumb if thumb else None,
                    input_message_content=types.InputTextMessageContent(msg),
                    reply_markup=markup
                )
            )
    else:
        songs = saavn_search(term, "song")
        for idx, sng in enumerate(songs[:10]):
            s_id = str(sng.get('id'))
            title = clean_txt(sng.get('title'))
            desc = clean_txt(sng.get('description', 'Single Track'))
            thumb = sng.get('image', '').replace("50x50", "500x500")

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬇️ Download Audio", callback_data=f"sng_{s_id}"))

            msg_content = f"Title: {title}\nSingers: {desc}"

            results.append(
                types.InlineQueryResultArticle(
                    id=f"sng_{s_id}",
                    title=title,
                    description=desc,
                    thumbnail_url=thumb if thumb else None,
                    input_message_content=types.InputTextMessageContent(msg_content),
                    reply_markup=markup
                )
            )

    bot.answer_inline_query(query.id, results, cache_time=1)

# --- 8. ALBUM & SONG CALLBACK RECEIVERS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("alb_"))
def callback_album(call):
    stored = album_token_store.get(call.data, {})
    token = stored.get("token")
    album_name = stored.get("name", "Album")
    target_chat_id = call.message.chat.id if call.message else call.from_user.id
    
    bot.answer_callback_query(call.id, text=f"'{album_name}' பாடல்கள் தயாராகின்றன...")

    _, songs = fetch_album_details_by_token(token or album_name)
    if not songs:
        try:
            bot.send_message(target_chat_id, "❌ பாடல்கள் கிடைக்கவில்லை.")
        except Exception:
            pass
        return

    try:
        bot.send_message(target_chat_id, f"⬇️ *{album_name}* ஆல்பத்திலிருந்து {len(songs)} பாடல்கள் பதிவிறக்கம் செய்யப்படுகின்றன...", parse_mode="Markdown")
        threading.Thread(target=process_album_download, args=(songs, target_chat_id), daemon=True).start()
    except Exception:
        pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("sng_"))
def callback_song(call):
    s_id = call.data.replace("sng_", "")
    target_chat_id = call.message.chat.id if call.message else call.from_user.id
    bot.answer_callback_query(call.id, text="பாடல் பதிவிறக்கம் ஆகிறது...")

    url = "https://www.jiosaavn.com/api.php"
    params = {
        "__call": "song.getDetails",
        "pids": str(s_id),
        "_marker": "0",
        "ctx": "web6dot0",
        "_format": "json"
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10).json()
        s_data = res.get(str(s_id), {}) or (res.get('songs', [{}])[0] if res.get('songs') else {})
        if s_data and (s_data.get('encrypted_media_url') or s_data.get('id')):
            threading.Thread(target=send_audio_track, args=(target_chat_id, s_data), daemon=True).start()
        else:
            bot.send_message(target_chat_id, "❌ பாடல் கிடைக்கவில்லை.")
    except Exception:
        try:
            bot.send_message(target_chat_id, "❌ பிழை ஏற்பட்டது.")
        except Exception:
            pass

# --- 9. FALLBACK COMMAND ---
@bot.message_handler(func=lambda msg: True)
def direct_text_search(message):
    start_cmd(message)

# --- 10. CRASH-PROOF THREADS & POLLING ---
if __name__ == '__main__':
    # Web server thread (Daemon)
    threading.Thread(target=run_web, daemon=True).start()
    
    # Render Keep-Alive Auto Ping thread (Daemon)
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    
    try:
        bot.remove_webhook()
    except Exception:
        pass
    time.sleep(2)

    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception:
            time.sleep(3)
