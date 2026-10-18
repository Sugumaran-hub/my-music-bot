import os
import re
import math
import threading
import requests
from flask import Flask
import telebot
from telebot import types
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TYER, COMM

# Render Port Check Dummy Server
app = Flask(__name__)

@app.route('/')
def home():
    return "Acoustic Vault Audiophile Studio Live!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

BOT_TOKEN = os.environ.get('BOT_TOKEN')
OWNER_ID = os.environ.get('OWNER_ID')

bot = telebot.TeleBot(BOT_TOKEN)
user_settings = {}

def is_authorized(chat_id):
    if OWNER_ID and str(chat_id) != str(OWNER_ID):
        return False
    return True

def clean_txt(text):
    if not text:
        return ""
    return re.sub(r'<.*?>', '', str(text)).replace('&quot;', '"').replace('&amp;', '&').strip()

# லைவ் புரோக்ரஸ் பார்
def get_progress_bar(current, total):
    percent = int((current / total) * 100)
    filled = int(math.floor(10 * current / total))
    bar = '█' * filled + '░' * (10 - filled)
    return f"`[{bar}]` {percent}% ({current}/{total})"

# இரட்டை ஏபிஐ எண்ட்-பாயிண்ட்கள் (Fallback System)
SAAVN_ENDPOINTS = [
    "https://saavn.dev/api",
    "https://saavn.me"
]

def fetch_api(path):
    for base in SAAVN_ENDPOINTS:
        try:
            r = requests.get(f"{base}{path}", timeout=4)
            if r.status_code == 200:
                data = r.json()
                if data.get('success', True) and data.get('data'):
                    return data.get('data')
        except Exception:
            continue
    return None

# --- 1. தொடக்கத் திரை (START & QUALITY PROFILE) ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if not is_authorized(message.chat.id):
        return

    chat_id = message.chat.id
    current_q = user_settings.get(chat_id, "320kbps Master")

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_song = types.InlineKeyboardButton("🔍 Search Song ↗️", switch_inline_query_current_chat="")
    btn_album = types.InlineKeyboardButton("💿 Search Album ↗️", switch_inline_query_current_chat="album ")
    btn_settings = types.InlineKeyboardButton(f"🎚 Profile: {current_q}", callback_data="toggle_settings")
    markup.add(btn_song, btn_album)
    markup.add(btn_settings)

    msg_text = (
        "💎 **ACOUSTIC VAULT · MASTER STUDIO**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✨ **Audio Engine:** 320kbps Extreme Master Quality\n"
        "✨ **Metadata:** Embedded HD Covers & Tags\n"
        "✨ **Discography:** 1-Click Complete Album Download\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🎧 **Profile:** `{current_q}`\n\n"
        "பாடல் அல்லது ஆல்பத்தைத் தேட கீழே உள்ள பட்டனைத் தொடவும்:"
    )
    bot.send_message(chat_id, msg_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "toggle_settings")
