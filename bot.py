"""
KJV Holy Bible Bot (@kjvholybiblebot) — full version
Features: Daily Verse (auto 07:00 Africa/Lagos), Bible Search (reference + keyword),
Read by book/chapter, Topics, 14-day Devotionals, Bible Quiz with scores,
Prayer Requests (forwarded to admin), Admin panel (/admin, hidden from menu).

Deploy on Railway:
  Variables: BOT_TOKEN=..., ADMIN_IDS=your_telegram_id (comma-separate for more)
  Optional:   DAILY_HOUR=7, DATABASE_PATH=bible_bot.db
  Start command: python bot.py

Bible text in 6 languages (free, no key): EN bible-api.com KJV; FR/AR/HI bolls.life;
HA/YO apibible.wbem.org. Keyword search: bolls.life with a built-in topical fallback.
Optional support vars: SUPPORT_LINK (payment link), SUPPORT_DETAILS (bank details text).
Customer menu shows ONLY: /start, /menu, /help  (/admin is typed manually, admin-only)
"""
import asyncio, html, json, logging, os, random, re, sqlite3
from datetime import datetime, date
from zoneinfo import ZoneInfo

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (BotCommand, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bible_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(";", ",").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DATABASE_PATH", "bible_bot.db")
DAILY_HOUR = int(os.getenv("DAILY_HOUR", "7"))
TZ = ZoneInfo(os.getenv("BOT_TIMEZONE", "Africa/Lagos"))
SUPPORT = os.getenv("SUPPORT_CONTACT", "@davidcreativelab")

# ---------------------------------------------------------------- DB
def db():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
          translation TEXT DEFAULT 'kjv', daily_optin INTEGER DEFAULT 1,
          quiz_score INTEGER DEFAULT 0, quiz_answered INTEGER DEFAULT 0,
          joined_at TEXT, last_seen TEXT);
        CREATE TABLE IF NOT EXISTS prayers(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
          full_name TEXT, text TEXT, status TEXT DEFAULT 'new', created_at TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS supports(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
          full_name TEXT, note TEXT, created_at TEXT);
        """)
    try: c.execute("ALTER TABLE users ADD COLUMN language TEXT")
    except Exception: pass

def upsert_user(u):
    now = datetime.now(TZ).isoformat(timespec="seconds")
    with db() as c:
        c.execute("""INSERT INTO users(user_id,username,full_name,joined_at,last_seen)
                     VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                     username=excluded.username, full_name=excluded.full_name, last_seen=excluded.last_seen""",
                  (u.id, u.username or "", u.full_name or "", now, now))

def get_user(uid):
    with db() as c: return c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

def set_user(uid, field, value):
    with db() as c: c.execute(f"UPDATE users SET {field}=? WHERE user_id=?", (value, uid))

def meta_get(k):
    with db() as c:
        r = c.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone(); return r["value"] if r else None

def meta_set(k, v):
    with db() as c: c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))

def is_admin(uid): return uid in ADMIN_IDS

# ---------------------------------------------------------------- content
DAILY_VERSES = [
 ("John 3:16","For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life."),
 ("Psalm 23:1","The LORD is my shepherd; I shall not want."),
 ("Philippians 4:13","I can do all things through Christ which strengtheneth me."),
 ("Proverbs 3:5","Trust in the LORD with all thine heart; and lean not unto thine own understanding."),
 ("Isaiah 41:10","Fear thou not; for I am with thee: be not dismayed; for I am thy God: I will strengthen thee; yea, I will help thee."),
 ("Romans 8:28","And we know that all things work together for good to them that love God, to them who are the called according to his purpose."),
 ("Jeremiah 29:11","For I know the thoughts that I think toward you, saith the LORD, thoughts of peace, and not of evil, to give you an expected end."),
 ("Psalm 46:1","God is our refuge and strength, a very present help in trouble."),
 ("Matthew 11:28","Come unto me, all ye that labour and are heavy laden, and I will give you rest."),
 ("Joshua 1:9","Be strong and of a good courage; be not afraid, neither be thou dismayed: for the LORD thy God is with thee whithersoever thou goest."),
 ("Lamentations 3:22-23","It is of the LORD's mercies that we are not consumed... great is thy faithfulness."),
 ("2 Timothy 1:7","For God hath not given us the spirit of fear; but of power, and of love, and of a sound mind."),
 ("Psalm 118:24","This is the day which the LORD hath made; we will rejoice and be glad in it."),
 ("Hebrews 11:1","Now faith is the substance of things hoped for, the evidence of things not seen."),
 ("John 14:6","I am the way, the truth, and the life: no man cometh unto the Father, but by me."),
 ("Psalm 121:1-2","I will lift up mine eyes unto the hills, from whence cometh my help. My help cometh from the LORD."),
 ("Isaiah 40:31","But they that wait upon the LORD shall renew their strength; they shall mount up with wings as eagles."),
 ("Romans 15:13","Now the God of hope fill you with all joy and peace in believing, that ye may abound in hope."),
 ("1 Corinthians 16:14","Let all your things be done with charity."),
 ("Galatians 5:22","But the fruit of the Spirit is love, joy, peace, longsuffering, gentleness, goodness, faith."),
 ("Psalm 19:14","Let the words of my mouth, and the meditation of my heart, be acceptable in thy sight, O LORD."),
 ("Micah 6:8","What doth the LORD require of thee, but to do justly, and to love mercy, and to walk humbly with thy God?"),
 ("Matthew 6:33","But seek ye first the kingdom of God, and his righteousness; and all these things shall be added unto you."),
 ("John 8:32","And ye shall know the truth, and the truth shall make you free."),
 ("Psalm 37:4","Delight thyself also in the LORD; and he shall give thee the desires of thine heart."),
 ("Romans 12:2","Be not conformed to this world: but be ye transformed by the renewing of your mind."),
 ("Ephesians 2:8","For by grace are ye saved through faith; and that not of yourselves: it is the gift of God."),
 ("1 Peter 5:7","Casting all your care upon him; for he careth for you."),
 ("Deuteronomy 31:8","The LORD, he it is that doth go before thee; he will be with thee, he will not fail thee."),
 ("Revelation 22:20","He which testifieth these things saith, Surely I come quickly. Amen. Even so, come, Lord Jesus."),
 ("Psalm 150:6","Let every thing that hath breath praise the LORD. Praise ye the LORD."),
]
def daily_verse(d=None):
    d = d or datetime.now(TZ).date()
    return DAILY_VERSES[d.toordinal() % len(DAILY_VERSES)]

TOPICS = {
 "hope":       [("Romans 15:13",),("Jeremiah 29:11",),("Hebrews 11:1",)],
 "fear":       [("Isaiah 41:10",),("2 Timothy 1:7",),("Psalm 56:3",)],
 "anxiety":    [("Philippians 4:6",),("1 Peter 5:7",),("Matthew 6:34",)],
 "healing":    [("Isaiah 53:5",),("Psalm 103:2-3",),("James 5:14-15",)],
 "strength":   [("Isaiah 40:31",),("Philippians 4:13",),("Nehemiah 8:10",)],
 "forgiveness":[("1 John 1:9",),("Ephesians 4:32",),("Psalm 103:12",)],
 "love":       [("1 Corinthians 13:4-7",),("John 15:13",),("1 John 4:19",)],
 "faith":      [("Hebrews 11:1",),("Mark 11:22-24",),("Romans 10:17",)],
 "peace":      [("John 14:27",),("Isaiah 26:3",),("Philippians 4:7",)],
 "guidance":   [("Proverbs 3:5-6",),("Psalm 32:8",),("James 1:5",)],
}

DEVOTIONALS = [
 ("Day 1 — God Is With You","Isaiah 41:10","Fear is loud, but it is not in charge. God does not promise to remove every storm — He promises His presence inside it. Today, name the thing you fear, then say the verse over it out loud.","Lord, You are with me. Strengthen my heart today. Amen."),
 ("Day 2 — Trust the Path","Proverbs 3:5-6","Your understanding sees one step; God sees the whole road. Trust is not having all the answers — it is leaning on the One who does.","Father, I lean on You, not on my own understanding. Direct my path. Amen."),
 ("Day 3 — Rest for the Weary","Matthew 11:28","Jesus invites the tired, not the perfect. Whatever weight you carried into today, you were never meant to carry it alone.","Jesus, I come to You. Give my soul rest. Amen."),
 ("Day 4 — Strength While You Wait","Isaiah 40:31","Waiting is not wasted time in God's hands. Eagles do not flap their way above the storm — they ride the wind God provides.","Lord, renew my strength as I wait on You. Amen."),
 ("Day 5 — The Shepherd's Care","Psalm 23:1","A sheep with a shepherd does not need to solve tomorrow. David's confidence was not in his supplies, but in his Shepherd.","Lord, You are my Shepherd. I shall not want. Amen."),
 ("Day 6 — Grace Is Enough","Ephesians 2:8","Salvation is a gift, not a wage. You cannot earn more of God's love today — and you cannot lose it by a bad yesterday.","Thank You, Father, for grace I did not earn. Amen."),
 ("Day 7 — A Sound Mind","2 Timothy 1:7","God gave you power, love and a sound mind — not fear. When anxious thoughts repeat, answer them with what God actually gave.","Holy Spirit, fill me with power, love and a sound mind. Amen."),
 ("Day 8 — Seek First","Matthew 6:33","Put God's kingdom first and anxiety loses its grip on the rest. Order your loves, and God orders your life.","Father, Your kingdom first — everything else in its place. Amen."),
 ("Day 9 — Great Is Thy Faithfulness","Lamentations 3:22-23","Jeremiah wrote this from ruins — faithfulness is proved in hard places. God's mercies are new this morning, not recycled.","Lord, great is Thy faithfulness. Your mercies met me this morning. Amen."),
 ("Day 10 — Casting Your Care","1 Peter 5:7","Casting is an action: throw the worry onto God, on purpose, every time it comes back. He cares — that is the reason given.","Lord, I cast this care on You, because You care for me. Amen."),
 ("Day 11 — The God of Hope","Romans 15:13","Hope is not optimism; it is a Person filling you. Joy and peace grow in believing, not in perfect circumstances.","God of hope, fill me with all joy and peace in believing. Amen."),
 ("Day 12 — Be Strong and Courageous","Joshua 1:9","God commanded courage to a man facing an impossible assignment — because courage rests on 'I will be with thee', not on odds.","Lord, I will be strong and courageous, for You are with me. Amen."),
 ("Day 13 — Transformed Thinking","Romans 12:2","The world presses you into its mould; the Word renews your mind out of it. What you meditate on, you become.","Father, renew my mind by Your Word today. Amen."),
 ("Day 14 — Even So, Come","Revelation 22:20","The Bible ends with a promise and a prayer: He is coming, and His people say 'Come'. Live ready, live hopeful, live holy.","Even so, come, Lord Jesus. Amen."),
]

QUIZ = [
 ("Who built the ark?", ["Noah","Moses","Abraham","David"], 0),
 ("How many days did God take to create the world, before resting?", ["6","7","5","40"], 0),
 ("What was the first plague in Egypt?", ["Water turned to blood","Frogs","Darkness","Locusts"], 0),
 ("Who was swallowed by a great fish?", ["Jonah","Peter","Paul","Elijah"], 0),
 ("Where was Jesus born?", ["Bethlehem","Nazareth","Jerusalem","Egypt"], 0),
 ("Who defeated Goliath?", ["David","Saul","Samson","Solomon"], 0),
 ("How many disciples did Jesus choose?", ["12","10","7","70"], 0),
 ("Who denied Jesus three times?", ["Peter","John","Judas","Thomas"], 0),
 ("What is the first book of the Bible?", ["Genesis","Exodus","Psalms","Matthew"], 0),
 ("Who led Israel out of Egypt?", ["Moses","Aaron","Joshua","Joseph"], 0),
 ("On what day did Jesus rise again?", ["The third day","The same day","After 40 days","The seventh day"], 0),
 ("Who wrote most of the Psalms?", ["David","Solomon","Asaph","Moses"], 0),
 ("What fruit is first listed as the fruit of the Spirit?", ["Love","Joy","Peace","Faith"], 0),
 ("Who was the first man?", ["Adam","Noah","Enoch","Seth"], 0),
 ("Which apostle wrote Revelation?", ["John","Paul","Peter","James"], 0),
]

OLD_TESTAMENT = ["Genesis","Exodus","Leviticus","Numbers","Deuteronomy","Joshua","Judges","Ruth","1 Samuel","2 Samuel","1 Kings","2 Kings","1 Chronicles","2 Chronicles","Ezra","Nehemiah","Esther","Job","Psalms","Proverbs","Ecclesiastes","Song of Solomon","Isaiah","Jeremiah","Lamentations","Ezekiel","Daniel","Hosea","Joel","Amos","Obadiah","Jonah","Micah","Nahum","Habakkuk","Zephaniah","Haggai","Zechariah","Malachi"]
NEW_TESTAMENT = ["Matthew","Mark","Luke","John","Acts","Romans","1 Corinthians","2 Corinthians","Galatians","Ephesians","Philippians","Colossians","1 Thessalonians","2 Thessalonians","1 Timothy","2 Timothy","Titus","Philemon","Hebrews","James","1 Peter","2 Peter","1 John","2 John","3 John","Jude","Revelation"]
BOOK_CHAPTERS = {"Genesis":50,"Exodus":40,"Leviticus":27,"Numbers":36,"Deuteronomy":34,"Joshua":24,"Judges":21,"Ruth":4,"1 Samuel":31,"2 Samuel":24,"1 Kings":22,"2 Kings":25,"1 Chronicles":29,"2 Chronicles":36,"Ezra":10,"Nehemiah":13,"Esther":10,"Job":42,"Psalms":150,"Proverbs":31,"Ecclesiastes":12,"Song of Solomon":8,"Isaiah":66,"Jeremiah":52,"Lamentations":5,"Ezekiel":48,"Daniel":12,"Hosea":14,"Joel":3,"Amos":9,"Obadiah":1,"Jonah":4,"Micah":7,"Nahum":3,"Habakkuk":3,"Zephaniah":3,"Haggai":2,"Zechariah":14,"Malachi":4,"Matthew":28,"Mark":16,"Luke":24,"John":21,"Acts":28,"Romans":16,"1 Corinthians":16,"2 Corinthians":13,"Galatians":6,"Ephesians":6,"Philippians":4,"Colossians":4,"1 Thessalonians":5,"2 Thessalonians":3,"1 Timothy":6,"2 Timothy":4,"Titus":3,"Philemon":1,"Hebrews":13,"James":5,"1 Peter":5,"2 Peter":3,"1 John":5,"2 John":1,"3 John":1,"Jude":1,"Revelation":22}
BOOKS = OLD_TESTAMENT + NEW_TESTAMENT  # all 66 books

AUDIO_BASE = "https://audiotreasure.com/content/KJV_AT"  # free KJV audio, one MP3 per chapter (verified live for 65 of 66 books)
AUDIO_NO_SUFFIX = {"Philemon", "2 John", "3 John", "Jude"}  # single-chapter books are one file, no chapter suffix
def audio_url(book: str, chapter) -> str | None:
    if book not in BOOK_CHAPTERS: return None
    n = BOOKS.index(book) + 1; name = book.replace(" ", "")
    if book in AUDIO_NO_SUFFIX: return f"{AUDIO_BASE}/{n:02d}_{name}.mp3"
    return f"{AUDIO_BASE}/{n:02d}_{name}{int(chapter):03d}.mp3"

async def audio_exists(url: str) -> bool:
    try:
        s = await http()
        async with s.head(url, allow_redirects=True) as r: return r.status == 200
    except Exception: return False

def split_long(text: str, size: int = 3800) -> list[str]:
    parts = []
    while len(text) > size:
        cut = text.rfind(" ", 0, size)
        if cut < size // 2: cut = size
        parts.append(text[:cut].strip()); text = text[cut:].strip()
    if text: parts.append(text)
    return parts

async def send_long(message: Message, text: str, last_markup=None):
    chunks = split_long(text)
    for i, chunk in enumerate(chunks):
        await message.answer(chunk, reply_markup=last_markup if i == len(chunks) - 1 else None)

# ---------------------------------------------------------------- Bible API
_http = None; _http_loop = None
async def http():
    global _http, _http_loop
    loop = asyncio.get_running_loop()
    if _http is None or _http.closed or _http_loop is not loop:
        _http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)); _http_loop = loop
    return _http

async def fetch_reference(ref: str, translation: str = "kjv") -> str | None:
    s = await http()
    try:
        async with s.get(f"https://bible-api.com/{ref.replace(' ', '+')}?translation={translation}") as r:
            if r.status != 200: return None
            d = await r.json()
            verses = " ".join(f"<b>{v.get('verse', '')}</b> {html.escape(v['text'].strip())}" for v in d.get("verses", []) if v.get("text"))
            return f"📖 <b>{html.escape(d.get('reference', ref))}</b> ({translation.upper()})\n\n{verses}" if verses else None
    except Exception as e:
        log.warning("bible-api failed: %s", e); return None

async def keyword_search(query: str, translation: str = "kjv", limit: int = 5) -> list[str]:
    s = await http(); code = "KJV"  # KJV only
    try:
        async with s.get("https://bolls.life/find/" + code + "/", params={"query": query, "match_case": "false", "match_whole": "false", "limit": str(limit)}) as r:
            if r.status != 200: return []
            rows = await r.json()
            out = []
            for row in (rows if isinstance(rows, list) else []):
                txt = re.sub("<[^>]+>", "", row.get("text", "")).strip()
                if txt: out.append(f"📖 <b>{html.escape(row.get('book_name',''))} {row.get('chapter','')}:{row.get('verse','')}</b>\n{html.escape(txt)}")
            return out[:limit]
    except Exception as e:
        log.warning("bolls search failed: %s", e); return []

REF_RE = re.compile(r"^\s*(\d?\s?[A-Za-z]+)\s+(\d+)(?::(\d+)(?:-(\d+))?)?\s*$")

# ---------------------------------------------------------------- languages (6)
# Bible text sources (all free, no key): EN = bible-api.com KJV; FR/AR/HI = bolls.life;
# HA/YO = apibible.wbem.org (Yoruba data there is stored one chapter ahead, hence shift=1).
LANGS = {
 "en": {"native": "English", "version": "King James Version (KJV)"},
 "hi": {"native": "हिन्दी", "version": "Hindi Bible (BSI)", "bolls": "HIOV"},
 "yo": {"native": "Èdè Yorùbá", "version": "Bibeli Mimọ́ (Yoruba Bible)", "wbem": "yo/bm", "shift": 1},
 "fr": {"native": "Français", "version": "Bible Segond 1910", "bolls": "FRLSG"},
 "ha": {"native": "Hausa", "version": "Littafi Mai Tsarki (Hausa Bible)", "wbem": "ha/hau"},
 "ar": {"native": "العربية", "version": "الكتاب المقدس — فان دايك", "bolls": "SVD"},
}
LANG_ORDER = ["en", "hi", "yo", "fr", "ha", "ar"]

def get_lang(uid) -> str:
    u = get_user(uid)
    lang = (u["language"] if u and "language" in u.keys() else None) or "en"
    return lang if lang in LANGS else "en"

def needs_lang_choice(uid) -> bool:
    u = get_user(uid)
    return bool(u) and (u["language"] if "language" in u.keys() else None) is None

def T(lang, key, **kw):
    s = STR.get(lang, STR["en"]).get(key) or STR["en"].get(key, key)
    return s.format(**kw) if kw else s

STR = {
"en": {
 "menu_title": "📖 <b>Holy Bible</b>\n\nWhat would you like to do today?",
 "welcome": "👋 Welcome, {name}!\n\n",
 "verse_day": "Verse of the Day",
 "daily_btn": "📖 Verse of the Day", "search_btn": "🔍 Search the Bible", "read_btn": "📚 Read a Chapter",
 "topics_btn": "💡 Topics", "dev_btn": "🌅 Devotionals", "quiz_btn": "❓ Bible Quiz",
 "prayer_btn": "🙏 Prayer Request", "settings_btn": "⚙️ Settings",
 "support_btn": "❤️ Support Us", "lang_btn": "🌐 Language",
 "back": "⬅️ Main Menu", "choose_lang": "🌐 <b>Choose your language</b>\n\nEverything — menus, Bible text, devotionals and quiz — will be shown in this language.",
 "lang_set": "✅ Language set to English.",
 "search_title": "🔍 <b>Search the Bible</b>\n\nSend a reference like <code>John 3:16</code> or <code>Romans 8</code>, or a keyword like <code>faith</code>, <code>healing</code>, <code>love</code>.",
 "search_fail": "Sorry, I couldn't find that passage. Check the spelling, e.g. <code>John 3:16</code>.",
 "no_results": "No results for “{q}”. Try a topic like <b>hope</b>, <b>faith</b> or <b>healing</b>, or a reference like <code>John 3:16</code>.",
 "kw_note": "Keyword search works in English, Hindi, French and Arabic for now. You can still type any reference (e.g. <code>John 3:16</code>) and read it in your language, or pick a topic from the Topics menu.",
 "read_title": "📚 <b>Read the Bible</b>\n\nChoose a Testament, then tap a book, then tap a chapter — no typing needed.\n\nYou can also type any reference directly, e.g. <code>Psalms 23</code> or <code>John 3:16</code>.",
 "old_test": "📜 Old Testament — 39 books", "new_test": "✝️ New Testament — 27 books",
 "tap_book": "Tap the book you want to read:", "tap_chapter": "Tap a chapter to read it:",
 "chapter_word": "chapter", "chapters_word": "chapters",
 "back_testaments": "⬅️ Back to Testaments", "back_books": "⬅️ Back to Books", "home": "🏠 Main Menu",
 "more_chapters_nav": "More chapters ▶️", "prev_chapters_nav": "◀️ Chapters",
 "listen": "🔊 Listen to {book} {chapter}", "more_chapters": "📚 More chapters of this book",
 "audio_loading": "Loading the audio…",
 "audio_unavail": "🔇 Sorry, audio isn't available for {book} {chapter} yet — please enjoy reading the chapter above.",
 "audio_failed": "🔇 The audio couldn't be sent just now — please try again in a moment.",
 "audio_note": "English narration (KJV)",
 "chapter_fail": "Sorry, I couldn't load that chapter right now. Please try again.",
 "topics_title": "💡 <b>Verses by Topic</b>\n\nChoose what you need today:",
 "topics_fail": "Couldn't load those verses right now — please try again.",
 "prev_day": "◀️ Previous day", "next_day": "Next day ▶️",
 "quiz_title": "❓ <b>Bible Quiz</b>", "correct": "✅ <b>Correct!</b>", "wrong": "❌ Not quite — the answer is <b>{answer}</b>.",
 "your_score": "📊 Your score: <b>{score}/{answered}</b>", "next_q": "➡️ Next question",
 "prayer_title": "🙏 <b>Prayer Request</b>\n\nWrite your prayer request and send it — it goes privately to the ministry team, who will pray for you. Send /menu to cancel.",
 "prayer_sent": "🙏 Thank you — your prayer request has been received. We are praying for you.\n\n<i>“The effectual fervent prayer of a righteous man availeth much.” — James 5:16</i>",
 "settings_title": "⚙️ <b>Settings</b>",
 "version_line": "📖 Bible version: <b>{version}</b>",
 "daily_toggle": "Daily verse 07:00: {state}", "on": "ON ✅", "off": "OFF",
 "help_text": "📖 <b>How to use this bot</b>\n\n• <b>Verse of the Day</b> — a fresh verse daily (auto-sent 07:00 if enabled in Settings)\n• <b>Search</b> — type a reference like <code>John 3:16</code> or a word like <code>faith</code>\n• <b>Read a Chapter</b> — pick Testament → Book → Chapter, every verse is numbered, with a 🔊 Listen button (English KJV audio)\n• <b>Topics</b> — verses for hope, fear, healing and more\n• <b>Devotionals</b> — 14 short daily readings with a prayer\n• <b>Quiz</b> — test your Bible knowledge, scores are saved\n• <b>Prayer Request</b> — sent privately to the ministry team\n• <b>Language</b> — English, हिन्दी, Yorùbá, Français, Hausa, العربية (Settings or the 🌐 button)\n• <b>Support</b> — help keep this bot free for everyone\n\nQuestions? Contact {support}",
 "support_title": "❤️ <b>Support This Ministry</b>",
 "support_body": "This Bible bot is free for everyone, in 6 languages, with daily verses, audio and devotionals. Running it costs money every month — hosting, updates and keeping the reading and listening smooth.\n\nIf the bot has blessed you, please consider supporting it. Every gift, big or small, helps us keep the Word flowing to more people. God bless you! 🙏",
 "support_how": "💝 <b>How to support</b>",
 "support_contact_default": "Please contact the ministry team at {support} and they will gladly share how you can give.",
 "support_done_btn": "✅ I have supported",
 "support_note_prompt": "🙏 Thank you! If you like, write a short note (e.g. the amount and method) so we can thank you properly — or tap Skip.",
 "skip": "Skip ⏭",
 "support_thanks": "❤️ <b>Thank you for supporting this ministry!</b> Your gift helps keep the Bible free and smooth for readers and listeners everywhere. May God bless you richly. 🙏",
 "daily_tail": "Open /menu for today's devotional and quiz.",
 "not_understood": "Send me a Bible reference like <code>John 3:16</code>, a topic like <b>hope</b> or <b>healing</b>, or open the menu:",
 "type_ref_hint": "Please tap a Testament → Book → Chapter above, or send a full reference like <code>Psalms 23</code>.",
 "read_fail": "Sorry, I couldn't load that chapter. Try e.g. <code>John 1</code>.",
 "menu_prompt": "Use the menu below to search the Bible, read devotionals, take the quiz, or send a prayer request.",
},
"fr": {
 "menu_title": "📖 <b>Sainte Bible</b>\n\nQue voulez-vous faire aujourd'hui ?",
 "welcome": "👋 Bienvenue, {name} !\n\n",
 "verse_day": "Verset du jour",
 "daily_btn": "📖 Verset du jour", "search_btn": "🔍 Rechercher", "read_btn": "📚 Lire un chapitre",
 "topics_btn": "💡 Thèmes", "dev_btn": "🌅 Méditations", "quiz_btn": "❓ Quiz biblique",
 "prayer_btn": "🙏 Demande de prière", "settings_btn": "⚙️ Réglages",
 "support_btn": "❤️ Nous soutenir", "lang_btn": "🌐 Langue",
 "back": "⬅️ Menu principal", "choose_lang": "🌐 <b>Choisissez votre langue</b>\n\nTout — menus, texte biblique, méditations et quiz — sera affiché dans cette langue.",
 "lang_set": "✅ Langue définie : Français.",
 "search_title": "🔍 <b>Rechercher dans la Bible</b>\n\nEnvoyez une référence comme <code>Jean 3:16</code> ou <code>Romains 8</code>, ou un mot-clé comme <code>foi</code>, <code>guérison</code>, <code>amour</code>.",
 "search_fail": "Désolé, je n'ai pas trouvé ce passage. Vérifiez l'orthographe, ex. <code>Jean 3:16</code>.",
 "no_results": "Aucun résultat pour « {q} ». Essayez un thème comme <b>espoir</b>, <b>foi</b> ou <b>guérison</b>, ou une référence comme <code>Jean 3:16</code>.",
 "kw_note": "La recherche par mot-clé fonctionne en anglais, hindi, français et arabe. Tapez une référence (ex. <code>Jean 3:16</code>) pour la lire dans votre langue.",
 "read_title": "📚 <b>Lire la Bible</b>\n\nChoisissez un Testament, puis un livre, puis un chapitre — sans rien taper.\n\nVous pouvez aussi taper une référence, ex. <code>Psaumes 23</code> ou <code>Jean 3:16</code>.",
 "old_test": "📜 Ancien Testament — 39 livres", "new_test": "✝️ Nouveau Testament — 27 livres",
 "tap_book": "Touchez le livre à lire :", "tap_chapter": "Touchez un chapitre pour le lire :",
 "chapter_word": "chapitre", "chapters_word": "chapitres",
 "back_testaments": "⬅️ Retour aux Testaments", "back_books": "⬅️ Retour aux livres", "home": "🏠 Menu principal",
 "more_chapters_nav": "Plus de chapitres ▶️", "prev_chapters_nav": "◀️ Chapitres",
 "listen": "🔊 Écouter {book} {chapter}", "more_chapters": "📚 Autres chapitres de ce livre",
 "audio_loading": "Chargement de l'audio…",
 "audio_unavail": "🔇 Désolé, l'audio n'est pas encore disponible pour {book} {chapter} — bonne lecture du chapitre ci-dessus.",
 "audio_failed": "🔇 L'audio n'a pas pu être envoyé — réessayez dans un moment.",
 "audio_note": "Narration en anglais (KJV)",
 "chapter_fail": "Désolé, impossible de charger ce chapitre. Réessayez.",
 "topics_title": "💡 <b>Versets par thème</b>\n\nChoisissez ce dont vous avez besoin aujourd'hui :",
 "topics_fail": "Impossible de charger ces versets — réessayez.",
 "prev_day": "◀️ Jour précédent", "next_day": "Jour suivant ▶️",
 "quiz_title": "❓ <b>Quiz biblique</b>", "correct": "✅ <b>Correct !</b>", "wrong": "❌ Pas tout à fait — la réponse est <b>{answer}</b>.",
 "your_score": "📊 Votre score : <b>{score}/{answered}</b>", "next_q": "➡️ Question suivante",
 "prayer_title": "🙏 <b>Demande de prière</b>\n\nÉcrivez votre demande et envoyez-la — elle parvient en privé à l'équipe du ministère, qui priera pour vous. Envoyez /menu pour annuler.",
 "prayer_sent": "🙏 Merci — votre demande de prière a été reçue. Nous prions pour vous.\n\n<i>« La prière fervente du juste a une grande efficacité. » — Jacques 5:16</i>",
 "settings_title": "⚙️ <b>Réglages</b>",
 "version_line": "📖 Version de la Bible : <b>{version}</b>",
 "daily_toggle": "Verset quotidien 07:00 : {state}", "on": "OUI ✅", "off": "NON",
 "help_text": "📖 <b>Comment utiliser ce bot</b>\n\n• <b>Verset du jour</b> — un verset frais chaque jour (envoyé à 07:00 si activé)\n• <b>Recherche</b> — une référence comme <code>Jean 3:16</code> ou un mot comme <code>foi</code>\n• <b>Lire un chapitre</b> — Testament → Livre → Chapitre, versets numérotés, bouton 🔊 Écouter (audio anglais KJV)\n• <b>Thèmes</b> — versets pour l'espoir, la peur, la guérison…\n• <b>Méditations</b> — 14 lectures quotidiennes avec prière\n• <b>Quiz</b> — testez vos connaissances, scores enregistrés\n• <b>Demande de prière</b> — envoyée en privé à l'équipe\n• <b>Langue</b> — English, हिन्दी, Yorùbá, Français, Hausa, العربية\n• <b>Soutien</b> — aidez à garder ce bot gratuit pour tous\n\nDes questions ? Contactez {support}",
 "support_title": "❤️ <b>Soutenir ce ministère</b>",
 "support_body": "Ce bot biblique est gratuit pour tous, en 6 langues, avec versets quotidiens, audio et méditations. Son fonctionnement coûte chaque mois — hébergement, mises à jour, lecture et écoute fluides.\n\nSi ce bot vous a béni, pensez à le soutenir. Chaque don, petit ou grand, aide la Parole à atteindre plus de personnes. Que Dieu vous bénisse ! 🙏",
 "support_how": "💝 <b>Comment soutenir</b>",
 "support_contact_default": "Contactez l'équipe du ministère à {support} : elle vous indiquera volontiers comment donner.",
 "support_done_btn": "✅ J'ai donné",
 "support_note_prompt": "🙏 Merci ! Si vous le souhaitez, écrivez un petit mot (ex. montant et moyen) pour que nous puissions vous remercier — ou touchez Passer.",
 "skip": "Passer ⏭",
 "support_thanks": "❤️ <b>Merci de soutenir ce ministère !</b> Votre don aide à garder la Bible gratuite et fluide pour les lecteurs et auditeurs partout. Que Dieu vous bénisse richement. 🙏",
 "daily_tail": "Ouvrez /menu pour la méditation et le quiz du jour.",
 "not_understood": "Envoyez-moi une référence comme <code>Jean 3:16</code>, un thème comme <b>espoir</b> ou <b>guérison</b>, ou ouvrez le menu :",
 "type_ref_hint": "Touchez Testament → Livre → Chapitre ci-dessus, ou envoyez une référence complète comme <code>Psaumes 23</code>.",
 "read_fail": "Désolé, impossible de charger ce chapitre. Essayez ex. <code>Jean 1</code>.",
 "menu_prompt": "Utilisez le menu ci-dessous pour rechercher, lire, méditer, faire le quiz ou envoyer une prière.",
},
}

STR["hi"] = {
 "menu_title": "📖 <b>पवित्र बाइबल</b>\n\nआज आप क्या करना चाहेंगे?",
 "welcome": "👋 स्वागत है, {name}!\n\n",
 "verse_day": "आज का वचन",
 "daily_btn": "📖 आज का वचन", "search_btn": "🔍 बाइबल खोजें", "read_btn": "📚 अध्याय पढ़ें",
 "topics_btn": "💡 विषय", "dev_btn": "🌅 मनन", "quiz_btn": "❓ बाइबल प्रश्नोत्तरी",
 "prayer_btn": "🙏 प्रार्थना निवेदन", "settings_btn": "⚙️ सेटिंग्स",
 "support_btn": "❤️ सहयोग करें", "lang_btn": "🌐 भाषा",
 "back": "⬅️ मुख्य मेनू", "choose_lang": "🌐 <b>अपनी भाषा चुनें</b>\n\nसब कुछ — मेनू, बाइबल पाठ, मनन और प्रश्नोत्तरी — इसी भाषा में दिखेगा।",
 "lang_set": "✅ भाषा हिंदी सेट हो गई।",
 "search_title": "🔍 <b>बाइबल खोजें</b>\n\nकोई संदर्भ भेजें जैसे <code>यूहन्ना 3:16</code> या <code>रोमियों 8</code>, या कोई शब्द जैसे <code>विश्वास</code>, <code>चंगाई</code>, <code>प्रेम</code>।",
 "search_fail": "क्षमा करें, वह अंश नहीं मिला। वर्तनी जाँचें, जैसे <code>यूहन्ना 3:16</code>।",
 "no_results": "“{q}” के लिए कोई परिणाम नहीं। कोई विषय आज़माएँ जैसे <b>आशा</b>, <b>विश्वास</b> या <b>चंगाई</b>, या संदर्भ जैसे <code>यूहन्ना 3:16</code>।",
 "kw_note": "शब्द-खोज अभी अंग्रेज़ी, हिंदी, फ़्रेंच और अरबी में काम करती है। आप कोई भी संदर्भ (जैसे <code>यूहन्ना 3:16</code>) अपनी भाषा में पढ़ सकते हैं।",
 "read_title": "📚 <b>बाइबल पढ़ें</b>\n\nपहले नियम चुनें, फिर पुस्तक, फिर अध्याय — टाइप करने की ज़रूरत नहीं।\n\nआप सीधे संदर्भ भी भेज सकते हैं, जैसे <code>भजन 23</code> या <code>यूहन्ना 3:16</code>।",
 "old_test": "📜 पुराना नियम — 39 पुस्तकें", "new_test": "✝️ नया नियम — 27 पुस्तकें",
 "tap_book": "जो पुस्तक पढ़ना चाहें उसे छूएँ:", "tap_chapter": "पढ़ने के लिए अध्याय छूएँ:",
 "chapter_word": "अध्याय", "chapters_word": "अध्याय",
 "back_testaments": "⬅️ नियमों पर वापस", "back_books": "⬅️ पुस्तकों पर वापस", "home": "🏠 मुख्य मेनू",
 "more_chapters_nav": "और अध्याय ▶️", "prev_chapters_nav": "◀️ अध्याय",
 "listen": "🔊 सुनें {book} {chapter}", "more_chapters": "📚 इस पुस्तक के और अध्याय",
 "audio_loading": "ऑडियो लोड हो रहा है…",
 "audio_unavail": "🔇 क्षमा करें, {book} {chapter} के लिए ऑडियो अभी उपलब्ध नहीं है — कृपया ऊपर का अध्याय पढ़ें।",
 "audio_failed": "🔇 ऑडियो भेजा नहीं जा सका — थोड़ी देर में फिर कोशिश करें।",
 "audio_note": "अंग्रेज़ी वर्णन (KJV)",
 "chapter_fail": "क्षमा करें, यह अध्याय अभी लोड नहीं हो सका। फिर कोशिश करें।",
 "topics_title": "💡 <b>विषय अनुसार वचन</b>\n\nआज आपको क्या चाहिए, चुनें:",
 "topics_fail": "वे वचन अभी लोड नहीं हो सके — फिर कोशिश करें।",
 "prev_day": "◀️ पिछला दिन", "next_day": "अगला दिन ▶️",
 "quiz_title": "❓ <b>बाइबल प्रश्नोत्तरी</b>", "correct": "✅ <b>सही!</b>", "wrong": "❌ बिल्कुल नहीं — उत्तर है <b>{answer}</b>।",
 "your_score": "📊 आपका स्कोर: <b>{score}/{answered}</b>", "next_q": "➡️ अगला प्रश्न",
 "prayer_title": "🙏 <b>प्रार्थना निवेदन</b>\n\nअपना प्रार्थना निवेदन लिखकर भेजें — यह निजी रूप से सेवकाई टीम के पास जाता है, वे आपके लिए प्रार्थना करेंगे। रद्द करने के लिए /menu भेजें।",
 "prayer_sent": "🙏 धन्यवाद — आपका प्रार्थना निवेदन मिल गया है। हम आपके लिए प्रार्थना कर रहे हैं।\n\n<i>“धर्मी जन की प्रार्थना का प्रभाव बहुत होता है।” — याकूब 5:16</i>",
 "settings_title": "⚙️ <b>सेटिंग्स</b>",
 "version_line": "📖 बाइबल संस्करण: <b>{version}</b>",
 "daily_toggle": "रोज़ का वचन 07:00: {state}", "on": "चालू ✅", "off": "बंद",
 "help_text": "📖 <b>इस बॉट का उपयोग कैसे करें</b>\n\n• <b>आज का वचन</b> — रोज़ एक नया वचन (सेटिंग में चालू हो तो 07:00 पर अपने आप)\n• <b>खोज</b> — संदर्भ जैसे <code>यूहन्ना 3:16</code> या शब्द जैसे <code>विश्वास</code>\n• <b>अध्याय पढ़ें</b> — नियम → पुस्तक → अध्याय, हर पद क्रमांकित, 🔊 सुनें बटन (अंग्रेज़ी KJV ऑडियो)\n• <b>विषय</b> — आशा, भय, चंगाई आदि के वचन\n• <b>मनन</b> — प्रार्थना सहित 14 छोटे दैनिक पाठ\n• <b>प्रश्नोत्तरी</b> — अपने बाइबल ज्ञान की जाँच, स्कोर सहेजा जाता है\n• <b>प्रार्थना निवेदन</b> — निजी रूप से टीम को भेजा जाता है\n• <b>भाषा</b> — English, हिन्दी, Yorùbá, Français, Hausa, العربية\n• <b>सहयोग</b> — इस बॉट को सबके लिए मुफ़्त रखने में मदद करें\n\nप्रश्न? संपर्क करें {support}",
 "support_title": "❤️ <b>इस सेवकाई का सहयोग करें</b>",
 "support_body": "यह बाइबल बॉट 6 भाषाओं में सबके लिए मुफ़्त है — रोज़ के वचन, ऑडियो और मनन के साथ। इसे चलाने में हर महीने खर्च आता है — होस्टिंग, अपडेट, और पढ़ना-सुनना सुचारु रखना।\n\nयदि इस बॉट ने आपको आशीष दी है, तो कृपया सहयोग करें। हर दान, छोटा या बड़ा, वचन को और लोगों तक पहुँचाने में मदद करता है। परमेश्वर आपको आशीष दे! 🙏",
 "support_how": "💝 <b>सहयोग कैसे करें</b>",
 "support_contact_default": "कृपया सेवकाई टीम से {support} पर संपर्क करें — वे खुशी से दान का तरीका बताएँगे।",
 "support_done_btn": "✅ मैंने सहयोग किया",
 "support_note_prompt": "🙏 धन्यवाद! चाहें तो छोटा नोट लिखें (जैसे राशि और तरीका) ताकि हम धन्यवाद दे सकें — या छोड़ें दबाएँ।",
 "skip": "छोड़ें ⏭",
 "support_thanks": "❤️ <b>इस सेवकाई के सहयोग के लिए धन्यवाद!</b> आपका दान बाइबल को हर जगह पाठकों और श्रोताओं के लिए मुफ़्त और सुचारु रखने में मदद करता है। परमेश्वर आपको बहुत आशीष दे। 🙏",
 "daily_tail": "आज के मनन और प्रश्नोत्तरी के लिए /menu खोलें।",
 "not_understood": "मुझे कोई बाइबल संदर्भ भेजें जैसे <code>यूहन्ना 3:16</code>, कोई विषय जैसे <b>आशा</b> या <b>चंगाई</b>, या मेनू खोलें:",
 "type_ref_hint": "कृपया ऊपर नियम → पुस्तक → अध्याय छूएँ, या पूरा संदर्भ भेजें जैसे <code>भजन 23</code>।",
 "read_fail": "क्षमा करें, वह अध्याय लोड नहीं हुआ। जैसे <code>यूहन्ना 1</code> आज़माएँ।",
 "menu_prompt": "नीचे के मेनू से बाइबल खोजें, मनन पढ़ें, प्रश्नोत्तरी खेलें या प्रार्थना निवेदन भेजें।",
}
STR["ha"] = {
 "menu_title": "📖 <b>Littafi Mai Tsarki</b>\n\nMe kake so ka yi yau?",
 "welcome": "👋 Barka da zuwa, {name}!\n\n",
 "verse_day": "Ayar Rana",
 "daily_btn": "📖 Ayar Rana", "search_btn": "🔍 Bincika Littafi", "read_btn": "📚 Karanta Sura",
 "topics_btn": "💡 Batutuwa", "dev_btn": "🌅 Ibada ta Rana", "quiz_btn": "❓ Tambayoyin Littafi",
 "prayer_btn": "🙏 Buƙatar Addu'a", "settings_btn": "⚙️ Saituna",
 "support_btn": "❤️ Taimaka Mana", "lang_btn": "🌐 Harshe",
 "back": "⬅️ Babban Menu", "choose_lang": "🌐 <b>Zaɓi harshenka</b>\n\nKomai — menu, nassin Littafi, ibada da tambayoyi — za a nuna cikin wannan harshe.",
 "lang_set": "✅ An saita harshe zuwa Hausa.",
 "search_title": "🔍 <b>Bincika Littafi Mai Tsarki</b>\n\nAika nassi kamar <code>Yohanna 3:16</code> ko <code>Romawa 8</code>, ko kalma kamar <code>bangaskiya</code>, <code>warkarwa</code>, <code>ƙauna</code>.",
 "search_fail": "Yi haƙuri, ban sami wannan nassin ba. Duba rubutun, misali <code>Yohanna 3:16</code>.",
 "no_results": "Babu sakamako na “{q}”. Gwada batu kamar <b>bege</b>, <b>bangaskiya</b> ko <b>warkarwa</b>, ko nassi kamar <code>Yohanna 3:16</code>.",
 "kw_note": "Binciken kalmomi yana aiki cikin Ingilishi, Hindi, Faransanci da Larabci a yanzu. Za ka iya rubuta kowanne nassi (misali <code>Yohanna 3:16</code>) ka karanta shi da harshenka, ko ka zaɓi batu daga menu na Batutuwa.",
 "read_title": "📚 <b>Karanta Littafi Mai Tsarki</b>\n\nZaɓi Alkawari, sai littafi, sai sura — ba sai ka rubuta komai ba.\n\nZa ka kuma iya rubuta nassi kai tsaye, misali <code>Zabura 23</code> ko <code>Yohanna 3:16</code>.",
 "old_test": "📜 Tsohon Alkawari — littattafai 39", "new_test": "✝️ Sabon Alkawari — littattafai 27",
 "tap_book": "Taɓa littafin da kake so ka karanta:", "tap_chapter": "Taɓa sura don karanta ta:",
 "chapter_word": "sura", "chapters_word": "surori",
 "back_testaments": "⬅️ Komawa Alkawari", "back_books": "⬅️ Komawa Littattafai", "home": "🏠 Babban Menu",
 "more_chapters_nav": "Ƙarin surori ▶️", "prev_chapters_nav": "◀️ Surori",
 "listen": "🔊 Saurari {book} {chapter}", "more_chapters": "📚 Ƙarin surori na wannan littafi",
 "audio_loading": "Ana loda sautin…",
 "audio_unavail": "🔇 Yi haƙuri, sauti bai samu ba tukuna na {book} {chapter} — ka ji daɗin karanta surar a sama.",
 "audio_failed": "🔇 Ba a iya aika sautin ba a yanzu — sake gwadawa bayan ɗan lokaci.",
 "audio_note": "Sautin Ingilishi ne (KJV)",
 "chapter_fail": "Yi haƙuri, ba a iya loda wannan surar ba a yanzu. Sake gwadawa.",
 "topics_title": "💡 <b>Ayoyi bisa Batu</b>\n\nZaɓi abin da kake buƙata yau:",
 "topics_fail": "Ba a iya loda waɗannan ayoyin ba a yanzu — sake gwadawa.",
 "prev_day": "◀️ Ranar baya", "next_day": "Rana ta gaba ▶️",
 "quiz_title": "❓ <b>Tambayoyin Littafi</b>", "correct": "✅ <b>Daidai ne!</b>", "wrong": "❌ Ba haka ba — amsar ita ce <b>{answer}</b>.",
 "your_score": "📊 Makin ka: <b>{score}/{answered}</b>", "next_q": "➡️ Tambaya ta gaba",
 "prayer_title": "🙏 <b>Buƙatar Addu'a</b>\n\nRubuta buƙatar addu'arka ka aika — za ta tafi a ɓoye zuwa ga ƙungiyar hidima, za su yi addu'a dominka. Aika /menu don sokewa.",
 "prayer_sent": "🙏 Na gode — an karɓi buƙatar addu'arka. Muna addu'a dominka.\n\n<i>“Addu'ar mai adalci tana da iko sosai.” — Yakubu 5:16</i>",
 "settings_title": "⚙️ <b>Saituna</b>",
 "version_line": "📖 Sigar Littafi: <b>{version}</b>",
 "daily_toggle": "Ayar rana 07:00: {state}", "on": "A KUNNE ✅", "off": "A KASHE",
 "help_text": "📖 <b>Yadda ake amfani da wannan bot</b>\n\n• <b>Ayar Rana</b> — sabuwar aya kowace rana (aika 07:00 idan an kunna a Saituna)\n• <b>Bincike</b> — nassi kamar <code>Yohanna 3:16</code> ko kalma kamar <code>bangaskiya</code>\n• <b>Karanta Sura</b> — Alkawari → Littafi → Sura, kowace aya mai lamba, tare da maɓallin 🔊 Saurara (sautin KJV na Ingilishi)\n• <b>Batutuwa</b> — ayoyi kan bege, tsoro, warkarwa da sauransu\n• <b>Ibada ta Rana</b> — karatun yau da kullum 14 tare da addu'a\n• <b>Tambayoyi</b> — gwada iliminka na Littafi, ana ajiye maki\n• <b>Buƙatar Addu'a</b> — a ɓoye zuwa ga ƙungiyar hidima\n• <b>Harshe</b> — English, हिन्दी, Yorùbá, Français, Hausa, العربية\n• <b>Taimako</b> — taimaka a ci gaba da wannan bot kyauta ga kowa\n\nTambaya? Tuntuɓi {support}",
 "support_title": "❤️ <b>Taimaka wa Wannan Hidima</b>",
 "support_body": "Wannan bot na Littafi kyauta ne ga kowa, cikin harsuna 6, tare da ayoyin rana, sauti da ibada. Gudanar da shi yana kashe kuɗi kowane wata — masauki, sabuntawa, da sa karatu da sauraro su yi santsi.\n\nIdan wannan bot ya albarkace ka, don Allah ka taimaka masa. Kowane taimako, ƙarami ko babba, yana taimakawa wajen kai Maganar Allah ga ƙarin mutane. Allah ya albarkace ka! 🙏",
 "support_how": "💝 <b>Yadda ake taimakawa</b>",
 "support_contact_default": "Don Allah tuntubi ƙungiyar hidima a {support} — za su yi farin cikin gaya maka yadda za ka bayar.",
 "support_done_btn": "✅ Na taimaka",
 "support_note_prompt": "🙏 Na gode! Idan kana so, rubuta ɗan taƙaitaccen bayani (misali adadi da hanyar da ka bayar) don mu gode maka yadda ya kamata — ko ka taɓa Tsallakewa.",
 "skip": "Tsallakewa ⏭",
 "support_thanks": "❤️ <b>Na gode da taimaka wa wannan hidima!</b> Taimakonka yana sa Littafi ya kasance kyauta da santsi ga masu karatu da masu sauraro a ko'ina. Allah ya albarkace ka sosai. 🙏",
 "daily_tail": "Buɗe /menu don ibada da tambayoyin yau.",
 "not_understood": "Aiko mini nassi kamar <code>Yohanna 3:16</code>, batu kamar <b>bege</b> ko <b>warkarwa</b>, ko buɗe menu:",
 "type_ref_hint": "Don Allah taɓa Alkawari → Littafi → Sura a sama, ko aika cikakken nassi kamar <code>Zabura 23</code>.",
 "read_fail": "Yi haƙuri, ba a iya loda wannan surar ba. Gwada misali <code>Yohanna 1</code>.",
 "menu_prompt": "Yi amfani da menu a ƙasa don bincike, ibada, tambayoyi, ko buƙatar addu'a.",
}
STR["yo"] = {
 "menu_title": "📖 <b>Bíbélì Mímọ́</b>\n\nKí ni ìwọ yóò fẹ́ ṣe lónìí?",
 "welcome": "👋 Káàbọ̀, {name}!\n\n",
 "verse_day": "Ẹsẹ Ọjọ́",
 "daily_btn": "📖 Ẹsẹ Ọjọ́", "search_btn": "🔍 Wá Bíbélì", "read_btn": "📚 Ka Orí Kan",
 "topics_btn": "💡 Àwọn Kókó", "dev_btn": "🌅 Ìwàásù Ojoojúmọ́", "quiz_btn": "❓ Ìbéèrè Bíbélì",
 "prayer_btn": "🙏 Ìbéèrè Àdúrà", "settings_btn": "⚙️ Ètò",
 "support_btn": "❤️ Ṣe Ìrànlọ́wọ́", "lang_btn": "🌐 Èdè",
 "back": "⬅️ Àkọ́kọ́ Menu", "choose_lang": "🌐 <b>Yan èdè rẹ</b>\n\nGbogbo ohun — menu, ọ̀rọ̀ Bíbélì, ìwàásù àti ìbéèrè — ni a ó fi hàn ní èdè yìí.",
 "lang_set": "✅ A ti yan èdè Yorùbá.",
 "search_title": "🔍 <b>Wá Bíbélì</b>\n\nFi ìtọ́kasí ránṣẹ́ bíi <code>Johanu 3:16</code> tàbí <code>Romu 8</code>, tàbí ọ̀rọ̀ bíi <code>ìgbàgbọ́</code>, <code>ìwòsàn</code>, <code>ìfẹ́</code>.",
 "search_fail": "Má bínú, n kò rí abala náà. Ṣàyẹ̀wò ìkọ̀wé rẹ̀, bíi <code>Johanu 3:16</code>.",
 "no_results": "Kò sí èsì fún “{q}”. Gbìyànjú kókó bíi <b>ìrètí</b>, <b>ìgbàgbọ́</b> tàbí <b>ìwòsàn</b>, tàbí ìtọ́kasí bíi <code>Johanu 3:16</code>.",
 "kw_note": "Wíwá ọ̀rọ̀ ń ṣiṣẹ́ ní Gẹ̀ẹ́sì, Hindi, Faransé àti Lárúbáwá fún ìsinsìnyí. Ìwọ lè kọ ìtọ́kasí èyíkéyìí (bíi <code>Johanu 3:16</code>) kí o sì kà á ní èdè rẹ.",
 "read_title": "📚 <b>Ka Bíbélì</b>\n\nYan Májẹ̀mú, lẹ́yìn náà ìwé, lẹ́yìn náà orí — o kò nílò láti tẹ nǹkan kọ.\n\nÌwọ tún lè kọ ìtọ́kasí taàrà, bíi <code>Saamu 23</code> tàbí <code>Johanu 3:16</code>.",
 "old_test": "📜 Májẹ̀mú Láíláí — ìwé 39", "new_test": "✝️ Májẹ̀mú Tuntun — ìwé 27",
 "tap_book": "Fọwọ́ kan ìwé tí ìwọ yóò fẹ́ kà:", "tap_chapter": "Fọwọ́ kan orí láti kà á:",
 "chapter_word": "orí", "chapters_word": "orí",
 "back_testaments": "⬅️ Padà sí Májẹ̀mú", "back_books": "⬅️ Padà sí Ìwé", "home": "🏠 Àkọ́kọ́ Menu",
 "more_chapters_nav": "Àwọn orí sí i ▶️", "prev_chapters_nav": "◀️ Àwọn orí",
 "listen": "🔊 Gbọ́ {book} {chapter}", "more_chapters": "📚 Àwọn orí sí i ti ìwé yìí",
 "audio_loading": "Ó ń ṣí ohùn náà…",
 "audio_unavail": "🔇 Má bínú, ohùn kò tíì sí fún {book} {chapter} — jọ̀wọ́ gbádùn kíka orí tí ó wà lókè.",
 "audio_failed": "🔇 A kò lè fi ohùn náà ránṣẹ́ nísinsìnyí — gbìyànjú lẹ́ẹ̀kan sí i ní ìṣẹ́jú díẹ̀.",
 "audio_note": "Ohùn Gẹ̀ẹ́sì (KJV)",
 "chapter_fail": "Má bínú, n kò lè ṣí orí náà nísinsìnyí. Jọ̀wọ́ gbìyànjú sí i.",
 "topics_title": "💡 <b>Àwọn Ẹsẹ gẹ́gẹ́ bí Kókó</b>\n\nYan ohun tí ìwọ nílò lónìí:",
 "topics_fail": "A kò lè ṣí àwọn ẹsẹ náà nísinsìnyí — gbìyànjú sí i.",
 "prev_day": "◀️ Ọjọ́ tí ó ṣáájú", "next_day": "Ọjọ́ tí ó tẹ̀lé ▶️",
 "quiz_title": "❓ <b>Ìbéèrè Bíbélì</b>", "correct": "✅ <b>Ó tọ́!</b>", "wrong": "❌ Kò rí bẹ́ẹ̀ — ìdáhùn ni <b>{answer}</b>.",
 "your_score": "📊 Àmì rẹ: <b>{score}/{answered}</b>", "next_q": "➡️ Ìbéèrè tí ó tẹ̀lé",
 "prayer_title": "🙏 <b>Ìbéèrè Àdúrà</b>\n\nKọ ìbéèrè àdúrà rẹ kí o sì fi ránṣẹ́ — ó lọ ní ìkọ̀kọ̀ sí ẹgbẹ́ ìránṣẹ́, wọn yóò gbàdúrà fún ọ. Fi /menu ránṣẹ́ láti fagilé.",
 "prayer_sent": "🙏 O ṣé — a ti gba ìbéèrè àdúrà rẹ. A ń gbàdúrà fún ọ.\n\n<i>“Àdúrà olódodo tí ó ní agbára ń ṣe ohun ńlá.” — Jakọbu 5:16</i>",
 "settings_title": "⚙️ <b>Ètò</b>",
 "version_line": "📖 Ẹ̀dà Bíbélì: <b>{version}</b>",
 "daily_toggle": "Ẹsẹ ojoojúmọ́ 07:00: {state}", "on": "Ó WÀ ✅", "off": "KÒ SÍ",
 "help_text": "📖 <b>Bí a ṣe ń lo bot yìí</b>\n\n• <b>Ẹsẹ Ọjọ́</b> — ẹsẹ tuntun lójoojúmọ́ (a fi ránṣẹ́ 07:00 bí ó bá wà ní Ètò)\n• <b>Wíwá</b> — ìtọ́kasí bíi <code>Johanu 3:16</code> tàbí ọ̀rọ̀ bíi <code>ìgbàgbọ́</code>\n• <b>Ka Orí Kan</b> — Májẹ̀mú → Ìwé → Orí, gbogbo ẹsẹ ní nọ́mbà, pẹ̀lú bọ́tìnì 🔊 Gbọ́ (ohùn KJV Gẹ̀ẹ́sì)\n• <b>Àwọn Kókó</b> — ẹsẹ fún ìrètí, ìbẹ̀rù, ìwòsàn àti sí i\n• <b>Ìwàásù</b> — kíkà ojoojúmọ́ kúkúrú 14 pẹ̀lú àdúrà\n• <b>Ìbéèrè</b> — dán ìmọ̀ Bíbélì rẹ wò, a ó pa àmì rẹ mọ́\n• <b>Ìbéèrè Àdúrà</b> — a fi ránṣẹ́ ní ìkọ̀kọ̀ sí ẹgbẹ́ ìránṣẹ́\n• <b>Èdè</b> — English, हिन्दी, Yorùbá, Français, Hausa, العربية\n• <b>Ìrànlọ́wọ́</b> — ṣe ìrànlọ́wọ́ láti jẹ́ kí bot yìí wà lọ́fẹ̀ẹ́ fún gbogbo ènìyàn\n\nÌbéèrè? Kan sí {support}",
 "support_title": "❤️ <b>Ṣe Ìrànlọ́wọ́ fún Ìránṣẹ́ Yìí</b>",
 "support_body": "Bot Bíbélì yìí jẹ́ lọ́fẹ̀ẹ́ fún gbogbo ènìyàn, ní èdè 6, pẹ̀lú ẹsẹ ojoojúmọ́, ohùn àti ìwàásù. Ṣíṣe rẹ̀ ń ná owó lóṣooṣù — ìgbàlejò, àwọn àtúnṣe, àti jíjẹ́ kí kíka àti gbígbọ́ rọ̀ dáadáa.\n\nBí bot yìí bá ti bùkún ọ, jọ̀wọ́ ṣe ìrànlọ́wọ́. Gbogbo ẹ̀bùn, kékeré tàbí ńlá, ń ran lọ́wọ́ láti mú Ọ̀rọ̀ náà dé ọ̀dọ̀ ènìyàn sí i. Ọlọ́run bùkún ọ! 🙏",
 "support_how": "💝 <b>Bí a ṣe lè ṣe ìrànlọ́wọ́</b>",
 "support_contact_default": "Jọ̀wọ́ kan sí ẹgbẹ́ ìránṣẹ́ ní {support} — wọn yóò fi ayọ̀ sọ bí ìwọ ṣe lè ṣe ìrànlọ́wọ́.",
 "support_done_btn": "✅ Mo ti ṣe ìrànlọ́wọ́",
 "support_note_prompt": "🙏 O ṣé! Bí ìwọ bá fẹ́, kọ àkọsílẹ̀ kúkúrú (bíi iye àti ọ̀nà tí o gbà) kí a lè dúpẹ́ lọ́wọ́ rẹ dáadáa — tàbí fọwọ́ kan Fò.",
 "skip": "Fò ⏭",
 "support_thanks": "❤️ <b>O ṣé fún ìrànlọ́wọ́ rẹ fún ìránṣẹ́ yìí!</b> Ẹ̀bùn rẹ ń ran lọ́wọ́ láti jẹ́ kí Bíbélì wà lọ́fẹ̀ẹ́ àti ní ìrọ̀rùn fún àwọn akàwé àti olùgbọ́ níbi gbogbo. Kí Ọlọ́run bùkún ọ lọ́pọ̀lọpọ̀. 🙏",
 "daily_tail": "Ṣí /menu fún ìwàásù àti ìbéèrè òní.",
 "not_understood": "Fi ìtọ́kasí Bíbélì ránṣẹ́ sí mi bíi <code>Johanu 3:16</code>, kókó bíi <b>ìrètí</b> tàbí <b>ìwòsàn</b>, tàbí ṣí menu:",
 "type_ref_hint": "Jọ̀wọ́ fọwọ́ kan Májẹ̀mú → Ìwé → Orí lókè, tàbí fi ìtọ́kasí kíkún ránṣẹ́ bíi <code>Saamu 23</code>.",
 "read_fail": "Má bínú, n kò lè ṣí orí náà. Gbìyànjú bíi <code>Johanu 1</code>.",
 "menu_prompt": "Lo menu tí ó wà nísàlẹ̀ láti wá Bíbélì, ka ìwàásù, ṣe ìbéèrè, tàbí fi ìbéèrè àdúrà ránṣẹ́.",
}
STR["ar"] = {
 "menu_title": "📖 <b>الكتاب المقدس</b>\n\nماذا تريد أن تفعل اليوم؟",
 "welcome": "👋 أهلاً بك، {name}!\n\n",
 "verse_day": "آية اليوم",
 "daily_btn": "📖 آية اليوم", "search_btn": "🔍 ابحث في الكتاب", "read_btn": "📚 اقرأ إصحاحاً",
 "topics_btn": "💡 مواضيع", "dev_btn": "🌅 تأملات", "quiz_btn": "❓ اختبار الكتاب",
 "prayer_btn": "🙏 طلب صلاة", "settings_btn": "⚙️ الإعدادات",
 "support_btn": "❤️ ادعمنا", "lang_btn": "🌐 اللغة",
 "back": "⬅️ القائمة الرئيسية", "choose_lang": "🌐 <b>اختر لغتك</b>\n\nكل شيء — القوائم ونص الكتاب والتأملات والاختبار — سيظهر بهذه اللغة.",
 "lang_set": "✅ تم تعيين اللغة إلى العربية.",
 "search_title": "🔍 <b>ابحث في الكتاب المقدس</b>\n\nأرسل مرجعاً مثل <code>يوحنا 3:16</code> أو <code>رومية 8</code>، أو كلمة مثل <code>إيمان</code>، <code>شفاء</code>، <code>محبة</code>.",
 "search_fail": "عذراً، لم أجد ذلك المقطع. تحقق من الكتابة، مثل <code>يوحنا 3:16</code>.",
 "no_results": "لا نتائج لـ «{q}». جرّب موضوعاً مثل <b>رجاء</b>، <b>إيمان</b> أو <b>شفاء</b>، أو مرجعاً مثل <code>يوحنا 3:16</code>.",
 "kw_note": "البحث بالكلمات يعمل بالإنجليزية والهندية والفرنسية والعربية حالياً. يمكنك كتابة أي مرجع (مثل <code>يوحنا 3:16</code>) وقراءته بلغتك.",
 "read_title": "📚 <b>اقرأ الكتاب المقدس</b>\n\nاختر العهد، ثم السفر، ثم الإصحاح — دون كتابة.\n\nيمكنك أيضاً كتابة مرجع مباشرة، مثل <code>مزمور 23</code> أو <code>يوحنا 3:16</code>.",
 "old_test": "📜 العهد القديم — 39 سفراً", "new_test": "✝️ العهد الجديد — 27 سفراً",
 "tap_book": "المس السفر الذي تريد قراءته:", "tap_chapter": "المس إصحاحاً لقراءته:",
 "chapter_word": "إصحاح", "chapters_word": "إصحاحات",
 "back_testaments": "⬅️ عودة إلى العهدين", "back_books": "⬅️ عودة إلى الأسفار", "home": "🏠 القائمة الرئيسية",
 "more_chapters_nav": "إصحاحات أكثر ▶️", "prev_chapters_nav": "◀️ الإصحاحات",
 "listen": "🔊 استمع إلى {book} {chapter}", "more_chapters": "📚 إصحاحات أخرى من هذا السفر",
 "audio_loading": "جارٍ تحميل الصوت…",
 "audio_unavail": "🔇 عذراً، الصوت غير متوفر بعد لـ{book} {chapter} — استمتع بقراءة الإصحاح أعلاه.",
 "audio_failed": "🔇 تعذّر إرسال الصوت الآن — حاول بعد قليل.",
 "audio_note": "التعليق الصوتي بالإنجليزية (KJV)",
 "chapter_fail": "عذراً، تعذّر تحميل هذا الإصحاح الآن. حاول مجدداً.",
 "topics_title": "💡 <b>آيات حسب الموضوع</b>\n\nاختر ما تحتاجه اليوم:",
 "topics_fail": "تعذّر تحميل تلك الآيات الآن — حاول مجدداً.",
 "prev_day": "◀️ اليوم السابق", "next_day": "اليوم التالي ▶️",
 "quiz_title": "❓ <b>اختبار الكتاب المقدس</b>", "correct": "✅ <b>صحيح!</b>", "wrong": "❌ ليس تماماً — الإجابة هي <b>{answer}</b>.",
 "your_score": "📊 نتيجتك: <b>{score}/{answered}</b>", "next_q": "➡️ السؤال التالي",
 "prayer_title": "🙏 <b>طلب صلاة</b>\n\nاكتب طلب صلاتك وأرسله — يصل سراً إلى فريق الخدمة وسيصلّون من أجلك. أرسل /menu للإلغاء.",
 "prayer_sent": "🙏 شكراً — تم استلام طلب صلاتك. نحن نصلّي من أجلك.\n\n<i>«صلاة البار تقتدر كثيراً في فعلها.» — يعقوب 5:16</i>",
 "settings_title": "⚙️ <b>الإعدادات</b>",
 "version_line": "📖 ترجمة الكتاب: <b>{version}</b>",
 "daily_toggle": "آية اليوم 07:00: {state}", "on": "مفعّلة ✅", "off": "معطّلة",
 "help_text": "📖 <b>كيفية استخدام هذا البوت</b>\n\n• <b>آية اليوم</b> — آية جديدة كل يوم (تُرسل 07:00 إن فعّلتها في الإعدادات)\n• <b>البحث</b> — مرجع مثل <code>يوحنا 3:16</code> أو كلمة مثل <code>إيمان</code>\n• <b>قراءة إصحاح</b> — العهد ← السفر ← الإصحاح، كل آية مرقّمة، مع زر 🔊 استماع (صوت إنجليزي KJV)\n• <b>المواضيع</b> — آيات للرجاء والخوف والشفاء وغيرها\n• <b>التأملات</b> — 14 قراءة يومية قصيرة مع صلاة\n• <b>الاختبار</b> — اختبر معرفتك، وتُحفظ نتائجك\n• <b>طلب الصلاة</b> — يُرسل سراً إلى فريق الخدمة\n• <b>اللغة</b> — English, हिन्दी, Yorùbá, Français, Hausa, العربية\n• <b>الدعم</b> — ساعد في بقاء هذا البوت مجانياً للجميع\n\nأسئلة؟ تواصل مع {support}",
 "support_title": "❤️ <b>ادعم هذه الخدمة</b>",
 "support_body": "هذا البوت مجاني للجميع، بست لغات، مع آيات يومية وصوت وتأملات. تشغيله يكلّف مالاً كل شهر — استضافة وتحديثات والحفاظ على سلاسة القراءة والاستماع.\n\nإن باركك هذا البوت، فكّر في دعمه. كل عطية، صغيرة كانت أم كبيرة، تساعد في إيصال الكلمة إلى مزيد من الناس. باركك الله! 🙏",
 "support_how": "💝 <b>كيف تدعم</b>",
 "support_contact_default": "تواصل مع فريق الخدمة على {support} وسيسعدهم إخبارك بكيفية العطاء.",
 "support_done_btn": "✅ لقد دعمت",
 "support_note_prompt": "🙏 شكراً لك! إن أردت، اكتب ملاحظة قصيرة (مثل المبلغ والطريقة) لنشكرك كما ينبغي — أو المس تخطي.",
 "skip": "تخطي ⏭",
 "support_thanks": "❤️ <b>شكراً لدعمك هذه الخدمة!</b> عطيتك تساعد في بقاء الكتاب مجانياً وسلساً للقرّاء والمستمعين في كل مكان. باركك الله بغنى. 🙏",
 "daily_tail": "افتح /menu لتأمل اليوم والاختبار.",
 "not_understood": "أرسل لي مرجعاً مثل <code>يوحنا 3:16</code>، أو موضوعاً مثل <b>رجاء</b> أو <b>شفاء</b>، أو افتح القائمة:",
 "type_ref_hint": "المس العهد ← السفر ← الإصحاح أعلاه، أو أرسل مرجعاً كاملاً مثل <code>مزمور 23</code>.",
 "read_fail": "عذراً، تعذّر تحميل ذلك الإصحاح. جرّب مثلاً <code>يوحنا 1</code>.",
 "menu_prompt": "استخدم القائمة أدناه للبحث والقراءة والتأمل والاختبار أو إرسال طلب صلاة.",
}

TOPIC_LABELS = {
 "en": {"hope":"Hope","fear":"Fear","anxiety":"Anxiety","healing":"Healing","strength":"Strength","forgiveness":"Forgiveness","love":"Love","faith":"Faith","peace":"Peace","guidance":"Guidance"},
 "fr": {"hope":"Espoir","fear":"Peur","anxiety":"Anxiété","healing":"Guérison","strength":"Force","forgiveness":"Pardon","love":"Amour","faith":"Foi","peace":"Paix","guidance":"Direction"},
 "hi": {"hope":"आशा","fear":"भय","anxiety":"चिंता","healing":"चंगाई","strength":"सामर्थ्य","forgiveness":"क्षमा","love":"प्रेम","faith":"विश्वास","peace":"शांति","guidance":"मार्गदर्शन"},
 "ha": {"hope":"Bege","fear":"Tsoro","anxiety":"Damuwa","healing":"Warkarwa","strength":"Ƙarfi","forgiveness":"Gafara","love":"Ƙauna","faith":"Bangaskiya","peace":"Salama","guidance":"Jagora"},
 "yo": {"hope":"Ìrètí","fear":"Ìbẹ̀rù","anxiety":"Àníyàn","healing":"Ìwòsàn","strength":"Agbára","forgiveness":"Ìdáríjì","love":"Ìfẹ́","faith":"Ìgbàgbọ́","peace":"Àlàáfíà","guidance":"Ìtọ́sọ́nà"},
 "ar": {"hope":"رجاء","fear":"خوف","anxiety":"قلق","healing":"شفاء","strength":"قوة","forgiveness":"غفران","love":"محبة","faith":"إيمان","peace":"سلام","guidance":"إرشاد"},
}

QUIZ_I18N = {
"fr": [
 ("Qui a construit l'arche ?", ["Noé","Moïse","Abraham","David"], 0),
 ("En combien de jours Dieu a-t-il créé le monde, avant de se reposer ?", ["6","7","5","40"], 0),
 ("Quel fut le premier fléau en Égypte ?", ["L'eau changée en sang","Les grenouilles","Les ténèbres","Les sauterelles"], 0),
 ("Qui fut avalé par un grand poisson ?", ["Jonas","Pierre","Paul","Élie"], 0),
 ("Où Jésus est-il né ?", ["Bethléem","Nazareth","Jérusalem","Égypte"], 0),
 ("Qui a vaincu Goliath ?", ["David","Saül","Samson","Salomon"], 0),
 ("Combien de disciples Jésus a-t-il choisis ?", ["12","10","7","70"], 0),
 ("Qui a renié Jésus trois fois ?", ["Pierre","Jean","Judas","Thomas"], 0),
 ("Quel est le premier livre de la Bible ?", ["Genèse","Exode","Psaumes","Matthieu"], 0),
 ("Qui a fait sortir Israël d'Égypte ?", ["Moïse","Aaron","Josué","Joseph"], 0),
 ("Quel jour Jésus est-il ressuscité ?", ["Le troisième jour","Le même jour","Après 40 jours","Le septième jour"], 0),
 ("Qui a écrit la plupart des Psaumes ?", ["David","Salomon","Asaph","Moïse"], 0),
 ("Quel fruit est cité en premier parmi les fruits de l'Esprit ?", ["L'amour","La joie","La paix","La foi"], 0),
 ("Qui fut le premier homme ?", ["Adam","Noé","Hénoc","Seth"], 0),
 ("Quel apôtre a écrit l'Apocalypse ?", ["Jean","Paul","Pierre","Jacques"], 0)],
"hi": [
 ("तौबा का जहाज़ (नौहा) किसने बनाया?", ["नूह","मूसा","अब्राहम","दाऊद"], 0),
 ("परमेश्वर ने विश्राम से पहले कितने दिनों में जगत बनाया?", ["6","7","5","40"], 0),
 ("मिस्र में पहली विपत्ति क्या थी?", ["पानी ख़ून बन गया","मेंढक","अंधकार","टिड्डियाँ"], 0),
 ("किसे एक बड़ी मछली ने निगल लिया?", ["योना","पतरस","पौलुस","एलिय्याह"], 0),
 ("यीशु कहाँ जन्मे?", ["बेतलेहेम","नासरत","येरूशलेम","मिस्र"], 0),
 ("गोलियत को किसने हराया?", ["दाऊद","शाऊल","शिमशोन","सुलैमान"], 0),
 ("यीशु ने कितने चेले चुने?", ["12","10","7","70"], 0),
 ("किसने यीशु का तीन बार इनकार किया?", ["पतरस","यूहन्ना","यहूदा","थोमा"], 0),
 ("बाइबल की पहली पुस्तक कौन-सी है?", ["उत्पत्ति","निर्गमन","भजन संहिता","मत्ती"], 0),
 ("इस्राएल को मिस्र से कौन निकाल लाया?", ["मूसा","हारून","यहोशू","यूसुफ़"], 0),
 ("यीशु किस दिन जी उठे?", ["तीसरे दिन","उसी दिन","40 दिन बाद","सातवें दिन"], 0),
 ("अधिकांश भजन किसने लिखे?", ["दाऊद","सुलैमान","आसाप","मूसा"], 0),
 ("आत्मा के फल में पहला फल कौन-सा गिनाया गया है?", ["प्रेम","आनंद","शांति","विश्वास"], 0),
 ("पहला मनुष्य कौन था?", ["आदम","नूह","हनोक","शेत"], 0),
 ("प्रकाशितवाक्य किस प्रेरित ने लिखा?", ["यूहन्ना","पौलुस","पतरस","याकूब"], 0)],
"ha": [
 ("Wa ya gina jirgin Nuhu?", ["Nuhu","Musa","Ibrahim","Dauda"], 0),
 ("Kwanaki nawa Allah ya yi halitta kafin ya huta?", ["6","7","5","40"], 0),
 ("Menene annoba ta farko a Masar?", ["Ruwa ya zama jini","Kwaɗi","Duhu","Fara"], 0),
 ("Wa babban kifi ya haɗiye?", ["Yunusa","Bitrus","Bulushi","Iliya"], 0),
 ("A ina aka haifi Yesu?", ["Baitalami","Nazaret","Urushalima","Masar"], 0),
 ("Wa ya ci Galiyat?", ["Dauda","Saul","Samson","Sulemanu"], 0),
 ("Almajirai nawa Yesu ya zaɓa?", ["12","10","7","70"], 0),
 ("Wa ya yi musun Yesu sau uku?", ["Bitrus","Yohanna","Yahuda","Toma"], 0),
 ("Menene littafi na farko a Littafi Mai Tsarki?", ["Farawa","Fitowa","Zabura","Matta"], 0),
 ("Wa ya fitar da Isra'ila daga Masar?", ["Musa","Haruna","Joshua","Yusufu"], 0),
 ("A rana ta nawa Yesu ya tashi daga matattu?", ["Rana ta uku","A ranar","Bayan kwana 40","Rana ta bakwai"], 0),
 ("Wa ya rubuta mafi yawan Zabura?", ["Dauda","Sulemanu","Asaf","Musa"], 0),
 ("Wanne 'ya'ya ne aka fara lissafa a cikin 'ya'yan Ruhu?", ["Ƙauna","Farinciki","Salama","Bangaskiya"], 0),
 ("Wa ne mutum na farko?", ["Adamu","Nuhu","Enok","Setu"], 0),
 ("Wanne manzo ya rubuta Wahayi?", ["Yohanna","Bulushi","Bitrus","Yakubu"], 0)],
"yo": [
 ("Ta ni ó kọ́ ọkọ̀ ojú omi náà?", ["Noa","Mose","Abrahamu","Dafidi"], 0),
 ("Ọjọ́ mélòó ni Ọlọ́run fi dá ayé kí ó tó sìmí?", ["6","7","5","40"], 0),
 ("Kí ni ìyọnu àkọ́kọ́ ní Ejibiti?", ["Omi di ẹ̀jẹ̀","Àwọn ọ̀pọ̀lọ́","Òkùnkùn","Ẹlẹ́ńgà"], 0),
 ("Ta ni ẹja ńlá gbé mì?", ["Jona","Peteru","Paulu","Elija"], 0),
 ("Níbo ni a bí Jesu?", ["Betlehemu","Nasareti","Jerusalem","Ejibiti"], 0),
 ("Ta ni ó ṣẹ́gun Goliati?", ["Dafidi","Saulu","Samsoni","Solomoni"], 0),
 ("Ọmọ-ẹ̀yìn mélòó ni Jesu yàn?", ["12","10","7","70"], 0),
 ("Ta ni ó sẹ́ Jesu nígbà mẹ́ta?", ["Peteru","Johanu","Judasi","Tomasi"], 0),
 ("Kí ni ìwé àkọ́kọ́ nínú Bíbélì?", ["Genesisi","Eksodu","Saamu","Matiu"], 0),
 ("Ta ni ó mú Israeli jáde ní Ejibiti?", ["Mose","Aroni","Josua","Josefu"], 0),
 ("Ọjọ́ wo ni Jesu jíǹde?", ["Ọjọ́ kẹta","Ọjọ́ náà fúnra rẹ̀","Lẹ́yìn ọjọ́ 40","Ọjọ́ keje"], 0),
 ("Ta ni ó kọ ọ̀pọ̀lọpọ̀ Saamu?", ["Dafidi","Solomoni","Asafu","Mose"], 0),
 ("Èso wo ni a kọ́kọ́ dárúkọ nínú èso Ẹ̀mí?", ["Ìfẹ́","Ayọ̀","Àlàáfíà","Ìgbàgbọ́"], 0),
 ("Ta ni ọkùnrin àkọ́kọ́?", ["Adamu","Noa","Enoku","Seti"], 0),
 ("Àpọ́sítélì wo ni ó kọ Ìfihàn?", ["Johanu","Paulu","Peteru","Jakọbu"], 0)],
"ar": [
 ("من بنى الفلك؟", ["نوح","موسى","إبراهيم","داود"], 0),
 ("في كم يوم خلق الله العالم قبل أن يستريح؟", ["6","7","5","40"], 0),
 ("ما هي الضربة الأولى في مصر؟", ["تحوّل الماء إلى دم","الضفادع","الظلمة","الجراد"], 0),
 ("من ابتلعه حوت عظيم؟", ["يونان","بطرس","بولس","إيليا"], 0),
 ("أين وُلد يسوع؟", ["بيت لحم","الناصرة","أورشليم","مصر"], 0),
 ("من هزم جليات؟", ["داود","شاول","شمشون","سليمان"], 0),
 ("كم تلميذاً اختار يسوع؟", ["12","10","7","70"], 0),
 ("من أنكر يسوع ثلاث مرات؟", ["بطرس","يوحنا","يهوذا","توما"], 0),
 ("ما هو أول سفر في الكتاب المقدس؟", ["التكوين","الخروج","المزامير","متى"], 0),
 ("من أخرج إسرائيل من مصر؟", ["موسى","هارون","يشوع","يوسف"], 0),
 ("في أي يوم قام يسوع؟", ["اليوم الثالث","اليوم نفسه","بعد 40 يوماً","اليوم السابع"], 0),
 ("من كتب معظم المزامير؟", ["داود","سليمان","آساف","موسى"], 0),
 ("ما أول ثمرة تُذكر من ثمار الروح؟", ["المحبة","الفرح","السلام","الإيمان"], 0),
 ("من هو أول إنسان؟", ["آدم","نوح","أخنوخ","شيث"], 0),
 ("أي رسول كتب سفر الرؤيا؟", ["يوحنا","بولس","بطرس","يعقوب"], 0)],
}
def quiz_for(lang): return QUIZ_I18N.get(lang, QUIZ)

DEV_I18N = {
"fr": [
 ("Jour 1 — Dieu est avec vous","Isaiah 41:10","La peur parle fort, mais elle ne commande pas. Dieu ne promet pas d'enlever toute tempête — Il promet Sa présence au milieu d'elle. Nommez ce que vous craignez, puis dites le verset à voix haute.","Seigneur, Tu es avec moi. Fortifie mon cœur aujourd'hui. Amen."),
 ("Jour 2 — Faites confiance au chemin","Proverbs 3:5-6","Votre intelligence voit un pas ; Dieu voit toute la route. Faire confiance, ce n'est pas tout comprendre — c'est s'appuyer sur Celui qui comprend tout.","Père, je m'appuie sur Toi, non sur mon intelligence. Dirige mes pas. Amen."),
 ("Jour 3 — Repos pour les fatigués","Matthew 11:28","Jésus invite les fatigués, pas les parfaits. Le poids que vous portez aujourd'hui, vous n'étiez jamais censé le porter seul.","Jésus, je viens à Toi. Donne le repos à mon âme. Amen."),
 ("Jour 4 — La force dans l'attente","Isaiah 40:31","Attendre n'est pas du temps perdu entre les mains de Dieu. L'aigle ne bat pas des ailes au-dessus de la tempête — il monte sur le vent que Dieu donne.","Seigneur, renouvelle ma force pendant que je T'attends. Amen."),
 ("Jour 5 — Le soin du Berger","Psalm 23:1","Une brebis qui a un berger n'a pas à résoudre demain. La confiance de David n'était pas dans ses provisions, mais dans son Berger.","Seigneur, Tu es mon Berger. Je ne manque de rien. Amen."),
 ("Jour 6 — La grâce suffit","Ephesians 2:8","Le salut est un don, pas un salaire. Vous ne pouvez ni gagner plus d'amour de Dieu aujourd'hui, ni le perdre par un mauvais hier.","Merci, Père, pour une grâce que je n'ai pas méritée. Amen."),
 ("Jour 7 — Un esprit sain","2 Timothy 1:7","Dieu vous a donné force, amour et un esprit sain — non la peur. Quand les pensées anxieuses se répètent, répondez par ce que Dieu a vraiment donné.","Saint-Esprit, remplis-moi de force, d'amour et d'un esprit sain. Amen."),
 ("Jour 8 — Cherchez d'abord","Matthew 6:33","Mettez le royaume de Dieu en premier, et l'anxiété lâche le reste. Ordonnez vos amours, et Dieu ordonne votre vie.","Père, Ton royaume d'abord — tout le reste à sa place. Amen."),
 ("Jour 9 — Grande est Ta fidélité","Lamentations 3:22-23","Jérémie a écrit ceci depuis des ruines — la fidélité se prouve dans les lieux durs. Les compassions de Dieu sont nouvelles ce matin, pas recyclées.","Seigneur, grande est Ta fidélité. Tes compassions m'ont accueilli ce matin. Amen."),
 ("Jour 10 — Déchargez-vous sur Lui","1 Peter 5:7","Se décharger est un acte : jetez le souci sur Dieu, exprès, chaque fois qu'il revient. Il se soucie de vous — voilà la raison donnée.","Seigneur, je Te remets ce souci, car Tu prends soin de moi. Amen."),
 ("Jour 11 — Le Dieu de l'espérance","Romans 15:13","L'espérance n'est pas l'optimisme ; c'est une Personne qui vous remplit. Joie et paix grandissent dans la foi, pas dans des circonstances parfaites.","Dieu de l'espérance, remplis-moi de joie et de paix dans la foi. Amen."),
 ("Jour 12 — Sois fort et courageux","Joshua 1:9","Dieu a commandé le courage à un homme face à une mission impossible — parce que le courage repose sur « Je serai avec toi », pas sur les probabilités.","Seigneur, je serai fort et courageux, car Tu es avec moi. Amen."),
 ("Jour 13 — Pensée renouvelée","Romans 12:2","Le monde vous presse dans son moule ; la Parole renouvelle votre intelligence. Ce que vous méditez, vous le devenez.","Père, renouvelle mon intelligence par Ta Parole aujourd'hui. Amen."),
 ("Jour 14 — Viens, Seigneur Jésus","Revelation 22:20","La Bible se termine par une promesse et une prière : Il vient, et Son peuple dit « Viens ». Vivez prêt, plein d'espérance, saint.","Viens, Seigneur Jésus. Amen.")],
"hi": [
 ("दिन 1 — परमेश्वर आपके साथ है","Isaiah 41:10","भय ऊँची आवाज़ करता है, पर हुकूमत नहीं करता। परमेश्वर हर तूफ़ान हटाने का वादा नहीं करता — वह तूफ़ान के बीच अपनी उपस्थिति का वादा करता है। आज जिस बात से डरते हैं उसे नाम दें, फिर यह वचन ज़ोर से कहें।","प्रभु, आप मेरे साथ हैं। आज मेरा हृदय मज़बूत करें। आमीन।"),
 ("दिन 2 — मार्ग पर भरोसा करें","Proverbs 3:5-6","आपकी समझ एक कदम देखती है; परमेश्वर पूरी सड़क देखता है। भरोसा सब उत्तर जानना नहीं — उस पर झुकना है जो सब जानता है।","पिता, मैं आप पर झुकता हूँ, अपनी समझ पर नहीं। मेरे मार्ग की अगुवाई करें। आमीन।"),
 ("दिन 3 — थकों के लिए विश्राम","Matthew 11:28","यीशु थके हुओं को बुलाते हैं, सिद्धों को नहीं। जो बोझ आप आज ढो रहे हैं, वह आपको अकेले ढोना ही नहीं था।","यीशु, मैं आपके पास आता हूँ। मेरी आत्मा को विश्राम दें। आमीन।"),
 ("दिन 4 — प्रतीक्षा में सामर्थ्य","Isaiah 40:31","परमेश्वर के हाथों में प्रतीक्षा व्यर्थ समय नहीं। उकाब तूफ़ान के ऊपर पंख नहीं फड़फड़ाता — वह परमेश्वर की दी हवा पर चढ़ता है।","प्रभु, जब मैं आपकी बाट जोहता हूँ, मेरी सामर्थ्य नई करें। आमीन।"),
 ("दिन 5 — चरवाहे की देखभाल","Psalm 23:1","जिस भेड़ का चरवाहा है उसे कल की चिंता नहीं सुलझानी। दाऊद का भरोसा उसके सामान पर नहीं, उसके चरवाहे पर था।","प्रभु, आप मेरे चरवाहे हैं। मुझे कोई घटी नहीं होगी। आमीन।"),
 ("दिन 6 — अनुग्रह ही पर्याप्त","Ephesians 2:8","उद्धार उपहार है, मज़दूरी नहीं। आप आज परमेश्वर का और प्रेम नहीं कमा सकते — और न बुरे कल से उसे खो सकते हैं।","धन्यवाद पिता, उस अनुग्रह के लिए जो मैंने नहीं कमाया। आमीन।"),
 ("दिन 7 — स्वस्थ मन","2 Timothy 1:7","परमेश्वर ने आपको सामर्थ्य, प्रेम और स्वस्थ मन दिया है — भय नहीं। जब चिंता के विचार दोहराएँ, उन्हें वही उत्तर दें जो परमेश्वर ने सच में दिया।","पवित्र आत्मा, मुझे सामर्थ्य, प्रेम और स्वस्थ मन से भर दें। आमीन।"),
 ("दिन 8 — पहले खोजें","Matthew 6:33","परमेश्वर के राज्य को पहले रखें और चिंता बाकी सब छोड़ देगी। अपने प्रेमों को क्रम दें, परमेश्वर आपके जीवन को क्रम देगा।","पिता, आपका राज्य पहले — बाकी सब अपने स्थान पर। आमीन।"),
 ("दिन 9 — तेरी सच्चाई महान है","Lamentations 3:22-23","यिर्मयाह ने यह खंडहरों से लिखा — सच्चाई कठिन स्थानों में सिद्ध होती है। परमेश्वर की करुणा आज सुबह नई है, पुरानी नहीं।","प्रभु, आपकी सच्चाई महान है। आपकी करुणा आज सुबह मुझसे मिली। आमीन।"),
 ("दिन 10 — अपनी चिंता डालें","1 Peter 5:7","डालना एक काम है: चिंता को जानबूझकर परमेश्वर पर फेंकें, हर बार जब वह लौटे। वह आपकी चिंता करता है — यही कारण दिया गया है।","प्रभु, मैं यह चिंता आप पर डालता हूँ, क्योंकि आप मेरी चिंता करते हैं। आमीन।"),
 ("दिन 11 — आशा का परमेश्वर","Romans 15:13","आशा आशावाद नहीं; वह एक व्यक्ति है जो आपको भरता है। आनंद और शांति विश्वास में बढ़ते हैं, सिद्ध परिस्थितियों में नहीं।","आशा के परमेश्वर, मुझे विश्वास में सारे आनंद और शांति से भर दें। आमीन।"),
 ("दिन 12 — मज़बूत और साहसी बनें","Joshua 1:9","परमेश्वर ने असंभव काम का सामना कर रहे मनुष्य को साहस की आज्ञा दी — क्योंकि साहस 'मैं तेरे साथ रहूँगा' पर टिका है, संभावनाओं पर नहीं।","प्रभु, मैं मज़बूत और साहसी रहूँगा, क्योंकि आप मेरे साथ हैं। आमीन।"),
 ("दिन 13 — नवीनीकृत सोच","Romans 12:2","जगत आपको अपने साँचे में दबाता है; वचन आपके मन को नया करता है। जिसका आप मनन करते हैं, वही आप बनते हैं।","पिता, आज अपने वचन से मेरे मन को नया करें। आमीन।"),
 ("दिन 14 — हे प्रभु यीशु, आ","Revelation 22:20","बाइबल एक वादे और एक प्रार्थना के साथ समाप्त होती है: वह आ रहा है, और उसके लोग कहते हैं 'आ'। तैयार, आशावान और पवित्र जीवन जीएँ।","हे प्रभु यीशु, आ। आमीन।")],
"ha": [
 ("Rana 1 — Allah Yana Tare Da Kai","Isaiah 41:10","Tsoro yana da ƙara, amma ba shi da iko. Allah ba ya yin alkawarin kawar da kowace hadari — yana alkawarin kasancewarsa a cikinta. Yau, ambaci abin da kake tsoro, sai ka faɗi ayar da babbar murya.","Ubangiji, kana tare da ni. Ka ƙarfafa zuciyata yau. Amin."),
 ("Rana 2 — Dogara ga Hanya","Proverbs 3:5-6","Fahimtarka tana ganin mataki ɗaya; Allah yana ganin dukan hanya. Dogara ba shi ne sanin dukan amsoshi ba — jingina ne ga wanda ya san su.","Uba, na jingina gare ka, ba ga fahimtata ba. Ka ja-goranci hanyata. Amin."),
 ("Rana 3 — Hutu ga Waɗanda Suka Gajiya","Matthew 11:28","Yesu yana gayyatar waɗanda suka gajiya, ba cikakku ba. Nauyin da kake ɗauka yau, ba a nufi ka ɗauke shi kai kaɗai ba.","Yesu, na zo gare ka. Ka ba raina hutu. Amin."),
 ("Rana 4 — Ƙarfi Yayin Jira","Isaiah 40:31","Jira ba lokacin ɓata ba ne a hannun Allah. Gaggafa ba ta bugun fuka-fuki a kan hadari — tana hawan iskar da Allah ya bayar.","Ubangiji, ka sabunta ƙarfina yayin da nake jiranka. Amin."),
 ("Rana 5 — Kulawar Makiyayi","Psalm 23:1","Tumakin da ke da makiyayi ba sai ya damu da gobe ba. Amincewar Dauda ba ta cikin kayansa ba ce, ta cikin Makiyayinsa ce.","Ubangiji, kai ne Makiyayina. Ba zan rasa kome ba. Amin."),
 ("Rana 6 — Alheri Ya Isa","Ephesians 2:8","Ceto kyauta ne, ba lada ba. Ba za ka iya samun ƙarin ƙaunar Allah yau ba — kuma ba za ka rasa ta saboda munin jiya ba.","Na gode, Uba, domin alherin da ban cancanta ba. Amin."),
 ("Rana 7 — Hankali Lafiyayye","2 Timothy 1:7","Allah ya ba ka iko, ƙauna da hankali lafiyayye — ba tsoro ba. Idan tunanin damuwa suka maimaitu, amsa musu da abin da Allah ya bayar da gaske.","Ruhu Mai Tsarki, ka cika ni da iko, ƙauna da hankali lafiyayye. Amin."),
 ("Rana 8 — Nemi Farko","Matthew 6:33","Ka sa Mulkin Allah a farko, damuwa za ta saki sauran. Ka tsara abubuwan da kake ƙauna, Allah zai tsara rayuwarka.","Uba, Mulkin ka a farko — komai a wurinsa. Amin."),
 ("Rana 9 — Amincinka Mai Girma Ne","Lamentations 3:22-23","Irmiya ya rubuta wannan daga rusassun gine-gine — aminci yana tabbata a wurare masu wuya. Jinƙan Allah sabo ne a wannan safe, ba tsoho ba.","Ubangiji, amincinka mai girma ne. Jinƙanka sun haɗu da ni a wannan safe. Amin."),
 ("Rana 10 — Jefa Damuwarka","1 Peter 5:7","Jefawa aiki ne: jefa damuwar ga Allah da gangan, duk lokacin da ta dawo. Yana lura da kai — shi ne dalilin da aka bayar.","Ubangiji, na jefa wannan damuwa gare ka, domin kana lura da ni. Amin."),
 ("Rana 11 — Allah na Bege","Romans 15:13","Bege ba kyakkyawan fata ba ne; Mutum ne da yake cika ka. Farinciki da salama suna girma cikin bangaskiya, ba cikin cikakken yanayi ba.","Allah na bege, ka cika ni da farinciki da salama cikin bangaskiya. Amin."),
 ("Rana 12 — Ka Yi Ƙarfi da Juriya","Joshua 1:9","Allah ya umarci mutumin da ke fuskantar aiki marar yiwuwa da ya yi ƙarfi — domin ƙarfi yana dogara ga 'Zan kasance tare da kai', ba ga yiwuwa ba.","Ubangiji, zan yi ƙarfi da juriya, domin kana tare da ni. Amin."),
 ("Rana 13 — Sabuntawar Tunani","Romans 12:2","Duniya tana matsa ka cikin sifarta; Magana tana sabunta ranka daga ciki. Abin da kake tunani a kai, shi za ka zama.","Uba, ka sabunta raina da Maganarka yau. Amin."),
 ("Rana 14 — Zo, Ubangiji Yesu","Revelation 22:20","Littafi ya ƙare da alkawari da addu'a: Yana zuwa, mutanensa kuma suna cewa 'Zo'. Ka rayu cikin shiri, bege da tsarki.","Zo, Ubangiji Yesu. Amin.")],
"yo": [
 ("Ọjọ́ 1 — Ọlọ́run Wà Pẹ̀lú Rẹ","Isaiah 41:10","Ìbẹ̀rù ń pariwo, ṣùgbọ́n kò ní agbára ìjọba. Ọlọ́run kò ṣèlérí láti mú gbogbo ìjì kúrò — Ó ṣèlérí wíwà Rẹ̀ nínú rẹ̀. Lónìí, dárúkọ ohun tí ìwọ ń bẹ̀rù, kí o sì sọ ẹsẹ náà sókè.","Olúwa, Ìwọ wà pẹ̀lú mi. Mú ọkàn mi lágbára lónìí. Àmín."),
 ("Ọjọ́ 2 — Gbẹ́kẹ̀lé Ọ̀nà Náà","Proverbs 3:5-6","Òye rẹ ń rí ìgbésẹ̀ kan; Ọlọ́run ń rí gbogbo ọ̀nà. Ìgbẹ́kẹ̀lé kì í ṣe níní gbogbo ìdáhùn — ó jẹ́ títẹ̀ sí Ẹni tí Ó ní wọn.","Baba, mo tẹ̀ sí Ọ, kì í ṣe sí òye mi. Tọ́ ọ̀nà mi. Àmín."),
 ("Ọjọ́ 3 — Ìsìmí fún Aláàrẹ̀","Matthew 11:28","Jesu ń pe aláàrẹ̀, kì í ṣe ẹni pípé. Ẹrù tí ìwọ ń rù lónìí, a kò pinnu pé kí ìwọ nìkan rù ú.","Jesu, mo wá sọ́dọ̀ Rẹ. Fún ọkàn mi ní ìsìmí. Àmín."),
 ("Ọjọ́ 4 — Agbára Nígbà Ìdúró","Isaiah 40:31","Ìdúró kì í ṣe àkókò tí ó ṣòfò ní ọwọ́ Ọlọ́run. Idì kì í lù ìyẹ́ rẹ̀ lókè ìjì — ó ń gun afẹ́fẹ́ tí Ọlọ́run pèsè.","Olúwa, tún agbára mi ṣe bí mo ṣe ń dúró dè Ọ́. Àmín."),
 ("Ọjọ́ 5 — Ìtọ́jú Olùṣọ́-àgùntàn","Psalm 23:1","Àgùntàn tí ó ní olùṣọ́ kò nílò láti yanjú ọ̀la. Ìgbẹ́kẹ̀lé Dafidi kò sí nínú ohun ìní rẹ̀, ó wà nínú Olùṣọ́ rẹ̀.","Olúwa, Ìwọ ni Olùṣọ́-àgùntàn mi. N kò ní ṣàìní. Àmín."),
 ("Ọjọ́ 6 — Oore-ọ̀fẹ́ Tó","Ephesians 2:8","Ìgbàlà jẹ́ ẹ̀bùn, kì í ṣe owó iṣẹ́. Ìwọ kò lè rí ìfẹ́ Ọlọ́run sí i lónìí — bẹ́ẹ̀ ni ìwọ kò lè pàdánù rẹ̀ nítorí àná tí kò dára.","O ṣé, Baba, fún oore-ọ̀fẹ́ tí n kò rí gbà nípa iṣẹ́. Àmín."),
 ("Ọjọ́ 7 — Ọkàn Tí Ó Dára","2 Timothy 1:7","Ọlọ́run fún ọ ní agbára, ìfẹ́ àti ọkàn tí ó dára — kì í ṣe ìbẹ̀rù. Nígbà tí èrò àníyàn bá ń padà wá, fi ohun tí Ọlọ́run fún ọ gan-an dáhùn.","Ẹ̀mí Mímọ́, fi agbára, ìfẹ́ àti ọkàn tí ó dára kún mi. Àmín."),
 ("Ọjọ́ 8 — Wá Ìjọba Rẹ̀ Kọ́kọ́","Matthew 6:33","Fi ìjọba Ọlọ́run sí ipò àkọ́kọ́, àníyàn yóò sì tú ìyókù sílẹ̀. Tò àwọn ìfẹ́ rẹ, Ọlọ́run yóò sì to ìgbésí ayé rẹ.","Baba, ìjọba Rẹ kọ́kọ́ — gbogbo ohun ìyókù ní ipò wọn. Àmín."),
 ("Ọjọ́ 9 — Ńlá ni Òtítọ́ Rẹ","Lamentations 3:22-23","Jeremaya kọ èyí láti inú ahoro — òtítọ́ ni a ń dán wò ní ibì líle. Àánú Ọlọ́run jẹ́ tuntun ní òwúrọ̀ yìí, kì í ṣe àtijọ́.","Olúwa, ńlá ni òtítọ́ Rẹ. Àánú Rẹ bá mi ní òwúrọ̀ yìí. Àmín."),
 ("Ọjọ́ 10 — Ju Àníyàn Rẹ Lé E","1 Peter 5:7","Jíjù jẹ́ ìṣe: ju àníyàn náà lé Ọlọ́run, ní ète, nígbà gbogbo tí ó bá padà. Ó bìkítà fún ọ — ìdí tí a fún ni nìyí.","Olúwa, mo ju àníyàn yìí lé Ọ, nítorí Ìwọ bìkítà fún mi. Àmín."),
 ("Ọjọ́ 11 — Ọlọ́run Ìrètí","Romans 15:13","Ìrètí kì í ṣe ìrètí lásán; Ẹ̀dá ni tí ó ń kún ọ. Ayọ̀ àti àlàáfíà ń dàgbà nínú ìgbàgbọ́, kì í ṣe nínú ipò pípé.","Ọlọ́run ìrètí, fi gbogbo ayọ̀ àti àlàáfíà nínú ìgbàgbọ́ kún mi. Àmín."),
 ("Ọjọ́ 12 — Jẹ́ Alágbára Kí O Sì Gbóya","Joshua 1:9","Ọlọ́run pàṣẹ ìgbóya fún ọkùnrin tí ó dojúkọ iṣẹ́ tí kò ṣeé ṣe — nítorí ìgbóya dúró lórí 'Èmi ó wà pẹ̀lú rẹ', kì í ṣe lórí ìṣeéṣe.","Olúwa, èmi ó lágbára, èmi ó sì gbóya, nítorí Ìwọ wà pẹ̀lú mi. Àmín."),
 ("Ọjọ́ 13 — Èrò Tí A Tún Ṣe","Romans 12:2","Ayé ń tẹ ọ́ sínú àpẹẹrẹ rẹ̀; Ọ̀rọ̀ náà ń tún ọkàn rẹ ṣe. Ohun tí ìwọ bá ń ronú lé lórí, ìwọ ni ìwọ ó di.","Baba, tún ọkàn mi ṣe nípa Ọ̀rọ̀ Rẹ lónìí. Àmín."),
 ("Ọjọ́ 14 — Wá, Jesu Olúwa","Revelation 22:20","Bíbélì parí pẹ̀lú ìlérí àti àdúrà: Ó ń bọ̀, àwọn ènìyàn Rẹ̀ sì ń sọ pé 'Wá'. Gbé ìgbé ayé ìmúrasílẹ̀, ìrètí àti ìwà mímọ́.","Wá, Jesu Olúwa. Àmín.")],
"ar": [
 ("اليوم 1 — الله معك","Isaiah 41:10","الخوف صوته عالٍ لكنه لا يحكم. الله لا يعد بإزالة كل عاصفة — بل يعد بحضوره في وسطها. اليوم سمِّ ما تخافه، ثم قل الآية بصوت عالٍ.","يا رب، أنت معي. شدّد قلبي اليوم. آمين."),
 ("اليوم 2 — ثق بالطريق","Proverbs 3:5-6","فهمك يرى خطوة واحدة؛ الله يرى الطريق كله. الثقة ليست أن تعرف كل الإجابات — بل أن تتكل على من يعرفها.","يا أبي، أتكل عليك لا على فهمي. اهدِ طريقي. آمين."),
 ("اليوم 3 — راحة للمتعبين","Matthew 11:28","يسوع يدعو المتعبين لا الكاملين. الحمل الذي تحمله اليوم لم يكن مقصوداً أن تحمله وحدك.","يا يسوع، آتي إليك. أرح نفسي. آمين."),
 ("اليوم 4 — قوة أثناء الانتظار","Isaiah 40:31","الانتظار ليس وقتاً ضائعاً في يد الله. النسر لا يخفق بجناحيه فوق العاصفة — بل يرتفع على الريح التي يعطيها الله.","يا رب، جدّد قوتي أثناء انتظاري لك. آمين."),
 ("اليوم 5 — عناية الراعي","Psalm 23:1","الخروف الذي له راعٍ لا يحتاج أن يحلّ مشكلة الغد. ثقة داود لم تكن في مؤونته بل في راعيه.","يا رب، أنت راعيّ. لا يعوزني شيء. آمين."),
 ("اليوم 6 — النعمة تكفي","Ephesians 2:8","الخلاص عطية لا أجرة. لا تستطيع أن تكسب محبة أكثر من الله اليوم — ولا أن تخسرها بسبب أمسٍ سيئ.","شكراً يا أبي، لأجل نعمة لم أستحقها. آمين."),
 ("اليوم 7 — ذهن سليم","2 Timothy 1:7","أعطاك الله قوة ومحبة وذهناً سليماً — لا خوفاً. حين تتكرر أفكار القلق، أجبها بما أعطاه الله فعلاً.","أيها الروح القدس، املأني قوة ومحبة وذهناً سليماً. آمين."),
 ("اليوم 8 — اطلبوا أولاً","Matthew 6:33","ضع ملكوت الله أولاً، فيفقد القلق قبضته على الباقي. رتّب محباتك، والله يرتّب حياتك.","يا أبي، ملكوتك أولاً — وكل شيء آخر في مكانه. آمين."),
 ("اليوم 9 — عظيم أمانتك","Lamentations 3:22-23","كتب إرميا هذا من وسط الخراب — الأمانة تُثبَت في الأماكن الصعبة. مراحم الله جديدة هذا الصباح، ليست معادة.","يا رب، عظيمة أمانتك. مراحمك قابلتني هذا الصباح. آمين."),
 ("اليوم 10 — ألقِ همك عليه","1 Peter 5:7","الإلقاء فعل: ارمِ الهم على الله، عن قصد، كلما عاد. إنه يعتني بك — هذا هو السبب المعطى.","يا رب، ألقي هذا الهم عليك، لأنك تعتني بي. آمين."),
 ("اليوم 11 — إله الرجاء","Romans 15:13","الرجاء ليس تفاؤلاً؛ بل شخص يملأك. الفرح والسلام ينموان في الإيمان، لا في الظروف الكاملة.","يا إله الرجاء، املأني كل فرح وسلام في الإيمان. آمين."),
 ("اليوم 12 — كن قوياً وشجاعاً","Joshua 1:9","أمر الله بالشجاعة رجلاً يواجه مهمة مستحيلة — لأن الشجاعة تستند إلى «أكون معك»، لا إلى الاحتمالات.","يا رب، سأكون قوياً وشجاعاً، لأنك معي. آمين."),
 ("اليوم 13 — ذهن متجدد","Romans 12:2","العالم يضغطك في قالبه؛ والكلمة تجدد ذهنك. ما تتأمل فيه، تصيره.","يا أبي، جدّد ذهني بكلمتك اليوم. آمين."),
 ("اليوم 14 — تعال أيها الرب يسوع","Revelation 22:20","ينتهي الكتاب بوعد وصلاة: إنه آتٍ، وشعبه يقول «تعال». عش مستعداً، ممتلئ رجاءً، مقدساً.","تعال أيها الرب يسوع. آمين.")],
}
def dev_for(lang): return DEV_I18N.get(lang, DEVOTIONALS)

SUPPORT_LINK = os.getenv("SUPPORT_LINK", "").strip()     # e.g. a Paystack/Flutterwave payment link
SUPPORT_DETAILS = os.getenv("SUPPORT_DETAILS", "").strip()  # e.g. bank name + account number, shown on the Support screen

# ---------------------------------------------------------------- multilingual Bible fetch
def normalize_book(name: str):
    n = " ".join((name or "").split()); low = n.lower()
    for b in BOOKS:
        if b.lower() == low: return b
    return {"psalm": "Psalms", "song of songs": "Song of Solomon", "canticles": "Song of Solomon",
            "apocalypse": "Revelation", "psalms": "Psalms"}.get(low)

_bolls_names = {}
async def bolls_book_names(code: str) -> list:
    if code in _bolls_names: return _bolls_names[code]
    names = []
    try:
        s = await http()
        async with s.get(f"https://bolls.life/get-books/{code}/") as r:
            if r.status == 200:
                rows = await r.json()
                names = [row.get("name", "") for row in sorted(rows, key=lambda x: x.get("bookid", 0))]
    except Exception as e: log.warning("bolls books failed: %s", e)
    if len(names) == 66: _bolls_names[code] = names
    return names

async def book_display(lang: str, book: str) -> str:
    code = LANGS.get(lang, {}).get("bolls")
    if code:
        names = await bolls_book_names(code)
        if len(names) == 66: return names[BOOKS.index(book)]
    return book

def _clean_bolls(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").replace("\n", " ").strip()

async def chapter_verses(book: str, chapter: int, lang: str):
    """Return [(verse_no, text), ...] for a whole chapter in the user's language, or None."""
    cfg = LANGS.get(lang, LANGS["en"]); num = BOOKS.index(book) + 1
    try:
        s = await http()
        if lang == "en":
            async with s.get(f"https://bible-api.com/{book.replace(' ', '+')}+{chapter}?translation=kjv") as r:
                if r.status != 200: return None
                d = await r.json()
                return [(v.get("verse"), v["text"].strip()) for v in d.get("verses", []) if v.get("text")] or None
        if cfg.get("bolls"):
            async with s.get(f"https://bolls.life/get-text/{cfg['bolls']}/{num}/{chapter}/") as r:
                if r.status != 200: return None
                rows = await r.json()
                return [(row.get("verse"), _clean_bolls(row.get("text", ""))) for row in rows if row.get("text")] or None
        if cfg.get("wbem"):
            slug = book.lower().replace(" ", "")
            async with s.get(f"https://apibible.wbem.org/api/bibles/{cfg['wbem']}/{slug}/{int(chapter) + cfg.get('shift', 0)}") as r:
                if r.status != 200: return None
                d = await r.json()
                if "verses" not in d: return None
                return [(i + 1, v.strip()) for i, v in enumerate(d["verses"]) if v and v.strip()] or None
    except Exception as e:
        log.warning("chapter fetch failed (%s %s %s): %s", lang, book, chapter, e); return None
    return None

def _format_verses(book_disp: str, chapter: int, verses, lang: str, v_from=None, v_to=None) -> str:
    sel = [(n, t) for (n, t) in verses if (v_from is None or n >= v_from) and (v_to is None or n <= v_to)]
    if not sel: return None
    ref = f"{book_disp} {chapter}" + ("" if v_from is None else (f":{v_from}" if (v_to is None or v_to == v_from) else f":{v_from}-{v_to}"))
    body = " ".join(f"<b>{n}</b> {html.escape(t)}" for (n, t) in sel)
    return f"📖 <b>{html.escape(ref)}</b> ({html.escape(LANGS[lang]['version'])})\n\n{body}"

async def fetch_chapter_text(book: str, chapter: int, lang: str):
    verses = await chapter_verses(book, int(chapter), lang)
    if not verses: return None
    return _format_verses(await book_display(lang, book), int(chapter), verses, lang)

async def fetch_any(ref: str, lang: str):
    """Fetch any typed reference ('John 3:16', 'Psalms 23', '1 John 1:9') in the user's language."""
    if lang == "en": return await fetch_reference(ref, "kjv")
    mm = REF_RE.match(ref or "")
    if not mm: return None
    book = normalize_book(mm.group(1))
    if not book: return None
    chapter = int(mm.group(2)); v1 = int(mm.group(3)) if mm.group(3) else None; v2 = int(mm.group(4)) if mm.group(4) else v1
    verses = await chapter_verses(book, chapter, lang)
    if not verses: return None
    return _format_verses(await book_display(lang, book), chapter, verses, lang, v1, v2)

async def keyword_search_lang(query: str, lang: str, limit: int = 5) -> list:
    code = {"en": "KJV", "fr": "FRLSG", "ar": "SVD", "hi": "HIOV"}.get(lang)
    if not code: return []
    s = await http()
    try:
        async with s.get(f"https://bolls.life/v2/find/{code}", params={"search": query}) as r:
            if r.status != 200: return []
            d = await r.json()
            rows = d.get("results", []) if isinstance(d, dict) else []
            names = await bolls_book_names(code)
            out = []
            for row in rows:
                bnum = row.get("book") or 0
                if not (1 <= bnum <= 66): continue  # skip apocrypha hits
                txt = re.sub("<[^>]+>", "", row.get("text", "")).strip()
                if not txt: continue
                bname = names[bnum - 1] if len(names) == 66 else BOOKS[bnum - 1]
                out.append(f"📖 <b>{html.escape(bname)} {row.get('chapter','')}:{row.get('verse','')}</b>\n{html.escape(txt)}")
                if len(out) >= limit: break
            return out
    except Exception as e:
        log.warning("bolls search failed: %s", e); return []

# ---------------------------------------------------------------- FSM / keyboards
class Form(StatesGroup):
    search = State(); prayer = State(); read_ref = State()
    broadcast = State(); devotional = State(); support_note = State()

def main_menu(lang: str = "en"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=T(lang, "daily_btn"), callback_data="m:daily"),
         InlineKeyboardButton(text=T(lang, "search_btn"), callback_data="m:search")],
        [InlineKeyboardButton(text=T(lang, "read_btn"), callback_data="m:read"),
         InlineKeyboardButton(text=T(lang, "topics_btn"), callback_data="m:topics")],
        [InlineKeyboardButton(text=T(lang, "dev_btn"), callback_data="m:dev"),
         InlineKeyboardButton(text=T(lang, "quiz_btn"), callback_data="m:quiz")],
        [InlineKeyboardButton(text=T(lang, "prayer_btn"), callback_data="m:prayer"),
         InlineKeyboardButton(text=T(lang, "settings_btn"), callback_data="m:settings")],
        [InlineKeyboardButton(text=T(lang, "support_btn"), callback_data="m:support"),
         InlineKeyboardButton(text=T(lang, "lang_btn"), callback_data="m:lang")],
    ])

