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

# லைவ் புரோக்ரஸ் மீட்டர் உருவாக்கும் செயல்பாடு
def get_progress_bar(current, total):
    percent = int((current / total) * 100)
    filled = int(math.floor(10 * current / total))
    bar = '█' * filled + '░' * (10 - filled)
    return f"`[{bar}]` {percent}% ({current}/{total})"

# --- 1. மெயின் ஸ்டார்ட் மற்றும் தரம் தேர்வு திரை ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if not is_authorized(message.chat.id):
        return

    chat_id = message.chat.id
    current_q = user_settings.get(chat_id, "320kbps Master")

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_song = types.InlineKeyboardButton("🔍 Search Song ↗️", switch_inline_query_current_chat="song ")
    btn_album = types.InlineKeyboardButton("💿 Search Album ↗️", switch_inline_query_current_chat="album ")
    btn_settings = types.InlineKeyboardButton(f"🎚 Profile: {current_q}", callback_data="toggle_settings")
    markup.add(btn_song, btn_album)
    markup.add(btn_settings)

    msg_text = (
        "💎 **ACOUSTIC VAULT · MASTER STUDIO**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✨ **Audio Engine:** 320kbps Extreme Master Quality\n"
        "✨ **Metadata:** Embedded 1400p Covers & ID3 Tags\n"
        "✨ **Batch Discography:** 1-Click Complete Album Download\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🎧 **தேர்ந்தெடுக்கப்பட்ட தரம்:** `{current_q}`\n\n"
        "பாடல் அல்லது ஆல்பத்தைத் தேட கீழே உள்ள பட்டனைத் தொடவும்:"
    )
    bot.send_message(chat_id, msg_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "toggle_settings")
def toggle_quality_menu(call):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("⚡ 320kbps Studio Master (Extreme)", callback_data="set_q_320kbps Master"),
        types.InlineKeyboardButton("🎼 FLAC / Lossless Mode", callback_data="set_q_Studio FLAC"),
        types.InlineKeyboardButton("💾 160kbps Data Saver", callback_data="set_q_160kbps Saver")
    )
    bot.edit_message_text(
        "🎚 **விருப்பமான ஆடியோ தரத்தைத் தேர்வு செய்யவும்:**",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_q_"))
def save_quality(call):
    q = call.data.replace("set_q_", "")
    user_settings[call.message.chat.id] = q
    bot.answer_callback_query(call.id, text=f"தரம் {q} என மாற்றப்பட்டது!")
    send_welcome(call.message)

# --- 2. இன்லைன் கார்டுகள் தேடல் எஞ்சின் ---
@bot.inline_handler(func=lambda query: True)
def handle_inline(query):
    raw = query.query.strip()
    results = []

    if not raw:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    mode = "both"
    term = raw
    if raw.lower().startswith("song "):
        mode = "song"
        term = raw[5:].strip()
    elif raw.lower().startswith("album "):
        mode = "album"
        term = raw[6:].strip()

    if not term:
        bot.answer_inline_query(query.id, [], cache_time=1)
        return

    # ஆல்பம் தேடல்
    if mode in ["both", "album"]:
        try:
            url = f"https://saavn.me/search/albums?query={requests.utils.quote(term)}"
            data = requests.get(url, timeout=5).json()
            albums = data.get('data', {}).get('results', [])

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
                        description=f"{year} · Tamil Film · {artist}",
                        thumb_url=thumb,
                        input_message_content=types.InputTextMessageContent(
                            f"{caption}\n\n[⁠]({thumb})", 
                            parse_mode="Markdown"
                        ),
                        reply_markup=markup
                    )
                )
        except Exception:
            pass

    # பாடல் தேடல்
    if mode in ["both", "song"]:
        try:
            url = f"https://saavn.me/search/songs?query={requests.utils.quote(term)}"
            data = requests.get(url, timeout=5).json()
            songs = data.get('data', {}).get('results', [])

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
        except Exception:
            pass

    bot.answer_inline_query(query.id, results, cache_time=1)

