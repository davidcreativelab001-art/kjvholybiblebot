"""
KJV Holy Bible Bot (@kjvholybiblebot) — full version
Features: Daily Verse (auto 07:00 Africa/Lagos), Bible Search (reference + keyword),
Read by book/chapter, Topics, 14-day Devotionals, Bible Quiz with scores,
Prayer Requests (forwarded to admin), Admin panel (/admin, hidden from menu).

Deploy on Railway:
  Variables: BOT_TOKEN=..., ADMIN_IDS=your_telegram_id (comma-separate for more)
  Optional:   DAILY_HOUR=7, DATABASE_PATH=bible_bot.db
  Start command: python bot.py

Bible text: bible-api.com (free, no key) — KJV only.
Keyword search: bolls.life (free, no key) with a built-in topical fallback.
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
        """)

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

# ---------------------------------------------------------------- FSM / keyboards
class Form(StatesGroup):
    search = State(); prayer = State(); read_ref = State()
    broadcast = State(); devotional = State()

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Verse of the Day", callback_data="m:daily"),
         InlineKeyboardButton(text="🔍 Search the Bible", callback_data="m:search")],
        [InlineKeyboardButton(text="📚 Read a Chapter", callback_data="m:read"),
         InlineKeyboardButton(text="💡 Topics", callback_data="m:topics")],
        [InlineKeyboardButton(text="🌅 Devotionals", callback_data="m:dev"),
         InlineKeyboardButton(text="❓ Bible Quiz", callback_data="m:quiz")],
        [InlineKeyboardButton(text="🙏 Prayer Request", callback_data="m:prayer"),
         InlineKeyboardButton(text="⚙️ Settings", callback_data="m:settings")],
    ])

def back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")]])

router = Router()

async def show_menu(target):
    text = "📖 <b>KJV Holy Bible</b>\n\nWhat would you like to do today?"
    if isinstance(target, Message): await target.answer(text, reply_markup=main_menu())
    else: await target.message.edit_text(text, reply_markup=main_menu()); await target.answer()

@router.message(CommandStart())
async def on_start(m: Message, state: FSMContext):
    await state.clear(); upsert_user(m.from_user)
    ref, txt = daily_verse()
    await m.answer(f"👋 Welcome, {html.escape(m.from_user.first_name or 'friend')}!\n\n"
                   f"🌅 <b>Verse of the Day — {html.escape(ref)}</b>\n{html.escape(txt)}\n\n"
                   "Use the menu below to search the Bible, read devotionals, take the quiz, or send a prayer request.",
                   reply_markup=main_menu())

@router.message(Command("menu"))
async def on_menu(m: Message, state: FSMContext):
    await state.clear(); upsert_user(m.from_user); await show_menu(m)

@router.message(Command("help"))
async def on_help(m: Message):
    upsert_user(m.from_user)
    await m.answer("📖 <b>How to use this bot</b>\n\n"
                   "• <b>Verse of the Day</b> — a fresh verse daily (auto-sent 07:00 if enabled in Settings)\n"
                   "• <b>Search</b> — type a reference like <code>John 3:16</code> or a word like <code>faith</code>\n"
                   "• <b>Read a Chapter</b> — e.g. <code>Psalms 23</code> or <code>John 1</code>\n"
                   "• <b>Topics</b> — verses for hope, fear, healing and more\n"
                   "• <b>Devotionals</b> — 14 short daily readings with a prayer\n"
                   "• <b>Quiz</b> — test your Bible knowledge, scores are saved\n"
                   "• <b>Prayer Request</b> — sent privately to the ministry team\n\n"
                   f"Questions? Contact {html.escape(SUPPORT)}", reply_markup=back_menu())

@router.message(Command("verse"))
async def on_verse_cmd(m: Message):
    ref, txt = daily_verse()
    await m.answer(f"🌅 <b>Verse of the Day — {html.escape(ref)}</b>\n\n{html.escape(txt)}", reply_markup=back_menu())