def toggle_quality_menu(call):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("⚡ 320kbps Studio Master", callback_data="set_q_320kbps Master"),
        types.InlineKeyboardButton("🎼 FLAC / Lossless Mode", callback_data="set_q_Studio FLAC"),
        types.InlineKeyboardButton("💾 160kbps Data Saver", callback_data="set_q_160kbps Saver")
    )
    bot.edit_message_text(
        "🎚 **Select Audio Quality:**",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_q_"))
def save_quality(call):
    q = call.data.replace("set_q_", "")
    user_settings[call.message.chat.id] = q
    bot.answer_callback_query(call.id, text=f"Profile: {q}")
    send_welcome(call.message)

# --- 2. இன்லைன் உடனடிப் பரிந்துரைகள் எஞ்சின் ---
@bot.inline_handler(func=lambda query: True)
def handle_inline(query):
    raw = query.query.strip()
    results = []

    if not raw:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    is_album = False
    term = raw
    if raw.lower().startswith("album "):
        is_album = True
        term = raw[6:].strip()

    if not term:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    # ஆல்பம் தேடல்
    if is_album:
        data = fetch_api(f"/search/albums?query={requests.utils.quote(term)}")
        albums = data.get('results', []) if isinstance(data, dict) else []

        for alb in albums[:8]:
            alb_id = alb.get('id')
            name = clean_txt(alb.get('name'))
            year = alb.get('year', '')
            artist = clean_txt(alb.get('primaryArtists', 'Various Artists'))
            imgs = alb.get('image', [])
            thumb = imgs[-1].get('link') if imgs else ""

            caption = (
                f"**Album:** {name}\n"
                f"**Description:** Tamil Film · {artist}\n"
                f"**Language:** Tamil\n"
                f"**Year:** {year}"
            )

            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📥 Download Album", callback_data=f"dl_alb_{alb_id}"),
                types.InlineKeyboardButton("🔍 Search again", switch_inline_query_current_chat="album ")
            )

            results.append(
                types.InlineQueryResultArticle(
                    id=f"alb_{alb_id}",
                    title=f"{name}",
                    description=f"{year} · {artist}",
                    thumb_url=thumb,
                    input_message_content=types.InputTextMessageContent(
                        f"{caption}\n\n[⁠]({thumb})", 
                        parse_mode="Markdown"
                    ),
                    reply_markup=markup
                )
            )
    else:
        # பாடல் தேடல்
        data = fetch_api(f"/search/songs?query={requests.utils.quote(term)}")
        songs = data.get('results', []) if isinstance(data, dict) else []

        for sng in songs[:10]:
            s_id = sng.get('id')
            name = clean_txt(sng.get('name'))
            album = clean_txt(sng.get('album', {}).get('name', '')) if isinstance(sng.get('album'), dict) else ''
            artist = clean_txt(sng.get('primaryArtists', ''))
            imgs = sng.get('image', [])
            thumb = imgs[-1].get('link') if imgs else ""

            msg_content = f"🎵 **{name}**\n💿 Album: {album}\n🎤 {artist}"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⬇️ Download 320kbps Master", callback_data=f"dl_sng_{s_id}"))

            results.append(
                types.InlineQueryResultArticle(
                    id=f"sng_{s_id}",
                    title=f"{name}",
                    description=f"{album} · {artist}",
                    thumb_url=thumb,
                    input_message_content=types.InputTextMessageContent(msg_content, parse_mode="Markdown"),
                    reply_markup=markup
                )
            )

    bot.answer_inline_query(query.id, results, cache_time=1)

# --- 3. எச்டி கவர் மற்றும் ஐடி3 டேக்குடன் ஆடியோ அனுப்புதல் ---
def deliver_song(chat_id, song_obj):
    title = clean_txt(song_obj.get('name', 'Track'))
    artist = clean_txt(song_obj.get('primaryArtists', 'Unknown'))
    album = clean_txt(song_obj.get('album', {}).get('name', 'Single')) if isinstance(song_obj.get('album'), dict) else ''
    year = str(song_obj.get('year', ''))

    dl_list = song_obj.get('downloadUrl', [])
    if not dl_list:
        return False

    q_pref = user_settings.get(chat_id, "320kbps Master")
    link = dl_list[-1].get('link') if "160kbps" not in q_pref else dl_list[min(len(dl_list)-1, 2)].get('link')

    imgs = song_obj.get('image', [])
    cover_url = imgs[-1].get('link') if imgs else None

    filename = f"temp_{chat_id}_{clean_txt(title)[:10]}.mp3"
    try:
        res = requests.get(link, timeout=30)
        with open(filename, 'wb') as f:
            f.write(res.content)

        if cover_url:
            try:
                img_data = requests.get(cover_url, timeout=10).content
                try:
                    audio = ID3(filename)
                except Exception:
                    audio = ID3()

                audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_data))
                audio.add(TIT2(encoding=3, text=title))
                audio.add(TPE1(encoding=3, text=artist))
                audio.add(TALB(encoding=3, text=album))
                if year:
                    audio.add(TYER(encoding=3, text=year))
                audio.add(COMM(encoding=3, lang='eng', desc='Master', text='Acoustic Vault Master'))
                audio.save(filename)
            except Exception:
                pass

        caption_text = f"**Title:** {title}\n**Album:** {album}\n**Singers:** {artist}"

        with open(filename, 'rb') as audio_file:
            bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                title=title,
                performer=artist,
                caption=caption_text,
                parse_mode="Markdown"
            )

        if os.path.exists(filename):
            os.remove(filename)
        return True
    except Exception:
        if os.path.exists(filename):
            os.remove(filename)
        return False