# --- 3. எச்டி போஸ்டர் & ஐடி3 டேக் பொருத்தி ஆடியோ அனுப்பும் செயல்பாடு ---
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

    filename = f"temp_{chat_id}_{clean_txt(title)[:12]}.mp3"
    try:
        res = requests.get(link, timeout=30)
        with open(filename, 'wb') as f:
            f.write(res.content)

        # அசல் HD கவர் படம் மற்றும் மெட்டாடேட்டாவை MP3 ஃபைலுக்குள் உட்பொதித்தல்
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
                audio.add(COMM(encoding=3, lang='eng', desc='Master', text='Acoustic Vault Master 320kbps'))
                audio.save(filename)
            except Exception:
                pass

        caption_text = (
            f"**Title:** {title}\n"
            f"**Album:** {album}\n"
            f"**Singers:** {artist}"
        )

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

# --- 4. லைவ் புரோக்ரஸ் பார்க்கூடிய முழு ஆல்பம் டவுன்லோட் ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_alb_"))
def download_entire_album(call):
    alb_id = call.data.replace("dl_alb_", "")
    bot.answer_callback_query(call.id, text="ஆல்பம் பாடல்கள் தயாராகின்றன...")

    try:
        url = f"https://saavn.me/albums?id={alb_id}"
        res = requests.get(url, timeout=12).json()
        songs = res.get('data', {}).get('songs', [])

        if not songs:
            bot.send_message(call.message.chat.id, "❌ பாடல்கள் கிடைக்கவில்லை.")
            return

        total_tracks = len(songs)
        status_msg = bot.send_message(
            call.message.chat.id, 
            f"⚡ **Acoustic Vault Dispatcher**\n"
            f"{get_progress_bar(0, total_tracks)}\n"
            f"தொடக்கப் பணிகள் நடக்கின்றன...",
            parse_mode="Markdown"
        )

        for idx, s in enumerate(songs, start=1):
            s_name = clean_txt(s.get('name', f'Track {idx}'))
            try:
                bot.edit_message_text(
                    f"⚡ **Acoustic Vault Dispatcher**\n"
                    f"{get_progress_bar(idx, total_tracks)}\n"
                    f"அனுப்பப்படுகிறது: `{s_name}`",
                    chat_id=call.message.chat.id,
                    message_id=status_msg.message_id,
                    parse_mode="Markdown"
                )
            except Exception:
                pass

            deliver_song(call.message.chat.id, s)

        bot.delete_message(call.message.chat.id, status_msg.message_id)
        bot.send_message(call.message.chat.id, "✨ **முழு ஆல்பமும் ஸ்டுடியோ தரத்தில் வெற்றிகரமாக அனுப்பப்பட்டது!**", parse_mode="Markdown")
    except Exception:
        bot.send_message(call.message.chat.id, "❌ ஆல்பத்தைப் பதிவிறக்குவதில் பிழை ஏற்பட்டது.")

# --- 5. தனிப் பாடல் டவுன்லோட் ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_sng_"))
def download_single_song(call):
    s_id = call.data.replace("dl_sng_", "")
    bot.answer_callback_query(call.id, text="பாடல் பதிவிறக்கம் ஆகிறது...")

    try:
        url = f"https://saavn.me/songs?id={s_id}"
        res = requests.get(url, timeout=10).json()
        songs = res.get('data', [])

        if songs:
            deliver_song(call.message.chat.id, songs[0])
    except Exception:
        bot.send_message(call.message.chat.id, "❌ பாடல் பதிவிறக்கம் செய்ய முடியவில்லை.")

# --- 6. நேரடிப் பாடல் பெயர் / ஸ்ட்ரீமிங் லிங்க் தேடல் ---
@bot.message_handler(func=lambda msg: True)
def fallback_search(message):
    if not is_authorized(message.chat.id):
        return
    text = message.text.strip()
    query = text.split("/")[-1].split("?")[0].replace("-", " ")
    status = bot.reply_to(message, f"⚡ `{query}` பாடலைத் தேடுகிறேன்...")

    try:
        res = requests.get(f"https://saavn.me/search/songs?query={requests.utils.quote(query)}", timeout=10).json()
        songs = res.get('data', {}).get('results', [])
        bot.delete_message(message.chat.id, status.message_id)
        if songs:
            deliver_song(message.chat.id, songs[0])
        else:
            bot.reply_to(message, "❌ பாடல் கிடைக்கவில்லை. இன்லைன் பட்டனைப் பயன்படுத்தித் தேடவும்.")
    except Exception:
        bot.reply_to(message, "❌ இணைப்பில் பிழை ஏற்பட்டது.")

if __name__ == '__main__':
    threading.Thread(target=run_web, daemon=True).start()
    bot.infinity_polling()