# --- callbacks: menu sections
@router.callback_query(F.data == "m:menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear(); await show_menu(cb)

@router.callback_query(F.data == "m:daily")
async def cb_daily(cb: CallbackQuery):
    ref, txt = daily_verse()
    await cb.message.edit_text(f"🌅 <b>Verse of the Day — {html.escape(ref)}</b>\n\n{html.escape(txt)}", reply_markup=back_menu()); await cb.answer()

@router.callback_query(F.data == "m:search")
async def cb_search(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Form.search)
    await cb.message.edit_text("🔍 <b>Search the Bible</b>\n\nSend a reference like <code>John 3:16</code> or <code>Romans 8</code>, or a keyword like <code>faith</code>, <code>healing</code>, <code>love</code>.", reply_markup=back_menu()); await cb.answer()

@router.message(Form.search)
async def do_search(m: Message, state: FSMContext):
    q = (m.text or "").strip(); user = get_user(m.from_user.id); tr = "kjv"  # KJV only
    if not q: return
    await state.clear()
    if REF_RE.match(q):
        out = await fetch_reference(q, tr)
        await m.answer(out or "Sorry, I couldn't find that passage. Check the spelling, e.g. <code>John 3:16</code>.", reply_markup=back_menu()); return
    results = await keyword_search(q, tr)
    if not results:  # topical fallback
        key = q.lower()
        if key in TOPICS:
            parts = []
            for (ref,) in TOPICS[key]:
                got = await fetch_reference(ref, tr)
                if got: parts.append(got)
            results = parts
    await m.answer("\n\n".join(results) if results else f"No results for “{html.escape(q)}”. Try a topic like <b>hope</b>, <b>faith</b> or <b>healing</b>, or a reference like <code>John 3:16</code>.", reply_markup=back_menu())

def books_keyboard(books):
    rows = []
    for i in range(0, len(books), 2):
        rows.append([InlineKeyboardButton(text=b, callback_data=f"book:{b}") for b in books[i:i+2]])
    rows.append([InlineKeyboardButton(text="⬅️ Back to Testaments", callback_data="m:read")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def chapter_keyboard(book: str, page: int = 0, per_page: int = 30):
    total = BOOK_CHAPTERS.get(book, 1); pages = (total + per_page - 1) // per_page
    page = max(0, min(page, pages - 1))
    start = page * per_page; nums = list(range(start + 1, min(start + per_page, total) + 1))
    rows = []
    for i in range(0, len(nums), 5):
        rows.append([InlineKeyboardButton(text=str(n), callback_data=f"chap:{book}:{n}") for n in nums[i:i+5]])
    if pages > 1:
        nav = []
        if page > 0: nav.append(InlineKeyboardButton(text="◀️ Chapters", callback_data=f"chpage:{book}:{page-1}"))
        if page < pages - 1: nav.append(InlineKeyboardButton(text="More chapters ▶️", callback_data=f"chpage:{book}:{page+1}"))
        if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Back to Books", callback_data="test:old" if book in OLD_TESTAMENT else "test:new")])
    rows.append([InlineKeyboardButton(text="🏠 Main Menu", callback_data="m:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.callback_query(F.data == "m:read")
async def cb_read(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Form.read_ref)
    rows = [[InlineKeyboardButton(text="📜 Old Testament — 39 books", callback_data="test:old")],
            [InlineKeyboardButton(text="✝️ New Testament — 27 books", callback_data="test:new")],
            [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")]]
    await cb.message.edit_text("📚 <b>Read the Bible (KJV)</b>\n\nChoose a Testament, then tap a book, then tap a chapter — no typing needed.\n\nYou can also type any reference directly, e.g. <code>Psalms 23</code> or <code>John 3:16</code>.", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await cb.answer()

@router.callback_query(F.data.startswith("test:"))
async def cb_testament(cb: CallbackQuery):
    which = cb.data.split(":", 1)[1]
    books = OLD_TESTAMENT if which == "old" else NEW_TESTAMENT
    title = "📜 <b>Old Testament</b>" if which == "old" else "✝️ <b>New Testament</b>"
    await cb.message.edit_text(f"{title}\n\nTap the book you want to read:", reply_markup=books_keyboard(books)); await cb.answer()

@router.callback_query(F.data.startswith("book:"))
async def cb_book(cb: CallbackQuery, state: FSMContext):
    book = cb.data.split(":", 1)[1]
    await state.update_data(book=book)
    total = BOOK_CHAPTERS.get(book, 1)
    label = "chapter" if total == 1 else "chapters"
    await cb.message.edit_text(f"📚 <b>{html.escape(book)}</b> — {total} {label}\n\nTap a chapter to read it:", reply_markup=chapter_keyboard(book)); await cb.answer()

@router.callback_query(F.data.startswith("chpage:"))
async def cb_chpage(cb: CallbackQuery):
    parts = cb.data.split(":"); page = int(parts[-1]); book = ":".join(parts[1:-1])
    await cb.message.edit_text(f"📚 <b>{html.escape(book)}</b>\n\nTap a chapter to read it:", reply_markup=chapter_keyboard(book, page)); await cb.answer()

@router.callback_query(F.data.startswith("chap:"))
async def cb_chapter(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":"); chapter = parts[-1]; book = ":".join(parts[1:-1])
    await state.clear()
    out = await fetch_reference(f"{book} {chapter}", "kjv")
    if not out:
        await cb.message.answer("Sorry, I couldn't load that chapter right now. Please try again.", reply_markup=back_menu()); await cb.answer(); return
    nav = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔊 Listen to {book} {chapter}", callback_data=f"audio:{book}:{chapter}")],
        [InlineKeyboardButton(text="📚 More chapters of this book", callback_data=f"book:{book}")],
        [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")]])
    await send_long(cb.message, out, last_markup=nav); await cb.answer()

@router.callback_query(F.data.startswith("audio:"))
async def cb_audio(cb: CallbackQuery):
    parts = cb.data.split(":"); chapter = parts[-1]; book = ":".join(parts[1:-1])
    url = audio_url(book, chapter)
    await cb.answer("Loading the audio…")
    if not url or not await audio_exists(url):
        await cb.message.answer(f"🔇 Sorry, audio isn't available for {html.escape(book)} {html.escape(chapter)} yet — please enjoy reading the chapter above.", reply_markup=back_menu()); return
    try:
        await cb.message.answer_audio(url, caption=f"🔊 <b>{html.escape(book)} {html.escape(chapter)}</b> — King James Version", title=f"{book} {chapter} (KJV)", performer="KJV Audio Bible")
    except Exception as e:
        log.warning("audio send failed: %s", e)
        await cb.message.answer("🔇 The audio couldn't be sent just now — please try again in a moment.", reply_markup=back_menu())

@router.message(Form.read_ref)
async def do_read(m: Message, state: FSMContext):
    data = await state.get_data(); txt = (m.text or "").strip()
    ref = f"{data['book']} {txt}" if data.get("book") and txt.isdigit() else txt
    if not REF_RE.match(ref):
        await m.answer("Please tap a Testament → Book → Chapter above, or send a full reference like <code>Psalms 23</code>."); return
    await state.clear()
    out = await fetch_reference(ref, "kjv")
    if not out: await m.answer("Sorry, I couldn't load that chapter. Try e.g. <code>John 1</code>.", reply_markup=back_menu()); return
    markup = back_menu()
    mm = REF_RE.match(ref)
    if mm and not mm.group(3):  # a whole chapter, not a verse range — offer audio
        book_name = " ".join(mm.group(1).split()).title() if not mm.group(1)[0].isdigit() else mm.group(1).strip()
        book_name = {"Psalm": "Psalms"}.get(book_name, book_name)
        if book_name in BOOK_CHAPTERS:
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🔊 Listen to {book_name} {mm.group(2)}", callback_data=f"audio:{book_name}:{mm.group(2)}")],
                [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")]])
    await send_long(m, out, last_markup=markup)

@router.callback_query(F.data == "m:topics")
async def cb_topics(cb: CallbackQuery):
    rows = [[InlineKeyboardButton(text=f"💡 {k.title()}", callback_data=f"topic:{k}")] for k in TOPICS]
    rows.append([InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")])
    await cb.message.edit_text("💡 <b>Verses by Topic</b>\n\nChoose what you need today:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await cb.answer()

@router.callback_query(F.data.startswith("topic:"))
async def cb_topic(cb: CallbackQuery):
    key = cb.data.split(":", 1)[1]; user = get_user(cb.from_user.id); tr = "kjv"  # KJV only
    parts = []
    for (ref,) in TOPICS.get(key, []):
        got = await fetch_reference(ref, tr)
        if got: parts.append(got)
    await cb.message.edit_text("\n\n".join(parts) if parts else "Couldn't load those verses right now — please try again.", reply_markup=back_menu()); await cb.answer()

@router.callback_query(F.data == "m:dev")
async def cb_dev(cb: CallbackQuery):
    day = datetime.now(TZ).toordinal() % len(DEVOTIONALS)
    title, ref, body, prayer = DEVOTIONALS[day]
    user = get_user(cb.from_user.id); tr = "kjv"  # KJV only
    verse = await fetch_reference(ref, tr)
    rows = [[InlineKeyboardButton(text="◀️ Previous day", callback_data=f"dev:{(day-1) % len(DEVOTIONALS)}"),
             InlineKeyboardButton(text="Next day ▶️", callback_data=f"dev:{(day+1) % len(DEVOTIONALS)}")],
            [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")]]
    await cb.message.edit_text(f"🌅 <b>{html.escape(title)}</b>\n\n{verse or ''}\n\n{html.escape(body)}\n\n🙏 <i>{html.escape(prayer)}</i>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await cb.answer()

@router.callback_query(F.data.startswith("dev:"))
async def cb_dev_day(cb: CallbackQuery):
    day = int(cb.data.split(":", 1)[1]) % len(DEVOTIONALS)
    title, ref, body, prayer = DEVOTIONALS[day]
    user = get_user(cb.from_user.id); tr = "kjv"  # KJV only
    verse = await fetch_reference(ref, tr)
    rows = [[InlineKeyboardButton(text="◀️ Previous day", callback_data=f"dev:{(day-1) % len(DEVOTIONALS)}"),
             InlineKeyboardButton(text="Next day ▶️", callback_data=f"dev:{(day+1) % len(DEVOTIONALS)}")],
            [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")]]
    await cb.message.edit_text(f"🌅 <b>{html.escape(title)}</b>\n\n{verse or ''}\n\n{html.escape(body)}\n\n🙏 <i>{html.escape(prayer)}</i>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await cb.answer()

# --- quiz
async def send_quiz(cb_or_msg, uid):
    idx = random.randrange(len(QUIZ)); q, opts, _ = QUIZ[idx]
    rows = [[InlineKeyboardButton(text=o, callback_data=f"quiz:{idx}:{i}")] for i, o in enumerate(opts)]
    rows.append([InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")])
    text = f"❓ <b>Bible Quiz</b>\n\n{html.escape(q)}"
    if isinstance(cb_or_msg, CallbackQuery): await cb_or_msg.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await cb_or_msg.answer()
    else: await cb_or_msg.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data == "m:quiz")
async def cb_quiz(cb: CallbackQuery): await send_quiz(cb, cb.from_user.id)

@router.callback_query(F.data.startswith("quiz:"))
async def cb_quiz_answer(cb: CallbackQuery):
    _, idx, choice = cb.data.split(":"); idx, choice = int(idx), int(choice)
    q, opts, correct = QUIZ[idx]; user = get_user(cb.from_user.id)
    score = (user["quiz_score"] if user else 0) or 0; answered = (user["quiz_answered"] if user else 0) or 0
    right = choice == correct; answered += 1; score += 1 if right else 0
    set_user(cb.from_user.id, "quiz_score", score); set_user(cb.from_user.id, "quiz_answered", answered)
    verdict = "✅ <b>Correct!</b>" if right else f"❌ Not quite — the answer is <b>{html.escape(opts[correct])}</b>."
    rows = [[InlineKeyboardButton(text="➡️ Next question", callback_data="m:quiz")],
            [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")]]
    await cb.message.edit_text(f"{verdict}\n\n📊 Your score: <b>{score}/{answered}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await cb.answer()

# --- prayer
@router.callback_query(F.data == "m:prayer")
async def cb_prayer(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Form.prayer)
    await cb.message.edit_text("🙏 <b>Prayer Request</b>\n\nWrite your prayer request and send it — it goes privately to the ministry team, who will pray for you. Send /menu to cancel.", reply_markup=back_menu()); await cb.answer()

@router.message(Form.prayer)
async def do_prayer(m: Message, state: FSMContext, bot: Bot):
    text = (m.text or "").strip()
    if not text: return
    await state.clear()
    with db() as c:
        cur = c.execute("INSERT INTO prayers(user_id,username,full_name,text,created_at) VALUES(?,?,?,?,?)",
                        (m.from_user.id, m.from_user.username or "", m.from_user.full_name or "", text, datetime.now(TZ).isoformat(timespec="seconds")))
        pid = cur.lastrowid
    await m.answer("🙏 Thank you — your prayer request has been received. We are praying for you.\n\n<i>“The effectual fervent prayer of a righteous man availeth much.” — James 5:16</i>", reply_markup=back_menu())
    for aid in ADMIN_IDS:
        try: await bot.send_message(aid, f"🙏 <b>New prayer request #{pid}</b>\nFrom: {html.escape(m.from_user.full_name or '')} (@{html.escape(m.from_user.username or '—')}, <code>{m.from_user.id}</code>)\n\n{html.escape(text)}")
        except Exception: pass

# --- settings
@router.callback_query(F.data == "m:settings")
async def cb_settings(cb: CallbackQuery):
    user = get_user(cb.from_user.id)
    daily = (user["daily_optin"] if user else 1)
    rows = [[InlineKeyboardButton(text="📖 Translation: KJV ✓", callback_data="set:noop")],
            [InlineKeyboardButton(text=f"Daily verse 07:00: {'ON ✅' if daily else 'OFF'}", callback_data="set:daily")],
            [InlineKeyboardButton(text="⬅️ Main Menu", callback_data="m:menu")]]
    await cb.message.edit_text("⚙️ <b>Settings</b>\n\nThis bot uses the <b>King James Version (KJV)</b> only.", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)); await cb.answer()

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
    q = m.text.strip(); user = get_user(m.from_user.id); tr = "kjv"  # KJV only
    if REF_RE.match(q):
        out = await fetch_reference(q, tr); await m.answer(out or "Couldn't find that passage — try <code>John 3:16</code>.", reply_markup=back_menu()); return
    if q.lower() in TOPICS:
        parts = []
        for (ref,) in TOPICS[q.lower()]:
            got = await fetch_reference(ref, tr)
            if got: parts.append(got)
        if parts: await m.answer("\n\n".join(parts), reply_markup=back_menu()); return
    await m.answer("Send me a Bible reference like <code>John 3:16</code>, a topic like <b>hope</b> or <b>healing</b>, or open the menu:", reply_markup=main_menu())

# ---------------------------------------------------------------- admin (hidden: type /admin, not in menu)
@router.message(Command("admin"))
async def on_admin(m: Message):
    if not is_admin(m.from_user.id): return  # silently ignore non-admins
    with db() as c:
        users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        prayers = c.execute("SELECT COUNT(*) n FROM prayers WHERE status='new'").fetchone()["n"]
    rows = [[InlineKeyboardButton(text="🙏 New prayer requests", callback_data="a:prayers")],
            [InlineKeyboardButton(text="📣 Broadcast message", callback_data="a:broadcast")],
            [InlineKeyboardButton(text="📊 Stats", callback_data="a:stats")]]
    await m.answer(f"🛠 <b>Admin Panel</b>\n\n👥 Total users: <b>{users}</b>\n🙏 New prayer requests: <b>{prayers}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

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
                with db() as c: ids = [r["user_id"] for r in c.execute("SELECT user_id FROM users WHERE daily_optin=1").fetchall()]
                for uid in ids:
                    try: await bot.send_message(uid, f"🌅 <b>Verse of the Day — {html.escape(ref)}</b>\n\n{html.escape(txt)}\n\nOpen /menu for today's devotional and quiz.")
                    except Exception: pass
                    await asyncio.sleep(0.05)
                log.info("Daily verse sent to %d users", len(ids))
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