# --- 4. முழு ஆல்பம் டவுன்லோட் & லைவ் புரோக்ரஸ் பார் ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_alb_"))
def download_entire_album(call):
    alb_id = call.data.replace("dl_alb_", "")
    bot.answer_callback_query(call.id, text="Album loading...")

    try:
        data = fetch_api(f"/albums?id={alb_id}")
        songs = data.get('songs', []) if isinstance(data, dict) else []

        if not songs:
            bot.send_message(call.message.chat.id, "❌ பாடல்கள் கிடைக்கவில்லை.")
            return

        total_tracks = len(songs)
        status_msg = bot.send_message(
            call.message.chat.id, 
            f"⚡ **Acoustic Vault Dispatcher**\n{get_progress_bar(0, total_tracks)}\nInitializing...",
            parse_mode="Markdown"
        )

        for idx, s in enumerate(songs, start=1):
            s_name = clean_txt(s.get('name', f'Track {idx}'))
            try:
                bot.edit_message_text(
                    f"⚡ **Acoustic Vault Dispatcher**\n{get_progress_bar(idx, total_tracks)}\nSending: `{s_name}`",
                    chat_id=call.message.chat.id,
                    message_id=status_msg.message_id,
                    parse_mode="Markdown"
                )
            except Exception:
                pass

            deliver_song(call.message.chat.id, s)

        bot.delete_message(call.message.chat.id, status_msg.message_id)
        bot.send_message(call.message.chat.id, "✨ **முழு ஆல்பமும் வெற்றிகரமாக அனுப்பப்பட்டது!**", parse_mode="Markdown")
    except Exception:
        bot.send_message(call.message.chat.id, "❌ ஆல்பத்தைப் பதிவிறக்குவதில் பிழை ஏற்பட்டது.")

# --- 5. தனிப் பாடல் பதிவிறக்கம் ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_sng_"))
def download_single_song(call):
    s_id = call.data.replace("dl_sng_", "")
    bot.answer_callback_query(call.id, text="Song loading...")

    try:
        data = fetch_api(f"/songs?id={s_id}")
        songs = data if isinstance(data, list) else [data]
        if songs and songs[0]:
            deliver_song(call.message.chat.id, songs[0])
    except Exception:
        bot.send_message(call.message.chat.id, "❌ பாடல் பதிவிறக்கம் செய்ய முடியவில்லை.")

# --- 6. நேரடி டெக்ஸ்ட் தேடல் ---
@bot.message_handler(func=lambda msg: True)
def fallback_search(message):
    if not is_authorized(message.chat.id):
        return
    text = message.text.strip()
    status = bot.reply_to(message, f"⚡ `{text}` தேடுகிறேன்...")

    try:
        data = fetch_api(f"/search/songs?query={requests.utils.quote(text)}")
        songs = data.get('results', []) if isinstance(data, dict) else []
        bot.delete_message(message.chat.id, status.message_id)
        if songs:
            deliver_song(message.chat.id, songs[0])
        else:
            bot.reply_to(message, "❌ பாடல் கிடைக்கவில்லை. இன்லைன் பட்டனைப் பயன்படுத்தவும்.")
    except Exception:
        bot.reply_to(message, "❌ இணைப்பில் பிழை ஏற்பட்டது.")

# --- 7. AUTO-FIX CONFLICT & POLLING RUNNER ---
if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    try:
        bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    bot.infinity_polling(skip_pending=True)
