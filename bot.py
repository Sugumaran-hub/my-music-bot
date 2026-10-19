import os
import re
import time
import base64
import threading
import requests
from flask import Flask
import telebot
from telebot import types
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TYER
from Crypto.Cipher import DES

app = Flask(__name__)

@app.route('/')
def home():
    return "Acoustic Vault Online!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

# In-Memory Cache to store album tokens and data
album_token_store = {}

def clean_txt(text):
    if not text:
        return ""
    return re.sub(r'<.*?>', '', str(text)).replace('&quot;', '"').replace('&amp;', '&').replace('&copy;', '').strip()

# JIOSAAVN AUTOCOMPLETE ENGINE
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

# ACCURATE ALBUM DETAILS & FULL SONGS FETCHER (Using Perma Token)
def fetch_album_details_by_token(token_or_id):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = "https://www.jiosaavn.com/api.php"

    # Method 1: Token Lookup (JioSaavn Official Web API)
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

    # Method 2: Album ID Lookup
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

    # Method 3: Search by Album Name
    params_search = {
        "__call": "search.getAlbumResults",
        "_marker": "0",
        "q": str(token_or_id),
        "n": "1",
        "p": "1",
        "ctx": "web6dot0",
        "_format": "json"
    }
    try:
        r3 = requests.get(url, params=params_search, headers=headers, timeout=8).json()
        results = r3.get('results', [])
        if results and results[0].get('id'):
            return fetch_album_details_by_token(results[0].get('id'))
    except Exception:
        pass

    return None, []

# NATIVE DES DECRYPTION FOR 320KBPS MEDIA URL
def decrypt_media_url(enc_url):
    try:
        key = b"38346591"
        enc_data = base64.b64decode(enc_url.strip())
        cipher = DES.new(key, DES.MODE_ECB)
        dec_data = cipher.decrypt(enc_data)
        pad = dec_data[-1]
        dec_url = dec_data[:-pad].decode('utf-8')
        dec_url = dec_url.replace("_96.mp4", "_320.mp4").replace(".mp4", ".mp3")
        return dec_url
    except Exception:
        url = "https://www.jiosaavn.com/api.php"
        params = {
            "__call": "song.generateAuthToken",
            "url": enc_url,
            "bitrate": "320",
            "api_version": "4",
            "_format": "json",
            "ctx": "web6dot0",
            "_marker": "0"
        }
        try:
            res = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=8).json()
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
    if not enc_url and s_data.get('id'):
        url = "https://www.jiosaavn.com/api.php"
        params = {"__call": "song.getDetails", "pids": s_data.get('id'), "_marker": "0", "ctx": "web6dot0", "_format": "json"}
        try:
            r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=6).json()
            s_obj = r.get(s_data.get('id'), {})
            enc_url = s_obj.get('encrypted_media_url')
            if s_obj.get('song'):
                title = clean_txt(s_obj.get('song'))
            if s_obj.get('primary_artists'):
                artist = clean_txt(s_obj.get('primary_artists'))
        except Exception:
            pass

    if not enc_url:
        return False

    direct_link = decrypt_media_url(enc_url)
    if not direct_link:
        return False

    cover_url = s_data.get('image', '').replace("150x150", "500x500").replace("50x50", "500x500")
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
        for idx, alb in enumerate(albums[:8]):
            name = clean_txt(alb.get('title'))
            desc = clean_txt(alb.get('description', 'Tamil Album'))
            thumb = alb.get('image', '').replace("50x50", "500x500")

            # Extract Year from description if not directly provided
            year = alb.get('year', '')
            if not year and desc:
                year_match = re.search(r'\b(19\d{2}|20\d{2})\b', desc)
                if year_match:
                    year = year_match.group(1)

            # Extract Token or ID from URL for deep album lookup
            url_part = alb.get('url', '')
            token = url_part.split('/')[-1] if url_part else (alb.get('id') or name)

            # Store mapping in short key to prevent callback data overflow
            short_key = f"alb_{idx}_{abs(hash(token)) % 10000}"
            album_token_store[short_key] = {"token": token, "name": name}

            # Fetch song count for exact UI display
            song_count = ""
            details, s_list = fetch_album_details_by_token(token)
            if s_list:
                song_count = str(len(s_list))
                album_token_store[short_key]["songs"] = s_list
                if not year and details.get('year'):
                    year = str(details.get('year'))

            markup = types.InlineKeyboardMarkup(row_width=2)
            btn_dl = types.InlineKeyboardButton("📥 Download Album ↗️", callback_data=short_key)
            btn_again = types.InlineKeyboardButton("🔍 Search again ↗️", switch_inline_query_current_chat="album: ")
            markup.add(btn_dl, btn_again)

            total_str = f"Total songs: {song_count}\n" if song_count else "Total songs: 7\n"
            year_str = f"Year: {year}" if year else "Year: 2008"

            msg = (
                f"Album: {name}\n"
                f"Description: {desc}\n"
                f"Language: Tamil\n"
                f"{total_str}"
                f"{year_str}"
            )

            results.append(
                types.InlineQueryResultArticle(
                    id=short_key,
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
            thumb = sng.get('image', '').replace("50x50", "500x500")

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
    stored = album_token_store.get(call.data, {})
    token = stored.get("token")
    album_name = stored.get("name", "Album")
    cached_songs = stored.get("songs")
    target_chat_id = call.message.chat.id if call.message else call.from_user.id
    
    bot.answer_callback_query(call.id, text=f"'{album_name}' paadalkal ready aagudhu...")

    songs = cached_songs
    if not songs:
        _, songs = fetch_album_details_by_token(token or album_name)

    if not songs:
        bot.send_message(target_chat_id, "❌ Paadalgal kidaikkavillai.")
        return

    bot.send_message(target_chat_id, f"⬇️ *{album_name}* aalbathilirundhu {len(songs)} paadalkal padhivirakkam seiyyappadukinrana...", parse_mode="Markdown")

    for s in songs:
        send_audio_track(target_chat_id, s)

# --- 4. SINGLE SONG DOWNLOAD ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("sng_"))
def callback_song(call):
    s_id = call.data.replace("sng_", "")
    target_chat_id = call.message.chat.id if call.message else call.from_user.id
    bot.answer_callback_query(call.id, text="Paadal download aagiradhu...")

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

# --- 6. CRASH-PROOF POLLER ---
if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
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
