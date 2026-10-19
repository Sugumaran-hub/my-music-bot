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

API_BASES = [
    "https://saavn.dev/api",
    "https://saavn.me",
    "https://jiosaavn-api-privatecvc2.vercel.app"
]

def req_api(path):
    for base in API_BASES:
        try:
            r = requests.get(f"{base}{path}", timeout=6)
            if r.status_code == 200:
                js = r.json()
                if isinstance(js, dict):
                    if js.get('data'):
                        return js.get('data')
                    if js.get('results'):
                        return js.get('results')
                return js
        except Exception:
            continue
    return None

def send_audio_track(chat_id, song):
    title = clean_txt(song.get('name') or song.get('title', 'Track'))
    artist = clean_txt(song.get('primaryArtists') or song.get('singers', 'Unknown'))
    album_obj = song.get('album')
    album = clean_txt(album_obj.get('name')) if isinstance(album_obj, dict) else clean_txt(str(album_obj or 'Single'))
    year = str(song.get('year', ''))

    dl_urls = song.get('downloadUrl', [])
    target_url = None
    if isinstance(dl_urls, list) and dl_urls:
        target_url = dl_urls[-1].get('link') or dl_urls[-1].get('url')
    elif song.get('media_url'):
        target_url = song.get('media_url')

    if not target_url:
        return False

    imgs = song.get('image', [])
    cover_url = None
    if isinstance(imgs, list) and imgs:
        cover_url = imgs[-1].get('link') or imgs[-1].get('url')
    elif isinstance(imgs, str):
        cover_url = imgs

    filename = f"track_{chat_id}_{abs(hash(title)) % 10000}.mp3"
    try:
        res = requests.get(target_url, stream=True, timeout=25)
        with open(filename, 'wb') as f:
            for chunk in res.iter_content(chunk_size=16384):
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

        caption = (
            f"Title: {title}\n"
            f"Album: {album}\n"
            f"Singers: {artist}"
        )

        with open(filename, 'rb') as f_audio:
            bot.send_audio(
                chat_id=chat_id,
                audio=f_audio,
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
    btn_sng = types.InlineKeyboardButton("Search song ↗️", switch_inline_query_current_chat="")
    btn_alb = types.InlineKeyboardButton("Search album ↗️", switch_inline_query_current_chat="Album: ")
    markup.add(btn_sng, btn_alb)

    bot.send_message(message.chat.id, "🔎 Search Song in Inline Mode", reply_markup=markup)

# --- 2. INLINE SEARCH (EXACT CARDS) ---
@bot.inline_handler(func=lambda query: True)
def handle_inline(query):
    raw = query.query.strip()
    if not raw:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    is_album = raw.lower().startswith("album:") or raw.lower().startswith("album ")
    if is_album:
        term = raw.split(":", 1)[-1].strip() if ":" in raw else raw[6:].strip()
    else:
        term = raw

    if not term:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    results = []
    if is_album:
        data = req_api(f"/search/albums?query={requests.utils.quote(term)}")
        items = data.get('results', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for alb in items[:10]:
            alb_id = alb.get('id')
            name = clean_txt(alb.get('name') or alb.get('title'))
            artist = clean_txt(alb.get('primaryArtists') or alb.get('artist', 'Various Artists'))
            year = alb.get('year', '')
            song_count = alb.get('songCount') or alb.get('song_count', '')
            imgs = alb.get('image', [])
            thumb = imgs[-1].get('link') if isinstance(imgs, list) and imgs else (imgs if isinstance(imgs, str) else "")

            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📥 Download Album ↗️", callback_data=f"alb_{alb_id}"),
                types.InlineKeyboardButton("🔍 Search again ↗️", switch_inline_query_current_chat="Album: ")
            )

            count_str = f"Total songs: {song_count}\n" if song_count else ""
            msg = (
                f"Album: {name}\n"
                f"Description: Tamil Film · {artist}\n"
                f"Language: Tamil\n"
                f"{count_str}"
                f"Year: {year}\n\n"
                f"[⁠]({thumb})"
            )

            desc_text = f"{year} · Tamil Film · {artist}"
            if song_count:
                desc_text += f"\nTotal songs: {song_count}"

            results.append(
                types.InlineQueryResultArticle(
                    id=f"alb_{alb_id}",
                    title=name,
                    description=desc_text,
                    thumbnail_url=thumb,
                    input_message_content=types.InputTextMessageContent(msg, parse_mode="Markdown"),
                    reply_markup=markup
                )
            )
    else:
        data = req_api(f"/search/songs?query={requests.utils.quote(term)}")
        items = data.get('results', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for sng in items[:10]:
            s_id = sng.get('id')
            title = clean_txt(sng.get('name') or sng.get('title'))
            album_obj = sng.get('album')
            album = clean_txt(album_obj.get('name')) if isinstance(album_obj, dict) else clean_txt(str(album_obj or 'Single'))
            artist = clean_txt(sng.get('primaryArtists') or sng.get('singers', 'Unknown'))
            imgs = sng.get('image', [])
            thumb = imgs[-1].get('link') if isinstance(imgs, list) and imgs else (imgs if isinstance(imgs, str) else "")

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬇️ Download 320kbps Master", callback_data=f"sng_{s_id}"))

            msg_content = f"Title: {title}\nAlbum: {album}\nSingers: {artist}"

            results.append(
                types.InlineQueryResultArticle(
                    id=f"sng_{s_id}",
                    title=title,
                    description=f"{album} · {artist}",
                    thumbnail_url=thumb,
                    input_message_content=types.InputTextMessageContent(msg_content),
                    reply_markup=markup
                )
            )

    bot.answer_inline_query(query.id, results, cache_time=1)

# --- 3. ALBUM FULL DOWNLOAD ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("alb_"))
def callback_album(call):
    alb_id = call.data.replace("alb_", "")
    bot.answer_callback_query(call.id, text="Album loading...")

    data = req_api(f"/albums?id={alb_id}")
    songs = []
    album_name = "Album"
    cover_img = None

    if isinstance(data, dict):
        songs = data.get('songs', [])
        album_name = clean_txt(data.get('name') or data.get('title', 'Album'))
        imgs = data.get('image', [])
        if isinstance(imgs, list) and imgs:
            cover_img = imgs[-1].get('link') or imgs[-1].get('url')
    elif isinstance(data, list) and data:
        songs = data[0].get('songs', [])
        album_name = clean_txt(data[0].get('name') or data[0].get('title', 'Album'))

    if not songs:
        bot.send_message(call.message.chat.id, "❌ Paadalgal kidaikkavillai.")
        return

    if cover_img:
        try:
            bot.send_photo(call.message.chat.id, cover_img, caption=f"🗂 {album_name}")
        except Exception:
            pass

    for s in songs:
        send_audio_track(call.message.chat.id, s)

# --- 4. SINGLE SONG DOWNLOAD ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("sng_"))
def callback_song(call):
    s_id = call.data.replace("sng_", "")
    bot.answer_callback_query(call.id, text="Downloading song...")

    data = req_api(f"/songs?id={s_id}")
    song = None
    if isinstance(data, list) and data:
        song = data[0]
    elif isinstance(data, dict):
        song = data.get('songs', [{}])[0] if data.get('songs') else data

    if song:
        send_audio_track(call.message.chat.id, song)
    else:
        bot.send_message(call.message.chat.id, "❌ Song download error.")

# --- 5. DIRECT TEXT ---
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
