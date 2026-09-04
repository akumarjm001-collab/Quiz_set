import asyncio
import datetime

import logging
import csv
import io
import uuid
import sqlite3

import pytz

from aiogram.dispatcher.middlewares import BaseMiddleware

backup_message_ids = []

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor

API_TOKEN = "8480522731:AAFwu2L1FVq-3rFZddsCeur-ZG0cp602ohs"
BOT_USERNAME = "QuizSet_bot"
ADMIN_IDS = [1692919993]

BACKUP_CHANNEL_ID = -1003728503131

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# ---------------- DATABASE ----------------
conn = sqlite3.connect("quiz.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS quizzes (
    quiz_id TEXT PRIMARY KEY,
    name TEXT,
    time INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS questions (
    quiz_id TEXT,
    question TEXT,
    opt1 TEXT,
    opt2 TEXT,
    opt3 TEXT,
    opt4 TEXT,
    correct INTEGER
)
""")

conn.commit()

# Backup function

async def send_backup():
    global backup_message_ids

    try:
        ist = pytz.timezone("Asia/Kolkata")
        time_now = datetime.datetime.now(ist).strftime("%Y-%m-%d %H:%M")

        with open("quiz.db", "rb") as f:

            msg = await bot.send_document(
                BACKUP_CHANNEL_ID,
                f,
                caption=f"📦 Backup\n🕒 {datetime.datetime.now()}"
            )

        # ✅ message id save करो
        backup_message_ids.append(msg.message_id)

         # ✅ अगर 5 से ज्यादा हो गए → delete old
        if len(backup_message_ids) > 5:
            old_msg_id = backup_message_ids.pop(0)
            await bot.delete_message(BACKUP_CHANNEL_ID, old_msg_id)

        print("✅ Backup sent & cleaned")

    except Exception as e:
        print("❌ Backup Error:", e)

# Advanced Auto Clean

async def clean_old_backups():
    try:
        messages = []
        
        async for msg in bot.iter_chat_history(BACKUP_CHANNEL_ID, limit=50):
            if msg.document and msg.document.file_name == "quiz.db":
                messages.append(msg)

        # latest 5 rakho
        for old in messages[5:]:
            await bot.delete_message(BACKUP_CHANNEL_ID, old.message_id)

    except Exception as e:
        print("Clean error:", e)


# Auto backup loop

async def auto_backup():
    while True:
        await send_backup()
        await asyncio.sleep(3600)  # हर 1 घंटे


# ---------------- MEMORY ----------------
paused_groups = set()  # Paused
active_groups = set()   #Active quiz check
user_sessions = {}
group_sessions = {}
group_scores = {}
poll_data = {}

# ---------------- ADMIN ----------------
def is_admin(user_id):
    return user_id in ADMIN_IDS

class AdminMiddleware(BaseMiddleware):
    async def on_pre_process_update(self, update, data):
        if update.poll_answer:       # ✅ Poll answers sabke allow
            return
        
        user = None

        if update.message:
            user = update.message.from_user
        elif update.callback_query:
            user = update.callback_query.from_user
        elif update.inline_query:
            user = update.inline_query.from_user
        elif update.poll_answer:
            user = update.poll_answer.user

        if user and user.id not in ADMIN_IDS:
            if update.message:
                await update.message.answer("❌ Access Denied")
            raise Exception("Blocked")


dp.middleware.setup(AdminMiddleware())


@dp.callback_query_handler(lambda c: c.data.startswith("edit_title_"))
async def edit_title(callback: types.CallbackQuery):
    quiz_id = callback.data.split("_")[2]

    user_sessions[callback.from_user.id] = {
        "edit_title": quiz_id
    }

    await callback.message.answer("✏️ Send new quiz title:")

# ---------------- START ----------------
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    args = message.get_args()

    if args.startswith("quiz_"):
        quiz_id = args.split("_")[1]

        if message.chat.type == "private":
            await start_private_quiz(message.from_user.id, quiz_id)
        else:
            await start_group_quiz(message.chat.id, quiz_id)

        return

    await message.answer("📂 Send CSV to create quiz (Admin only)")

# ---------------- CSV UPLOAD ----------------
@dp.message_handler(content_types=['document'])
async def upload_csv(message: types.Message):

    if not is_admin(message.from_user.id):
        return await message.reply("❌ Only admin allowed")

    file = await bot.get_file(message.document.file_id)
    file_data = await bot.download_file(file.file_path)

    content = file_data.read().decode()
    reader = csv.reader(io.StringIO(content))

    quiz_id = str(uuid.uuid4())[:8]
    quiz_time = 15 

    cursor.execute("INSERT INTO quizzes VALUES (?, ?, ?)",
                   (quiz_id, message.document.file_name, quiz_time))

    # 🔥 A/B/C/D mapping
    answer_map = {
        "A": 0,
        "B": 1,
        "C": 2,
        "D": 3
    }

    # 🔥 header skip
    next(reader, None)

    for row in reader:

        if len(row) < 6:
            continue

        try:
            ans = row[5].strip().upper()

            if ans not in answer_map:
                print("Invalid answer:", row)
                continue

            correct = answer_map[ans]

            cursor.execute("INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?)", (
                quiz_id,
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                correct
            ))

        except Exception as e:
            print("Row error:", row, e)
            continue

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM questions WHERE quiz_id=?", (quiz_id,))
    total_q = cursor.fetchone()[0]

    text = f"""
✅ Quiz Created

📋 Quiz Name: {message.document.file_name}
❓ Questions: {total_q}
🆔 Quiz ID: {quiz_id}. 👤 Creator: {message.from_user.first_name}
"""

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🚀 Start Quiz", callback_data=f"play_{quiz_id}"))
    kb.add(InlineKeyboardButton(
        "👥 Play in Group",
        url=f"https://t.me/{BOT_USERNAME}?startgroup=quiz_{quiz_id}"
    ))
    kb.add(InlineKeyboardButton(
        "📢 Share Quiz",
        switch_inline_query=f"quiz_{quiz_id}"
    ))

    await message.answer(text, reply_markup=kb)



    #--------------STOP COMMAND-------------------

@dp.message_handler(commands=['stop'])
async def stop_quiz(message: types.Message):

    chat_id = message.chat.id

    # ❌ Only group
    if message.chat.type == "private":
        return await message.reply("❌ This command works only in group")

    # ❌ Only admin
    if not message.from_user.id in ADMIN_IDS:
        return await message.reply("❌ Only admin can stop quiz")

    # ❌ No active quiz
    if chat_id not in active_groups:
        return await message.reply("❌ No active quiz running")

    # 🛑 Stop quiz
    active_groups.remove(chat_id)

    #  Paused Quiz
    paused_groups.discard(chat_id)

    await message.answer("🛑 Quiz Stopped!")

    # 🏁 Show result
    await show_leaderboard(chat_id)

# ---------------------- STOP ALL COMMAND ----------------------------


@dp.message_handler(commands=['stopall'])
async def stop_all(message: types.Message):

    # ❌ Only admin
    if message.from_user.id not in ADMIN_IDS:
        return await message.reply("❌ Only admin can use this")

    # 🔴 Clear all running data
    active_groups.clear()
    paused_groups.clear()
    user_sessions.clear()
    group_sessions.clear()
    group_scores.clear()
    poll_data.clear()

    await message.answer("🛑 ALL QUIZZES STOPPED!\n⚠️ Bot fully reset")

#----------------- PAUSE COMMAND-----------------

@dp.message_handler(commands=['pause'])
async def pause_quiz(message: types.Message):

    chat_id = message.chat.id

    if message.chat.type == "private":
        return await message.reply("❌ Only group")

    if message.from_user.id not in ADMIN_IDS:
        return await message.reply("❌ Only admin")

    if chat_id not in active_groups:
        return await message.reply("❌ No active quiz")

    paused_groups.add(chat_id)

    await message.answer("⏸ Quiz Paused!")

#----------------- RESUME COMMAND ---------------
@dp.message_handler(commands=['resume'])
async def resume_quiz(message: types.Message):

    chat_id = message.chat.id

    if message.chat.type == "private":
        return await message.reply("❌ Only group")

    if message.from_user.id not in ADMIN_IDS:
        return await message.reply("❌ Only admin")

    if chat_id not in paused_groups:
        return await message.reply("❌ Quiz not paused")

    paused_groups.remove(chat_id)

    await message.answer("▶️ Quiz Resumed!")

    await send_group_question(chat_id)

# ---------------- LOAD QUESTIONS ----------------

import random

def get_questions(quiz_id):
    cursor.execute("SELECT * FROM questions WHERE quiz_id=?", (quiz_id,))
    rows = cursor.fetchall()

    questions = []

    for r in rows:

        q_text = r[1]
        options = [r[2], r[3], r[4], r[5]]
        correct_index = int(r[6])

        # 🔥 safety check
        if correct_index not in [0,1,2,3]:
            print("Invalid correct index:", r)
            continue

        correct_option = options[correct_index]

        random.shuffle(options)

        new_correct = options.index(correct_option)

      

        questions.append({
            "q": q_text,
            "options": options,
            "correct": new_correct
        })

    random.shuffle(questions)

    return questions

# ---------------- PRIVATE QUIZ ----------------
@dp.callback_query_handler(lambda c: c.data.startswith("play_"))
async def play(callback: types.CallbackQuery):
    quiz_id = callback.data.split("_")[1]
    await start_private_quiz(callback.from_user.id, quiz_id)

async def start_private_quiz(user_id, quiz_id):
    questions = get_questions(quiz_id)
    user_sessions[user_id] = {
        "quiz_id": quiz_id,
        "index": 0,
        "score": 0,
        "questions": questions
    }

    await bot.send_message(user_id, "🚀 Quiz Started")
    await send_private_question(user_id)



async def send_private_question(user_id):

    # 🛑 Stop check
    if user_id not in user_sessions:
       return
    session = user_sessions[user_id]
    quiz = session["questions"]

    if session["index"] >= len(quiz):
        await bot.send_message(user_id, f"🏁 Finished\nScore: {session['score']}")
        return

    q = quiz[session["index"]]

    poll = await bot.send_poll(
        user_id,
        f"❓ Q{session['index']+1}/{len(quiz)}\n\n{q['q']}",
        q["options"],
        type="quiz",
        correct_option_id=q["correct"],   # ✅ यही सही है
        is_anonymous=False,
        open_period=15
    )

    poll_data[poll.poll.id] = {
        "correct": q["correct"],
        "user_id": user_id
    }

    session["index"] += 1

    await asyncio.sleep(16)
    await send_private_question(user_id)

# ---------------- GROUP QUIZ ----------------
async def start_group_quiz(chat_id, quiz_id):

    # 🔹 Quiz name
    cursor.execute("SELECT name FROM quizzes WHERE quiz_id=?", (quiz_id,))
    data = cursor.fetchone()
    quiz_name = data[0] if data else "Unknown Quiz"

    # 🔹 Questions load
    questions = get_questions(quiz_id)

    total_q = len(questions)
    time_per_q = 15

    group_sessions[chat_id] = {
        "quiz_id": quiz_id,
        "index": 0,
        "questions": questions
    }
    

    group_scores[chat_id] = {}
    active_groups.add(chat_id)


    # 🔥 Intro Message
    text = f"""
🚀 Quiz Started in Group

📋 Quiz Name: {quiz_name}
❓ Total Questions: {total_q}
⏱ Time per Question: {time_per_q} sec

🏆 Get Ready!
🔥 Fastest answer wins
"""

    await bot.send_message(chat_id, text)

    # ⏳ Countdown
    msg = await bot.send_message(chat_id, "⏳ Starting in 3...")
    await asyncio.sleep(1)

    await bot.edit_message_text("⏳ Starting in 2...", chat_id, msg.message_id)
    await asyncio.sleep(1)

    await bot.edit_message_text("⏳ Starting in 1...", chat_id, msg.message_id)
    await asyncio.sleep(1)

    await bot.edit_message_text("🚀 GO!", chat_id, msg.message_id)

    # 🚀 Start quiz
    await send_group_question(chat_id)

async def send_group_question(chat_id):
      
      # 🛑 STOP CHECK

    if chat_id not in active_groups:
        return 
    
      #  ⏸ PAUSE CHECK

    if chat_id in paused_groups:
        return
    
    session = group_sessions[chat_id]
    quiz = session["questions"]

    if session["index"] >= len(quiz):
        await show_leaderboard(chat_id)
        return

    q = quiz[session["index"]]

 

    poll = await bot.send_poll(
        chat_id,
        f"❓ Q{session['index']+1}/{len(quiz)}\n\n{q['q']}",
        q["options"],
        type="quiz",
        correct_option_id=q["correct"],
        is_anonymous=False,
        open_period=15
    )

    poll_data[poll.poll.id] = {
        "correct": q["correct"],
        "chat_id": chat_id
    }

    session["index"] += 1

    await asyncio.sleep(16)
    await send_group_question(chat_id)

# ---------------- ANSWERS ----------------
@dp.poll_answer_handler()
async def handle_answer(poll_answer: types.PollAnswer):
    

    
    uid = poll_answer.user.id
    poll_id = poll_answer.poll_id
    chosen = poll_answer.option_ids[0]

    if poll_id not in poll_data:
        return

    data = poll_data[poll_id]

    if "user_id" in data:
        if chosen == data["correct"]:
            user_sessions[uid]["score"] += 1

    if "chat_id" in data:
        chat_id = data["chat_id"]

        if uid not in group_scores[chat_id]:
            group_scores[chat_id][uid] = {"score": 0}

        if chosen == data["correct"]:
            group_scores[chat_id][uid]["score"] += 1

# ---------------- LEADERBOARD ----------------
async def show_leaderboard(chat_id):
    scores = group_scores.get(chat_id, {})

    if not scores:
        await bot.send_message(chat_id, "❌ No participants")
        return

    # total questions count निकालो
    quiz_id = group_sessions[chat_id]["quiz_id"]
    cursor.execute("SELECT COUNT(*) FROM questions WHERE quiz_id=?", (quiz_id,))
    total_q = cursor.fetchone()[0]

    sorted_users = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)

    text = "🏁 Quiz Finished!\n\n"
    text += f"❓ Total Questions: {total_q}\n\n"

    medals = ["🥇", "🥈", "🥉"]

    for i, (uid, data) in enumerate(sorted_users):
        user = await bot.get_chat(uid)
        rank = medals[i] if i < 3 else f"{i+1}."

        text += f"{rank} {user.first_name} — {data['score']}/{total_q}\n"

    text += "\n🏆 Congratulations!"

    await bot.send_message(chat_id, text)

# ---------------- QUIZ LIST ----------------

@dp.message_handler(commands=['quizzes'])
async def list_quizzes(message: types.Message):

    cursor.execute("SELECT quiz_id, name, time FROM quizzes")
    data = cursor.fetchall()

    if not data:
        return await message.answer("❌ No quizzes found")

    text = "📚 All Quiz Sets\n\n"

    for i, (quiz_id, name, quiz_time) in enumerate(data, start=1):

        name = name.replace(".csv", "")           # ✅ .csv हटाओ

        # total questions count
        cursor.execute("SELECT COUNT(*) FROM questions WHERE quiz_id=?", (quiz_id,))
        total_q = cursor.fetchone()[0]

        text += f"{i}. <b>{name}</b>\n"
        text += f"🖊 {total_q} questions · ⏱️ {quiz_time} · 🔀 all\n"
        text += f"/view_{quiz_id}\n\n"

    await message.answer(text,parse_mode="HTML")

# ----------------- Title Save --------------
@dp.message_handler(lambda message: message.from_user.id in user_sessions and "edit_title" in user_sessions[message.from_user.id])
async def save_new_title(message: types.Message):

    quiz_id = user_sessions[message.from_user.id]["edit_title"]
    new_title = message.text.strip()

    # 🔥 DB update
    cursor.execute("UPDATE quizzes SET name=? WHERE quiz_id=?", (new_title, quiz_id))
    conn.commit()

    # 🧹 session clear
    del user_sessions[message.from_user.id]["edit_title"]

    await message.answer(f"✅ Title updated:\n📋 {new_title}")

    
 # ---------------- VIEW QUIZ ----------------
   
@dp.message_handler(lambda message: message.text.startswith("/view_"))
async def view_quiz(message: types.Message):

    quiz_id = message.text.split("_")[1]

    # quiz data lo
    cursor.execute("SELECT name, time FROM quizzes WHERE quiz_id=?", (quiz_id,))
    data = cursor.fetchone()

    if not data:
        return await message.reply("❌ Quiz not found")

    name, quiz_time = data
    name = name.replace(".csv", "")

    # total questions count
    cursor.execute("SELECT COUNT(*) FROM questions WHERE quiz_id=?", (quiz_id,))
    total_q = cursor.fetchone()[0]

    # creator name (optional safe)
    creator = message.from_user.first_name

    # 🔥 FINAL TEXT FORMAT
    text = f"""
📋 <b>Quiz Name:</b> {name}. ⏱️ <b>Time:</b> {quiz_time} sec

❓ <b>Questions:</b> {total_q}. 🆔 <b>Quiz ID:</b> {quiz_id}

👤 <b>Creator:</b> {creator}. 🔀 <b>Shuffle:</b> ON

"""

    # 🔘 BUTTONS
    kb = InlineKeyboardMarkup()

    kb.add(InlineKeyboardButton("🚀 Start Quiz", url=f"https://t.me/{BOT_USERNAME}?start=quiz_{quiz_id}"))

    kb.add(InlineKeyboardButton("👥 Play in Group",url=f"https://t.me/{BOT_USERNAME}?startgroup=quiz_{quiz_id}"))

    kb.add(InlineKeyboardButton("📢 Share Quiz", switch_inline_query=f"quiz_{quiz_id}"))
   
    kb.add(InlineKeyboardButton("✏️ Edit Quiz",callback_data=f"edit_{quiz_id}"))

    kb.add(
    InlineKeyboardButton(
        "🗑 Delete Quiz",
        callback_data=f"deletequiz_{quiz_id}"
    )
)

    await message.answer(text, reply_markup=kb, parse_mode="HTML")


#----------------- ADD NEW QUESIONS (CSV style input handler) ---------

@dp.message_handler(lambda m: m.from_user.id in user_sessions and "add_q_csv" in user_sessions[m.from_user.id])
async def add_question_csv(message: types.Message):

    quiz_id = user_sessions[message.from_user.id]["add_q_csv"]

    lines = message.text.strip().split("\n")

    added = 0
    skipped = 0

    for line in lines:

        # skip header
        if line.lower().startswith("question"):
            continue

        parts = [x.strip() for x in line.split(",")]

        if len(parts) != 6:
            skipped += 1
            continue

        q, a, b, c, d, ans = parts

        options = [a, b, c, d]

        # 🔥 support A/B/C/D format
        ans = ans.upper()

        if ans in ["A", "B", "C", "D"]:
            correct = ["A", "B", "C", "D"].index(ans)

        elif ans in options:
            correct = options.index(ans)

        else:
            skipped += 1
            continue

        try:
            cursor.execute("INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?)", (
                quiz_id, q, a, b, c, d, correct
            ))
            added += 1

        except:
            skipped += 1

    conn.commit()

    del user_sessions[message.from_user.id]

    await message.answer(
        f"✅ {added} Questions Added Successfully!\n"
        f"⚠️ Skipped: {skipped}"
    )

#----------------- EDIT MENU (callback handler) ------------------

@dp.callback_query_handler(lambda c: c.data.startswith("edit_"))
async def edit_menu(callback: types.CallbackQuery):

    quiz_id = callback.data.split("_")[1]

    kb = InlineKeyboardMarkup()

    kb.add(InlineKeyboardButton("✏️ Edit Questions", callback_data=f"editq_{quiz_id}"))
    kb.add(InlineKeyboardButton("📝 Edit Title", callback_data=f"edit_title_{quiz_id}"))
    kb.add(InlineKeyboardButton("➕ Add Question",callback_data=f"addq_{quiz_id}"))
    kb.add(InlineKeyboardButton("🔙 Back to Quiz", callback_data=f"back_{quiz_id}"))
    
    
    await callback.message.edit_text(
        "⚙️ Edit Menu\n\nSelect what you want to edit:",
        reply_markup=kb
    )

    


@dp.callback_query_handler(lambda c: c.data.startswith("back_"))
async def back_to_quiz(callback: types.CallbackQuery):

    quiz_id = callback.data.split("_")[1]

    cursor.execute("SELECT name, time FROM quizzes WHERE quiz_id=?", (quiz_id,))
    name, quiz_time = cursor.fetchone()

    name = name.replace(".csv", "")

    cursor.execute("SELECT COUNT(*) FROM questions WHERE quiz_id=?", (quiz_id,))
    total_q = cursor.fetchone()[0]

    creator = callback.from_user.first_name

    text = f"""
📋 <b>Quiz Name:</b>{name}. ⏱️ <b>Time: </b>{quiz_time} sec

❓ <b>Questions: </b>{total_q}. 🆔 <b>Quiz ID:</b>{quiz_id}

👤 <b>Creator:</b>{creator}. 🔀 Shuffle: <b>ON</b>
"""

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🚀 Start Quiz", url=f"https://t.me/{BOT_USERNAME}?start=quiz_{quiz_id}"))
    kb.add(InlineKeyboardButton("👥 Play in Group", url=f"https://t.me/{BOT_USERNAME}?startgroup=quiz_{quiz_id}"))
    kb.add(InlineKeyboardButton("📢 Share Quiz", switch_inline_query=f"quiz_{quiz_id}"))
    kb.add(InlineKeyboardButton("✏️ Edit Quiz", callback_data=f"edit_{quiz_id}"))

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# -------------- EDIT QUESTIONS ---------------

# LIST SHOW

@dp.callback_query_handler(lambda c: c.data.startswith("editq_"))
async def edit_questions(callback: types.CallbackQuery):

    quiz_id = callback.data.split("_")[1]

    page = 0
    await show_question_page(callback.message, quiz_id, page)



async def show_question_page(message, quiz_id, page):

    cursor.execute("SELECT rowid, question FROM questions WHERE quiz_id=?", (quiz_id,))
    questions = cursor.fetchall()

    per_page = 10
    start = page * per_page
    end = start + per_page

    page_questions = questions[start:end]

    if not page_questions:
        return await message.answer("❌ No questions found!")

    keyboard = InlineKeyboardMarkup()

    for qid, qtext in page_questions:
        keyboard.add(
            InlineKeyboardButton(
                qtext[:40],
                callback_data=f"qview_{qid}"
            )
        )

    nav = []

    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"page_{quiz_id}_{page-1}"))

    if end < len(questions):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"page_{quiz_id}_{page+1}"))

    if nav:
        keyboard.row(*nav)

    await message.answer(f"📋 Questions (Page {page+1})", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith("page_"))
async def change_page(callback: types.CallbackQuery):

    _, quiz_id, page = callback.data.split("_")
    page = int(page)

    await show_question_page(callback.message, quiz_id, page)

# QUESTION VIEW (DELETE BUTTON SHOW)

@dp.callback_query_handler(lambda c: c.data.startswith("qview_"))
async def view_question(callback: types.CallbackQuery):

    qid = callback.data.split("_")[1]

    cursor.execute("SELECT * FROM questions WHERE rowid=?", (qid,))
    data = cursor.fetchone()

    if not data:
        return await callback.message.answer("❌ Question not found!")

    quiz_id, q, a, b, c, d, correct = data

    options = [a, b, c, d]

    text = f"❓ {q}\n\n"
    for i, opt in enumerate(options):
        mark = "✅" if i == correct else ""
        text += f"{chr(65+i)}. {opt} {mark}\n"

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("🗑 Delete", callback_data=f"delq_{qid}")
    )

    await callback.message.answer(text, reply_markup=keyboard)

# DELETE CONFIRM 

@dp.callback_query_handler(lambda c: c.data.startswith("delq_"))
async def delete_confirm(callback: types.CallbackQuery):

    qid = callback.data.split("_")[1]

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("✅ Yes Delete", callback_data=f"confirmdel_{qid}"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel")
    )

    await callback.message.answer("⚠️ Are you sure?", reply_markup=keyboard)

# FINAL DELETE

@dp.callback_query_handler(lambda c: c.data.startswith("confirmdel_"))
async def delete_question(callback: types.CallbackQuery):

    qid = callback.data.split("_")[1]

    cursor.execute("DELETE FROM questions WHERE rowid=?", (qid,))
    conn.commit()

    cursor.execute("SELECT quiz_id FROM questions WHERE rowid=?", (qid,))
    row = cursor.fetchone()
    quiz_id = row[0] if row else None

    await callback.message.answer("🗑 Question Deleted Successfully!")

    await show_question_page(callback.message, quiz_id, 0)

# CANCEL BUTTON

@dp.callback_query_handler(lambda c: c.data == "cancel")
async def cancel_action(callback: types.CallbackQuery):
    await callback.message.answer("❌ Cancelled")

# permanent Delete Confirmation Handler

@dp.callback_query_handler(lambda c: c.data.startswith("deletequiz_"))
async def delete_quiz_confirm(callback: types.CallbackQuery):

    quiz_id = callback.data.split("_", 1)[1]

    # Quiz name fetch
    cursor.execute(
        "SELECT name FROM quizzes WHERE quiz_id=?",
        (quiz_id,)
    )

    row = cursor.fetchone()

    if not row:
        return await callback.answer("❌ Quiz not found", show_alert=True)

    quiz_name = row[0]

    kb = InlineKeyboardMarkup(row_width=1)

    kb.add(
        InlineKeyboardButton(
            "✅ Yes, Delete Permanently",
            callback_data=f"confirmdelete_{quiz_id}"
        )
    )

    kb.add(
        InlineKeyboardButton(
            "❌ Cancel",
            callback_data="cancel_delete"
        )
    )

    await callback.message.edit_text(
        f"⚠️ WARNING!\n\n"
        f"📚 Quiz: {quiz_name}\n\n"
        f"🗑 This will permanently delete the quiz and all questions.\n\n"
        f"❗ This action cannot be undone.",
        reply_markup=kb
    )

# Permanent Delete Handler

@dp.callback_query_handler(lambda c: c.data.startswith("confirmdelete_"))
async def confirm_delete_quiz(callback: types.CallbackQuery):

    quiz_id = callback.data.split("_", 1)[1]

    # Delete all questions
    cursor.execute(
        "DELETE FROM questions WHERE quiz_id=?",
        (quiz_id,)
    )

    # Delete quiz
    cursor.execute(
        "DELETE FROM quizzes WHERE quiz_id=?",
        (quiz_id,)
    )

    conn.commit()

    await callback.message.edit_text(
        "✅ Quiz permanently deleted."
    )

# Cancel Handler

@dp.callback_query_handler(lambda c: c.data == "cancel_delete")
async def cancel_delete(callback: types.CallbackQuery):

    await callback.answer("Cancelled")

    await callback.message.edit_text(
        "❌ Quiz deletion cancelled."
    )

# ---------------ADD QUESTION ------------------

@dp.callback_query_handler(lambda c: c.data.startswith("addq_"))
async def add_question(callback: types.CallbackQuery):

    quiz_id = callback.data.split("_")[1]

    user_sessions[callback.from_user.id] = {
        "add_q_csv": quiz_id
    }

    await callback.message.answer(
        "📥 Send question in this format:\n\n"
        "question, option1, option2, option3, option4, answer\n\n"
        "Example 1:\nWhat is 2+2, 1, 2, 3, 4, 4"

        "Example 2:\nभारत की राजधानी कहां है?, पटना, जयपुर, दिल्ली, मुम्बई, C"          
    )

# ---------------- INLINE SHARE ----------------
@dp.inline_handler()
async def inline_handler(query: types.InlineQuery):
    text = query.query.strip()

    if not text.startswith("quiz_"):
        return

    quiz_id = text.split("_")[1]

    cursor.execute("SELECT name FROM quizzes WHERE quiz_id=?", (quiz_id,))
    data = cursor.fetchone()

    if not data:
        return

    name = data[0]

    cursor.execute("SELECT COUNT(*) FROM questions WHERE quiz_id=?", (quiz_id,))
    total_q = cursor.fetchone()[0]

    message_text = f"""
📊 Quiz Name: {name}

❓ {total_q} Questions
🆔 ID: quiz_{quiz_id}
"""

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        "🚀 Start Quiz",
        url=f"https://t.me/{BOT_USERNAME}?start=quiz_{quiz_id}"
    ))
    kb.add(InlineKeyboardButton(
        "👥 Play in Group",
        url=f"https://t.me/{BOT_USERNAME}?startgroup=quiz_{quiz_id}"
    ))
    kb.add(InlineKeyboardButton(
        "📢 Share Quiz",
        switch_inline_query=f"quiz_{quiz_id}"
    ))

    result = types.InlineQueryResultArticle(
        id=quiz_id,
        title=name,
        description=f"{total_q} Questions",
        input_message_content=types.InputTextMessageContent(message_text),
        reply_markup=kb
    )

    await query.answer([result], cache_time=1)


# ---------------- RUN ----------------
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(auto_backup())
    executor.start_polling(dp, skip_updates=True)