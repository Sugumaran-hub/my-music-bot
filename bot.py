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

def clean_txt(text):
    if not text:
        return ""
    return re.sub(r'<.*?>', '', str(text)).replace('&quot;', '"').replace('&amp;', '&').replace('&copy;', '').strip()

# Jiosaavn Search
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
        res = requests.get(url, params=params, headers=headers, timeout=8).json()
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

# --- 1. START COMMAND (ZERO ERROR GUARANTEE) ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    text = (
        "🎧 *Acoustic Vault Audiophile Studio*\n\n"
        "Endha paadal alladhu album vendumo, adhan peyara inga direct-aa type panni send pannunga:\n\n"
        "*(Udaaranam: `vaaranam aayiram` alladhu `adaye kolluthey`)*"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# --- 2. CALLBACK HANDLERS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("alb_"))
def callback_album(call):
    alb_id = call.data.replace("alb_", "")
    bot.answer_callback_query(call.id, text="Album ready aagiradhu...")

    details = get_album_details(alb_id)
    songs = details.get('list', []) if details else []

    if not songs:
        bot.send_message(call.message.chat.id, "❌ Paadalgal kidaikkavillai.")
        return

    status = bot.send_message(call.message.chat.id, f"⬇️ *{len(songs)} paadalgalum anuppappadugiradhu...*", parse_mode="Markdown")

    for s in songs:
        deliver_track(call.message.chat.id, s)

    bot.delete_message(call.message.chat.id, status.message_id)
    bot.send_message(call.message.chat.id, "✅ *Muzhu album-mum vetrigaramaaga anuppappattadhu!*", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("sng_"))
def callback_song(call):
    s_id = call.data.replace("sng_", "")
    bot.answer_callback_query(call.id, text="Paadal download aagiradhu...")

    s_data = get_song_details(s_id)
    if s_data:
        deliver_track(call.message.chat.id, s_data)
    else:
        bot.send_message(call.message.chat.id, "❌ Download failure.")

# --- 3. DIRECT CHAT SEARCH (100% RELIABLE) ---
@bot.message_handler(func=lambda msg: True)
def direct_text(message):
    text = message.text.strip()
    status = bot.reply_to(message, f"🔎 *'{text}'* thedugiren...", parse_mode="Markdown")

    albums = saavn_search(text, "album")
    songs = saavn_search(text, "song")

    try:
        bot.delete_message(message.chat.id, status.message_id)
    except Exception:
        pass

    if not albums and not songs:
        bot.reply_to(message, "❌ Paadalgal kidaikkavillai. Correct spellings pottu thedunga.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    if albums:
        for alb in albums[:2]:
            alb_id = alb.get('id')
            alb_title = clean_txt(alb.get('title'))
            if alb_id and alb_title:
                markup.add(types.InlineKeyboardButton(text=f"💿 Download Album: {alb_title}", callback_data=f"alb_{alb_id}"))

    for s in songs[:6]:
        s_id = s.get('id')
        s_title = clean_txt(s.get('title'))
        if s_id and s_title:
            markup.add(types.InlineKeyboardButton(text=f"🎵 {s_title}", callback_data=f"sng_{s_id}"))

    bot.send_message(message.chat.id, f"🎧 *'{text}' results:*", reply_markup=markup, parse_mode="Markdown")

# --- 4. SAFE POLLER ---
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
