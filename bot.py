import os
import re
import threading
import requests
from flask import Flask
import telebot
from telebot import types
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TYER

app = Flask(__name__)

@app.route('/')
def home():
    return "Acoustic Vault Online!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

def clean_txt(text):
    if not text:
        return ""
    return re.sub(r'<.*?>', '', str(text)).replace('&quot;', '"').replace('&amp;', '&').replace('&copy;', '').strip()

# JIOSAAVN AUTOCOMPLETE SEARCH
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
        res = requests.get(url, params=params, headers=headers, timeout=6).json()
        if search_type == "album":
            return res.get('albums', {}).get('data', [])
        return res.get('songs', {}).get('data', [])
    except Exception:
        return []

# BULLETPROOF ALBUM DETAILS FETCHER (Dual Method)
def get_album_details(album_id):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    # Method 1: Direct albumid
    url1 = "https://www.jiosaavn.com/api.php"
    params1 = {
        "__call": "content.getAlbumDetails",
        "_marker": "0",
        "albumid": str(album_id),
        "ctx": "web6dot0",
        "_format": "json"
    }
    try:
        r1 = requests.get(url1, params=params1, headers=headers, timeout=8).json()
        if r1 and r1.get('list'):
            return r1
    except Exception:
        pass

    # Method 2: Token / URL search fallback
    params2 = {
        "__call": "webapi.get",
        "token": str(album_id),
        "type": "album",
        "includeMetaTags": "0",
        "ctx": "web6dot0",
        "_format": "json",
        "_marker": "0"
    }
    try:
        r2 = requests.get(url1, params=params2, headers=headers, timeout=8).json()
        if r2 and r2.get('list'):
            return r2
    except Exception:
        pass

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

def send_audio_track(chat_id, s_data):
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
            for chunk in r.iter_content(chunk_size=16384):
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

        caption = f"Title: {title}\nAlbum: {album}\nSingers: {artist}"

        with open(filename, 'rb') as audio_file:
            bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                title=title,
                performer=artist,
                caption=caption
            )

        if os.path.exists(filename):
            os.remove(filename)
        return True
    except Exception:
        if os.path.exists(filename):
            os.remove(filename)
        return False

# --- 1. /START COMMAND ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_sng = types.InlineKeyboardButton("Search song ↗️", switch_inline_query_current_chat="song: ")
    btn_alb = types.InlineKeyboardButton("Search album ↗️", switch_inline_query_current_chat="album: ")
    markup.add(btn_sng, btn_alb)

    bot.send_message(message.chat.id, "🔎 Search Song in Inline Mode", reply_markup=markup)

# --- 2. EXACT INLINE CARDS ---
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

    results = []
    if is_album:
        albums = saavn_search(term, "album")
        for alb in albums[:10]:
            # id அல்லது url-ல் உள்ள token-ஐப் பயன்படுத்தும் முறை
            alb_id = alb.get('id') or alb.get('url', '').split('/')[-1]
            name = clean_txt(alb.get('title'))
            desc = clean_txt(alb.get('description', 'Tamil Album'))
            year = alb.get('year', '')
            thumb = alb.get('image', '').replace("50x50", "150x150")

            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_dl = types.InlineKeyboardButton("📥 Download Album ↗️", callback_data=f"alb_{alb_id}")
            btn_again = types.InlineKeyboardButton("🔍 Search again ↗️", switch_inline_query_current_chat="album: ")
            markup.add(btn_dl, btn_again)

            msg = (
                f"Album: {name}\n"
                f"Description: {desc}\n"
                f"Language: Tamil\n"
                f"Year: {year}"
            )

            results.append(
                types.InlineQueryResultArticle(
                    id=f"alb_{alb_id}",
                    title=name,
                    description=f"{year} · {desc}",
                    thumbnail_url=thumb if thumb else None,
                    input_message_content=types.InputTextMessageContent(msg),
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
            markup.add(types.InlineKeyboardButton("⬇️ Download 320kbps MP3", callback_data=f"sng_{s_id}"))

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

# --- 3. ALBUM FULL DOWNLOAD ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("alb_"))
def callback_album(call):
    alb_id = call.data.replace("alb_", "")
    target_chat_id = call.message.chat.id if call.message else call.from_user.id
    
    bot.answer_callback_query(call.id, text="Album loading...")

    details = get_album_details(alb_id)
    songs = details.get('list', []) if details else []

    if not songs:
        bot.send_message(target_chat_id, "❌ Paadalgal kidaikkavillai.")
        return

    album_title = clean_txt(details.get('title', 'Album'))
    cover_img = details.get('image', '').replace("150x150", "500x500")

    if cover_img:
        try:
            bot.send_photo(target_chat_id, cover_img, caption=f"🗂 {album_title}")
        except Exception:
            pass

    for s in songs:
        send_audio_track(target_chat_id, s)

# --- 4. SINGLE SONG DOWNLOAD ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("sng_"))
def callback_song(call):
    s_id = call.data.replace("sng_", "")
    target_chat_id = call.message.chat.id if call.message else call.from_user.id
    bot.answer_callback_query(call.id, text="Downloading song...")

    url = "https://www.jiosaavn.com/api.php"
    params = {
        "__call": "song.getDetails",
        "pids": s_id,
        "_marker": "0",
        "ctx": "web6dot0",
        "_format": "json"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10).json()
        s_data = res.get(s_id, {})
        if s_data:
            send_audio_track(target_chat_id, s_data)
        else:
            bot.send_message(target_chat_id, "❌ Paadal kidaikkavillai.")
    except Exception:
        bot.send_message(target_chat_id, "❌ Pizhai erpatatadhu.")

# --- 5. DIRECT TEXT FALLBACK ---
@bot.message_handler(func=lambda msg: True)
def direct_text_search(message):
    start_cmd(message)

if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    try:
        bot.remove_webhook()
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