def back_menu(lang: str = "en"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")]])

def language_keyboard():
    rows = [[InlineKeyboardButton(text=LANGS[c]["native"], callback_data=f"lang:set:{c}")] for c in LANG_ORDER]
    return InlineKeyboardMarkup(inline_keyboard=rows)

router = Router()

async def show_menu(target, lang: str = "en"):
    text = T(lang, "menu_title")
    if isinstance(target, Message): await target.answer(text, reply_markup=main_menu(lang))
    else:
        try: await target.message.edit_text(text, reply_markup=main_menu(lang))
        except Exception: await target.message.answer(text, reply_markup=main_menu(lang))
        await target.answer()

@router.message(CommandStart())
async def on_start(m: Message, state: FSMContext):
    await state.clear(); upsert_user(m.from_user)
    if needs_lang_choice(m.from_user.id):
        await m.answer(f"👋 Welcome, {html.escape(m.from_user.first_name or 'friend')}!\n\n" + T("en", "choose_lang"),
                       reply_markup=language_keyboard()); return
    lang = get_lang(m.from_user.id)
    ref, txt = daily_verse()
    if lang != "en":
        got = await fetch_any(ref, lang)
        verse_block = got or f"🌅 <b>{T(lang, 'verse_day')} — {html.escape(ref)}</b>\n{html.escape(txt)}"
    else:
        verse_block = f"🌅 <b>{T(lang, 'verse_day')} — {html.escape(ref)}</b>\n{html.escape(txt)}"
    await m.answer(T(lang, "welcome", name=html.escape(m.from_user.first_name or "friend")) + verse_block + "\n\n" + T(lang, "menu_prompt"),
                   reply_markup=main_menu(lang))

@router.message(Command("menu"))
async def on_menu(m: Message, state: FSMContext):
    await state.clear(); upsert_user(m.from_user); await show_menu(m, get_lang(m.from_user.id))

@router.message(Command("help"))
async def on_help(m: Message):
    upsert_user(m.from_user); lang = get_lang(m.from_user.id)
    await m.answer(T(lang, "help_text", support=html.escape(SUPPORT)), reply_markup=back_menu(lang))

@router.message(Command("verse"))
async def on_verse_cmd(m: Message):
    lang = get_lang(m.from_user.id); ref, txt = daily_verse()
    if lang != "en":
        got = await fetch_any(ref, lang)
        if got: await m.answer(got, reply_markup=back_menu(lang)); return
    await m.answer(f"🌅 <b>{T(lang, 'verse_day')} — {html.escape(ref)}</b>\n\n{html.escape(txt)}", reply_markup=back_menu(lang))

# --- callbacks: menu sections
@router.callback_query(F.data == "m:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await show_menu(cb, get_lang(cb.from_user.id))

@router.callback_query(F.data == "m:lang")
async def cb_lang(cb: CallbackQuery):
    lang = get_lang(cb.from_user.id)
    await cb.message.answer(T(lang, "choose_lang"), reply_markup=language_keyboard()); await cb.answer()

@router.callback_query(F.data.startswith("lang:set:"))
async def cb_lang_set(cb: CallbackQuery, state: FSMContext):
    code = cb.data.split(":")[-1]
    if code not in LANGS: await cb.answer(); return
    set_user(cb.from_user.id, "language", code)
    await cb.answer(T(code, "lang_set"))
    await cb.message.answer(T(code, "lang_set") + "\n\n" + T(code, "menu_title"), reply_markup=main_menu(code))

# --- support / donate
@router.callback_query(F.data == "m:support")
async def cb_support(cb: CallbackQuery):
    lang = get_lang(cb.from_user.id)
    how = html.escape(SUPPORT_DETAILS) if SUPPORT_DETAILS else T(lang, "support_contact_default", support=html.escape(SUPPORT))
    rows = []
    if SUPPORT_LINK: rows.append([InlineKeyboardButton(text="💳 " + T(lang, "support_btn"), url=SUPPORT_LINK)])
    rows.append([InlineKeyboardButton(text=T(lang, "support_done_btn"), callback_data="sup:done")])
    rows.append([InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")])
    await cb.message.answer(f"{T(lang, 'support_title')}\n\n{T(lang, 'support_body')}\n\n{T(lang, 'support_how')}\n{how}",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await cb.answer()

async def _finish_support(target, uid, user, note: str, lang: str, bot: Bot):
    with db() as c:
        cur = c.execute("INSERT INTO supports(user_id,username,full_name,note,created_at) VALUES(?,?,?,?,?)",
                        (uid, user.username or "", user.full_name or "", note, datetime.now(TZ).isoformat(timespec="seconds")))
        sid = cur.lastrowid
    await target.answer(T(lang, "support_thanks"), reply_markup=back_menu(lang))
    for aid in ADMIN_IDS:
        try: await bot.send_message(aid, f"❤️ <b>New supporter #{sid}</b>\nFrom: {html.escape(user.full_name or '')} (@{html.escape(user.username or '—')}, <code>{uid}</code>)\nNote: {html.escape(note or '—')}")
        except Exception: pass

@router.callback_query(F.data == "sup:done")
async def cb_support_done(cb: CallbackQuery, state: FSMContext):
    lang = get_lang(cb.from_user.id)
    await state.set_state(Form.support_note)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=T(lang, "skip"), callback_data="sup:skip")]])
    await cb.message.answer(T(lang, "support_note_prompt"), reply_markup=kb); await cb.answer()

@router.callback_query(F.data == "sup:skip")
async def cb_support_skip(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await _finish_support(cb.message, cb.from_user.id, cb.from_user, "", get_lang(cb.from_user.id), bot); await cb.answer()

@router.message(Form.support_note)
async def do_support_note(m: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await _finish_support(m, m.from_user.id, m.from_user, (m.text or "").strip()[:500], get_lang(m.from_user.id), bot)

@router.callback_query(F.data == "m:daily")
async def cb_daily(cb: CallbackQuery):
    lang = get_lang(cb.from_user.id); ref, txt = daily_verse()
    if lang != "en":
        got = await fetch_any(ref, lang)
        if got:
            try: await cb.message.edit_text(got, reply_markup=back_menu(lang))
            except Exception: await cb.message.answer(got, reply_markup=back_menu(lang))
            await cb.answer(); return
    try: await cb.message.edit_text(f"🌅 <b>{T(lang, 'verse_day')} — {html.escape(ref)}</b>\n\n{html.escape(txt)}", reply_markup=back_menu(lang))
    except Exception: await cb.message.answer(f"🌅 <b>{T(lang, 'verse_day')} — {html.escape(ref)}</b>\n\n{html.escape(txt)}", reply_markup=back_menu(lang))
    await cb.answer()

@router.callback_query(F.data == "m:search")
async def cb_search(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Form.search); lang = get_lang(cb.from_user.id)
    try: await cb.message.edit_text(T(lang, "search_title"), reply_markup=back_menu(lang))
    except Exception: await cb.message.answer(T(lang, "search_title"), reply_markup=back_menu(lang))
    await cb.answer()

def _topic_key_for(text: str):
    low = (text or "").strip().lower()
    if low in TOPICS: return low
    for lang, labels in TOPIC_LABELS.items():
        for k, v in labels.items():
            if v.lower() == low: return k
    return None

@router.message(Form.search)
async def do_search(m: Message, state: FSMContext):
    q = (m.text or "").strip(); lang = get_lang(m.from_user.id)
    if not q: return
    await state.clear()
    if REF_RE.match(q):
        out = await fetch_any(q, lang)
        await m.answer(out or T(lang, "search_fail"), reply_markup=back_menu(lang)); return
    results = await keyword_search_lang(q, lang)
    if not results:
        key = _topic_key_for(q)
        if key:
            parts = []
            for (ref,) in TOPICS[key]:
                got = await fetch_any(ref, lang)
                if got: parts.append(got)
            results = parts
    if results: await m.answer("\n\n".join(results), reply_markup=back_menu(lang)); return
    note = T(lang, "no_results", q=html.escape(q))
    if lang in ("ha", "yo"): note += "\n\n" + T(lang, "kw_note")
    await m.answer(note, reply_markup=back_menu(lang))

def books_keyboard(books, lang: str = "en", names: dict | None = None):
    rows = []
    for i in range(0, len(books), 2):
        rows.append([InlineKeyboardButton(text=(names or {}).get(b, b), callback_data=f"book:{b}") for b in books[i:i+2]])
    rows.append([InlineKeyboardButton(text=T(lang, "back_testaments"), callback_data="m:read")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def chapter_keyboard(book: str, page: int = 0, per_page: int = 30, lang: str = "en"):
    total = BOOK_CHAPTERS.get(book, 1); pages = (total + per_page - 1) // per_page
    page = max(0, min(page, pages - 1))
    start = page * per_page; nums = list(range(start + 1, min(start + per_page, total) + 1))
    rows = []
    for i in range(0, len(nums), 5):
        rows.append([InlineKeyboardButton(text=str(n), callback_data=f"chap:{book}:{n}") for n in nums[i:i+5]])
    if pages > 1:
        nav = []
        if page > 0: nav.append(InlineKeyboardButton(text=T(lang, "prev_chapters_nav"), callback_data=f"chpage:{book}:{page-1}"))
        if page < pages - 1: nav.append(InlineKeyboardButton(text=T(lang, "more_chapters_nav"), callback_data=f"chpage:{book}:{page+1}"))
        if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text=T(lang, "back_books"), callback_data="test:old" if book in OLD_TESTAMENT else "test:new")])
    rows.append([InlineKeyboardButton(text=T(lang, "home"), callback_data="m:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == "m:read")
async def cb_read(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Form.read_ref); lang = get_lang(cb.from_user.id)
    rows = [[InlineKeyboardButton(text=T(lang, "old_test"), callback_data="test:old")],
            [InlineKeyboardButton(text=T(lang, "new_test"), callback_data="test:new")],
            [InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")]]
    try: await cb.message.edit_text(T(lang, "read_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception: await cb.message.answer(T(lang, "read_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()

@router.callback_query(F.data.startswith("test:"))
async def cb_testament(cb: CallbackQuery):
    which = cb.data.split(":", 1)[1]; lang = get_lang(cb.from_user.id)
    books = OLD_TESTAMENT if which == "old" else NEW_TESTAMENT
    title = "📜 <b>" + T(lang, "old_test").split("—")[0].strip() + "</b>" if which == "old" else "✝️ <b>" + T(lang, "new_test").split("—")[0].strip() + "</b>"
    names = None
    code = LANGS.get(lang, {}).get("bolls")
    if code:
        localized = await bolls_book_names(code)
        if len(localized) == 66: names = {b: localized[BOOKS.index(b)] for b in books}
    await cb.message.edit_text(f"{title}\n\n{T(lang, 'tap_book')}", reply_markup=books_keyboard(books, lang, names)); await cb.answer()

@router.callback_query(F.data.startswith("book:"))
async def cb_book(cb: CallbackQuery, state: FSMContext):
    book = cb.data.split(":", 1)[1]; lang = get_lang(cb.from_user.id)
    await state.update_data(book=book)
    total = BOOK_CHAPTERS.get(book, 1)
    label = T(lang, "chapter_word") if total == 1 else T(lang, "chapters_word")
    disp = await book_display(lang, book)
    await cb.message.edit_text(f"📚 <b>{html.escape(disp)}</b> — {total} {label}\n\n{T(lang, 'tap_chapter')}", reply_markup=chapter_keyboard(book, lang=lang)); await cb.answer()

@router.callback_query(F.data.startswith("chpage:"))
async def cb_chpage(cb: CallbackQuery):
    parts = cb.data.split(":"); page = int(parts[-1]); book = ":".join(parts[1:-1]); lang = get_lang(cb.from_user.id)
    disp = await book_display(lang, book)
    await cb.message.edit_text(f"📚 <b>{html.escape(disp)}</b>\n\n{T(lang, 'tap_chapter')}", reply_markup=chapter_keyboard(book, page, lang=lang)); await cb.answer()

@router.callback_query(F.data.startswith("chap:"))
async def cb_chapter(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":"); chapter = parts[-1]; book = ":".join(parts[1:-1]); lang = get_lang(cb.from_user.id)
    await state.clear()
    out = await fetch_chapter_text(book, int(chapter), lang)
    if not out and lang != "en": out = await fetch_chapter_text(book, int(chapter), "en")  # fallback to KJV if a source hiccups
    if not out:
        await cb.message.answer(T(lang, "chapter_fail"), reply_markup=back_menu(lang)); await cb.answer(); return
    disp = await book_display(lang, book)
    nav = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=T(lang, "listen", book=disp, chapter=chapter), callback_data=f"audio:{book}:{chapter}")],
        [InlineKeyboardButton(text=T(lang, "more_chapters"), callback_data=f"book:{book}")],
        [InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")]])
    await send_long(cb.message, out, last_markup=nav); await cb.answer()

@router.callback_query(F.data.startswith("audio:"))
async def cb_audio(cb: CallbackQuery):
    parts = cb.data.split(":"); chapter = parts[-1]; book = ":".join(parts[1:-1]); lang = get_lang(cb.from_user.id)
    url = audio_url(book, chapter)
    await cb.answer(T(lang, "audio_loading"))
    disp = await book_display(lang, book)
    if not url or not await audio_exists(url):
        await cb.message.answer(T(lang, "audio_unavail", book=html.escape(disp), chapter=html.escape(chapter)), reply_markup=back_menu(lang)); return
    try:
        await cb.message.answer_audio(url, caption=f"🔊 <b>{html.escape(disp)} {html.escape(chapter)}</b> — {T(lang, 'audio_note')}", title=f"{book} {chapter} (KJV)", performer="KJV Audio Bible")
    except Exception as e:
        log.warning("audio send failed: %s", e)
        await cb.message.answer(T(lang, "audio_failed"), reply_markup=back_menu(lang))

@router.message(Form.read_ref)
async def do_read(m: Message, state: FSMContext):
    data = await state.get_data(); txt = (m.text or "").strip(); lang = get_lang(m.from_user.id)
    ref = f"{data['book']} {txt}" if data.get("book") and txt.isdigit() else txt
    if not REF_RE.match(ref):
        await m.answer(T(lang, "type_ref_hint")); return
    await state.clear()
    out = await fetch_any(ref, lang)
    if not out: await m.answer(T(lang, "read_fail"), reply_markup=back_menu(lang)); return
    markup = back_menu(lang)
    mm = REF_RE.match(ref)
    if mm and not mm.group(3):  # a whole chapter, not a verse range — offer audio
        book_name = normalize_book(mm.group(1))
        if book_name:
            disp = await book_display(lang, book_name)
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=T(lang, "listen", book=disp, chapter=mm.group(2)), callback_data=f"audio:{book_name}:{mm.group(2)}")],
                [InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")]])
    await send_long(m, out, last_markup=markup)

@router.callback_query(F.data == "m:topics")
async def cb_topics(cb: CallbackQuery):
    lang = get_lang(cb.from_user.id)
    rows = [[InlineKeyboardButton(text=f"💡 {TOPIC_LABELS.get(lang, TOPIC_LABELS['en']).get(k, k.title())}", callback_data=f"topic:{k}")] for k in TOPICS]
    rows.append([InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")])
    try: await cb.message.edit_text(T(lang, "topics_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception: await cb.message.answer(T(lang, "topics_title"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()

@router.callback_query(F.data.startswith("topic:"))
async def cb_topic(cb: CallbackQuery):
    key = cb.data.split(":", 1)[1]; lang = get_lang(cb.from_user.id)
    parts = []
    for (ref,) in TOPICS.get(key, []):
        got = await fetch_any(ref, lang)
        if got: parts.append(got)
    text = "\n\n".join(parts) if parts else T(lang, "topics_fail")
    try: await cb.message.edit_text(text, reply_markup=back_menu(lang))
    except Exception: await send_long(cb.message, text, last_markup=back_menu(lang))
    await cb.answer()

async def _render_dev(cb: CallbackQuery, day: int):
    lang = get_lang(cb.from_user.id); devs = dev_for(lang)
    day %= len(devs)
    title, ref, body, prayer = devs[day]
    verse = await fetch_any(ref, lang)
    rows = [[InlineKeyboardButton(text=T(lang, "prev_day"), callback_data=f"dev:{(day-1) % len(devs)}"),
             InlineKeyboardButton(text=T(lang, "next_day"), callback_data=f"dev:{(day+1) % len(devs)}")],
            [InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")]]
    text = f"🌅 <b>{html.escape(title)}</b>\n\n{verse or ''}\n\n{html.escape(body)}\n\n🙏 <i>{html.escape(prayer)}</i>"
    try: await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception: await cb.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()

@router.callback_query(F.data == "m:dev")
async def cb_dev(cb: CallbackQuery):
    await _render_dev(cb, datetime.now(TZ).toordinal() % len(DEVOTIONALS))

@router.callback_query(F.data.startswith("dev:"))
async def cb_dev_day(cb: CallbackQuery):
    await _render_dev(cb, int(cb.data.split(":", 1)[1]))

# --- quiz
async def send_quiz(cb_or_msg, uid):
    lang = get_lang(uid); quiz = quiz_for(lang)
    idx = random.randrange(len(quiz)); q, opts, _ = quiz[idx]
    rows = [[InlineKeyboardButton(text=o, callback_data=f"quiz:{idx}:{i}")] for i, o in enumerate(opts)]
    rows.append([InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")])
    text = f"{T(lang, 'quiz_title')}\n\n{html.escape(q)}"
    if isinstance(cb_or_msg, CallbackQuery):
        try: await cb_or_msg.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except Exception: await cb_or_msg.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await cb_or_msg.answer()
    else: await cb_or_msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data == "m:quiz")
async def cb_quiz(cb: CallbackQuery): await send_quiz(cb, cb.from_user.id)

@router.callback_query(F.data.startswith("quiz:"))
async def cb_quiz_answer(cb: CallbackQuery):
    _, idx, choice = cb.data.split(":"); idx, choice = int(idx), int(choice)
    lang = get_lang(cb.from_user.id); quiz = quiz_for(lang)
    q, opts, correct = quiz[idx]; user = get_user(cb.from_user.id)
    score = (user["quiz_score"] if user else 0) or 0; answered = (user["quiz_answered"] if user else 0) or 0
    right = choice == correct; answered += 1; score += 1 if right else 0
    set_user(cb.from_user.id, "quiz_score", score); set_user(cb.from_user.id, "quiz_answered", answered)
    verdict = T(lang, "correct") if right else T(lang, "wrong", answer=html.escape(opts[correct]))
    rows = [[InlineKeyboardButton(text=T(lang, "next_q"), callback_data="m:quiz")],
            [InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")]]
    await cb.message.edit_text(f"{verdict}\n\n{T(lang, 'your_score', score=score, answered=answered)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await cb.answer()

# --- prayer
@router.callback_query(F.data == "m:prayer")
async def cb_prayer(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Form.prayer); lang = get_lang(cb.from_user.id)
    try: await cb.message.edit_text(T(lang, "prayer_title"), reply_markup=back_menu(lang))
    except Exception: await cb.message.answer(T(lang, "prayer_title"), reply_markup=back_menu(lang))
    await cb.answer()

@router.message(Form.prayer)
async def do_prayer(m: Message, state: FSMContext, bot: Bot):
    text = (m.text or "").strip()
    if not text: return
    await state.clear()
    with db() as c:
        cur = c.execute("INSERT INTO prayers(user_id,username,full_name,text,created_at) VALUES(?,?,?,?,?)",
                        (m.from_user.id, m.from_user.username or "", m.from_user.full_name or "", text, datetime.now(TZ).isoformat(timespec="seconds")))
        pid = cur.lastrowid
    lang = get_lang(m.from_user.id)
    await m.answer(T(lang, "prayer_sent"), reply_markup=back_menu(lang))
    for aid in ADMIN_IDS:
        try: await bot.send_message(aid, f"🙏 <b>New prayer request #{pid}</b>\nFrom: {html.escape(m.from_user.full_name or '')} (@{html.escape(m.from_user.username or '—')}, <code>{m.from_user.id}</code>)\n\n{html.escape(text)}")
        except Exception: pass

# --- settings
@router.callback_query(F.data == "m:settings")
async def cb_settings(cb: CallbackQuery):
    user = get_user(cb.from_user.id); lang = get_lang(cb.from_user.id)
    daily = (user["daily_optin"] if user else 1)
    rows = [[InlineKeyboardButton(text=T(lang, "daily_toggle", state=T(lang, "on") if daily else T(lang, "off")), callback_data="set:daily")],
            [InlineKeyboardButton(text=f"🌐 {T(lang, 'lang_btn')}: {LANGS[lang]['native']}", callback_data="m:lang")],
            [InlineKeyboardButton(text=T(lang, "back"), callback_data="m:menu")]]
    text = f"{T(lang, 'settings_title')}\n\n{T(lang, 'version_line', version=html.escape(LANGS[lang]['version']))}"
    try: await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception: await cb.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()

@router.callback_query(F.data.startswith("set:"))
async def cb_set(cb: CallbackQuery):
    parts = cb.data.split(":")
    if parts[1] == "daily":
        user = get_user(cb.from_user.id); set_user(cb.from_user.id, "daily_optin", 0 if (user and user["daily_optin"]) else 1)
    await cb_settings(cb)

# --- plain text: treat as search / reference
@router.message(F.text & ~F.text.startswith("/"))
async def catch_all(m: Message):
    upsert_user(m.from_user)
    q = m.text.strip(); lang = get_lang(m.from_user.id)
    if REF_RE.match(q):
        out = await fetch_any(q, lang); await m.answer(out or T(lang, "search_fail"), reply_markup=back_menu(lang)); return
    key = _topic_key_for(q)
    if key:
        parts = []
        for (ref,) in TOPICS[key]:
            got = await fetch_any(ref, lang)
            if got: parts.append(got)
        if parts: await m.answer("\n\n".join(parts), reply_markup=back_menu(lang)); return
    await m.answer(T(lang, "not_understood"), reply_markup=main_menu(lang))

# ---------------------------------------------------------------- admin (hidden: type /admin, not in menu)
@router.message(Command("admin"))
async def on_admin(m: Message):
    if not is_admin(m.from_user.id): return  # silently ignore non-admins
    with db() as c:
        users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        prayers = c.execute("SELECT COUNT(*) n FROM prayers WHERE status='new'").fetchone()["n"]
    with db() as c:
        sup = c.execute("SELECT COUNT(*) n FROM supports").fetchone()["n"]
    rows = [[InlineKeyboardButton(text="🙏 New prayer requests", callback_data="a:prayers")],
            [InlineKeyboardButton(text="❤️ Supporters", callback_data="a:supports")],
            [InlineKeyboardButton(text="📣 Broadcast message", callback_data="a:broadcast")],
            [InlineKeyboardButton(text="📊 Stats", callback_data="a:stats")]]
    await m.answer(f"🛠 <b>Admin Panel</b>\n\n👥 Total users: <b>{users}</b>\n🙏 New prayer requests: <b>{prayers}</b>\n❤️ Supporters: <b>{sup}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data == "a:stats")
async def cb_stats(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer(); return
    with db() as c:
        users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        daily = c.execute("SELECT COUNT(*) n FROM users WHERE daily_optin=1").fetchone()["n"]
        prayers = c.execute("SELECT COUNT(*) n FROM prayers").fetchone()["n"]
        top = c.execute("SELECT full_name, quiz_score, quiz_answered FROM users ORDER BY quiz_score DESC LIMIT 5").fetchall()
    board = "\n".join(f"• {html.escape(r['full_name'] or 'User')} — {r['quiz_score']}/{r['quiz_answered']}" for r in top) or "No quiz scores yet."
    await cb.message.edit_text(f"📊 <b>Stats</b>\n\n👥 Users: <b>{users}</b> (daily verse ON: {daily})\n🙏 Total prayers: <b>{prayers}</b>\n\n🏆 <b>Top quiz scores</b>\n{board}", reply_markup=back_menu()); await cb.answer()

@router.callback_query(F.data == "a:prayers")
async def cb_prayers(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer(); return
    with db() as c: rows_ = c.execute("SELECT * FROM prayers WHERE status='new' ORDER BY id DESC LIMIT 10").fetchall()
    if not rows_: await cb.message.edit_text("🙏 No new prayer requests.", reply_markup=back_menu()); await cb.answer(); return
    text = "🙏 <b>New prayer requests</b>\n\n" + "\n\n".join(f"#{r['id']} — {html.escape(r['full_name'] or '')} (@{html.escape(r['username'] or '—')})\n{html.escape(r['text'])}" for r in rows_)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Mark all as prayed", callback_data="a:prayed")], [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")]])
    await cb.message.edit_text(text[:4000], reply_markup=kb); await cb.answer()

@router.callback_query(F.data == "a:supports")
async def cb_supports(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer(); return
    with db() as c: rows_ = c.execute("SELECT * FROM supports ORDER BY id DESC LIMIT 10").fetchall()
    if not rows_: await cb.message.edit_text("❤️ No supporters yet.", reply_markup=back_menu()); await cb.answer(); return
    text = "❤️ <b>Recent supporters</b>\n\n" + "\n\n".join(f"#{r['id']} — {html.escape(r['full_name'] or '')} (@{html.escape(r['username'] or '—')})\n{html.escape(r['note'] or '—')}" for r in rows_)
    await cb.message.edit_text(text[:4000], reply_markup=back_menu()); await cb.answer()

@router.callback_query(F.data == "a:prayed")
async def cb_prayed(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): await cb.answer(); return
    with db() as c: c.execute("UPDATE prayers SET status='prayed' WHERE status='new'")
    await cb.message.edit_text("✅ All prayer requests marked as prayed for.", reply_markup=back_menu()); await cb.answer()

@router.callback_query(F.data == "a:broadcast")
async def cb_broadcast(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): await cb.answer(); return
    await state.set_state(Form.broadcast)
    await cb.message.edit_text("📣 Send the message to broadcast to <b>all users</b>. Send /menu to cancel."); await cb.answer()

@router.message(Form.broadcast)
async def do_broadcast(m: Message, state: FSMContext, bot: Bot):
    if not is_admin(m.from_user.id): await state.clear(); return
    await state.clear()
    with db() as c: ids = [r["user_id"] for r in c.execute("SELECT user_id FROM users").fetchall()]
    ok = fail = 0
    for uid in ids:
        try: await bot.send_message(uid, f"📣 {html.escape(m.text or '')}"); ok += 1
        except Exception: fail += 1
        await asyncio.sleep(0.05)
    await m.answer(f"📣 Broadcast done — sent: {ok}, failed/blocked: {fail}")

# ---------------------------------------------------------------- daily verse job
async def daily_job(bot: Bot):
    while True:
        try:
            now = datetime.now(TZ); today = now.date().isoformat()
            if now.hour == DAILY_HOUR and meta_get("last_daily") != today:
                meta_set("last_daily", today)
                ref, txt = daily_verse(now.date())
                with db() as c: rows_ = c.execute("SELECT user_id, language FROM users WHERE daily_optin=1").fetchall()
                by_lang = {}
                for r in rows_: by_lang.setdefault((r["language"] or "en") if r["language"] in LANGS else "en", []).append(r["user_id"])
                total = 0
                for lang, ids in by_lang.items():
                    if lang == "en":
                        body = f"🌅 <b>{T('en', 'verse_day')} — {html.escape(ref)}</b>\n\n{html.escape(txt)}"
                    else:
                        body = await fetch_any(ref, lang) or f"🌅 <b>{T(lang, 'verse_day')} — {html.escape(ref)}</b>\n\n{html.escape(txt)}"
                    for uid in ids:
                        try: await bot.send_message(uid, body + "\n\n" + T(lang, "daily_tail"))
                        except Exception: pass
                        total += 1; await asyncio.sleep(0.05)
                log.info("Daily verse sent to %d users", total)
        except Exception as e: log.warning("daily job: %s", e)
        await asyncio.sleep(60)

async def main():
    if not BOT_TOKEN: raise SystemExit("Set BOT_TOKEN in Railway Variables (get it from @BotFather).")
    init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage()); dp.include_router(router)
    # Customer menu: ONLY these three. /admin works typed, never listed.
    try: await bot.delete_my_commands()
    except Exception: pass
    await bot.set_my_commands([BotCommand(command="start", description="Start the bot"),
                               BotCommand(command="menu", description="Open the Menu"),
                               BotCommand(command="help", description="Help")])
    asyncio.create_task(daily_job(bot))
    log.info("Bible bot started. Admins: %s", ADMIN_IDS or "none set — set ADMIN_IDS to use /admin")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
