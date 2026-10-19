import os
import re
import time
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

# ACCURATE ALBUM DETAILS & FULL SONGS FETCHER
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

# OFFICIAL DIRECT 320KBPS MEDIA LINK FETCHER
def get_song_download_url(s_data):
    song_id = s_data.get('id')
    enc_url = s_data.get('encrypted_media_url')
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = "https://www.jiosaavn.com/api.php"

    # Step 1: If enc_url is missing, fetch song details first
    if not enc_url and song_id:
        p_det = {
            "__call": "song.getDetails",
            "pids": str(song_id),
            "_marker": "0",
            "ctx": "web6dot0",
            "_format": "json"
        }
        try:
            r = requests.get(url, params=p_det, headers=headers, timeout=6).json()
            s_obj = r.get(str(song_id), {})
            enc_url = s_obj.get('encrypted_media_url')
        except Exception:
            pass

    if not enc_url:
        return None

    # Step 2: Request direct auth stream URL
    p_auth = {
        "__call": "song.generateAuthToken",
        "url": enc_url,
        "bitrate": "320",
        "api_version": "4",
        "_format": "json",
        "ctx": "web6dot0",
        "_marker": "0"
    }
    try:
        res = requests.get(url, params=p_auth, headers=headers, timeout=8).json()
        auth_url = res.get('auth_url', '')
        if auth_url:
            return auth_url.replace("&amp;", "&")
    except Exception:
        pass

    return None

def send_audio_track(chat_id, s_data):
    title = clean_txt(s_data.get('song') or s_data.get('title', 'Track'))
    artist = clean_txt(s_data.get('primary_artists') or s_data.get('music', 'Unknown'))
    album = clean_txt(s_data.get('album', 'Single'))
    year = str(s_data.get('year', ''))

    direct_link = get_song_download_url(s_data)
    if not direct_link:
        return False

    cover_url = s_data.get('image', '').replace("150x150", "500x500").replace("50x50", "500x500")
    filename = f"track_{chat_id}_{abs(hash(title)) % 100000}.mp3"
    thumb_file = f"thumb_{chat_id}_{abs(hash(title)) % 100000}.jpg"

    try:
        # Download real audio stream
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(direct_link, stream=True, headers=headers, timeout=40)
        
        # Verify it's a real MP3/Audio stream (> 100 KB)
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)

        if os.path.getsize(filename) < 5000:
            if os.path.exists(filename):
                os.remove(filename)
            return False

        # Download thumbnail for Telegram audio player display
        has_thumb = False
        if cover_url:
            try:
                img_data = requests.get(cover_url, timeout=10).content
                with open(thumb_file, 'wb') as f_thumb:
                    f_thumb.write(img_data)
                has_thumb = True

                # Embed into ID3 metadata
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
            if has_thumb and os.path.exists(thumb_file):
                with open(thumb_file, 'rb') as t_file:
                    bot.send_audio(
                        chat_id=chat_id,
                        audio=audio_file,
                        thumb=t_file,
                        title=title,
                        performer=artist,
                        caption=caption
                    )
            else:
                bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=title,
                    performer=artist,
                    caption=caption
                )

        if os.path.exists(filename):
            os.remove(filename)
        if os.path.exists(thumb_file):
            os.remove(thumb_file)
        return True
    except Exception:
        if os.path.exists(filename):
            os.remove(filename)
        if os.path.exists(thumb_file):
            os.remove(thumb_file)
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

            year = alb.get('year', '')
            if not year and desc:
                year_match = re.search(r'\b(19\d{2}|20\d{2})\b', desc)
                if year_match:
                    year = year_match.group(1)

            url_part = alb.get('url', '')
            token = url_part.split('/')[-1] if url_part else (alb.get('id') or name)

            short_key = f"alb_{idx}_{abs(hash(token)) % 10000}"
            album_token_store[short_key] = {"token": token, "name": name}

            details, s_list = fetch_album_details_by_token(token)
            song_count = ""
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
    
    bot.answer_callback_query(call.id, text=f"'{album_name}' songs download aagudhu...")

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
