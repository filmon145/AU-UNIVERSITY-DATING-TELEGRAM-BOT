import sys
import asyncio
import aiosqlite
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, ConversationHandler, filters, CallbackQueryHandler
)

# Define conversation states
(NAME, GENDER, CAMPUS, PHOTO, BIO, HOBBIES, PREFERENCE, REVIEW, 
 EDIT_CHOICE, EDIT_NAME, EDIT_GENDER, EDIT_CAMPUS, 
 EDIT_PHOTO, EDIT_BIO, EDIT_HOBBIES, REPORT_REASON) = range(16)

DB_PATH = "au_dating_bot.db"
CHANNEL_USERNAME = "@AmboU_confession"  # Your channel username
ADMIN_USER_ID = 7719239133  # Replace with your Telegram user ID

# ---------------- Database ----------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Users table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            name TEXT, gender TEXT, campus TEXT, 
            photo_file_id TEXT, bio TEXT, hobbies TEXT, 
            preference TEXT DEFAULT 'Both',
            is_banned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Swipes table
        await db.execute("CREATE TABLE IF NOT EXISTS swipes (liker_id INTEGER, liked_id INTEGER, UNIQUE(liker_id, liked_id))")
        
        # Active chats table
        await db.execute("CREATE TABLE IF NOT EXISTS active_chats (user_id INTEGER PRIMARY KEY, partner_id INTEGER)")
        
        # Chat requests table (for reconnect permission)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS chat_requests (
            id INTEGER PRIMARY KEY,
            requester_id INTEGER,
            requested_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Reports table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY,
            reporter_id INTEGER,
            reported_id INTEGER,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Channel check table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS channel_checks (
            user_id INTEGER PRIMARY KEY,
            has_joined INTEGER DEFAULT 0,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        
        await db.commit()

async def save_profile(update, context):
    user = update.effective_user
    if not user:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO users 
            (telegram_id, username, name, gender, campus, photo_file_id, bio, hobbies, preference) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user.id,
                user.username,
                context.user_data.get('name'),
                context.user_data.get('gender'),
                context.user_data.get('campus'),
                context.user_data.get('photo_file_id'),
                context.user_data.get('bio'),
                context.user_data.get('hobbies'),
                context.user_data.get('preference', 'Both')
            )
        )
        await db.commit()

# ---------------- Channel Check ----------------
async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is a member of the required channel"""
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Error checking channel membership: {e}")
        return False

async def update_channel_check(user_id: int, has_joined: bool):
    """Update channel check status in database"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO channel_checks (user_id, has_joined, checked_at) 
            VALUES (?, ?, CURRENT_TIMESTAMP)""",
            (user_id, 1 if has_joined else 0)
        )
        await db.commit()

# ---------------- Start ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if user is banned
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row and row[0] == 1:
                await update.message.reply_text("❌ You have been banned from using this bot.")
                return ConversationHandler.END
    
    # Always check channel membership first
    has_joined = await check_channel_membership(user_id, context)
    await update_channel_check(user_id, has_joined)
    
    if not has_joined:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("✅ I've Joined", callback_data="check_channel")]
        ])
        message_text = (
            "<b>📢 WELCOME TO AU DATING BOT!</b>\n\n"
            "<b>🔒 ACCESS RESTRICTED</b>\n\n"
            "To use this bot, you must join our official channel:\n"
            f"<code>{CHANNEL_USERNAME}</code>\n\n"
            "<b>👉 STEPS TO CONTINUE:</b>\n"
            "1. Click 'Join Channel' below\n"
            "2. Join the channel\n"
            "3. Come back here\n"
            "4. Click 'I've Joined'\n\n"
            "After joining, you can create your profile and start matching! 💖"
        )
        await update.message.reply_text(
            message_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return ConversationHandler.END
    
    # User has joined channel, continue with normal flow
    # Check if user is already in a chat
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            chat_row = await cur.fetchone()
            if chat_row:
                await update.message.reply_text("❌ You are currently in a chat. Please use /stop to end your current conversation before starting a new registration.")
                return ConversationHandler.END
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            user = await cur.fetchone()
    
    if user:
        await update.message.reply_text(
            f"Welcome back, {user[0]}! 🤗\n\n"
            f"Use /find to meet people or /settings to change preferences.\n"
            f"Use /report to report inappropriate behavior.",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        "<b>🎉 WELCOME TO AU DATING BOT!</b>\n\n"
        "Let's create your profile. First, what's your name or nickname?",
        parse_mode="HTML"
    )
    return NAME

async def check_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle channel join check callback"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    has_joined = await check_channel_membership(user_id, context)
    await update_channel_check(user_id, has_joined)
    
    if has_joined:
        # User has joined, now check if they have a profile
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as cur:
                user = await cur.fetchone()
        
        if user:
            # Existing user
            await query.edit_message_text(
                f"<b>✅ WELCOME BACK, {user[0]}! 🤗</b>\n\n"
                f"You're all set! Use the commands below:\n"
                f"• /find - Meet new people\n"
                f"• /myprofile - View your profile\n"
                f"• /settings - Change preferences\n"
                f"• /report - Report inappropriate behavior\n\n"
                f"Happy matching! 💖",
                parse_mode="HTML",
                reply_markup=get_main_menu()
            )
        else:
            # New user, start registration
            await query.edit_message_text(
                "<b>✅ CHANNEL VERIFIED! 🎉</b>\n\n"
                "Welcome to AU Dating Bot!\n\n"
                "Let's create your profile. First, what's your name or nickname?",
                parse_mode="HTML"
            )
            # Send a new message to trigger the conversation handler
            await context.bot.send_message(
                chat_id=user_id,
                text="What's your name or nickname?",
                parse_mode="HTML"
            )
            # We can't directly return NAME from callback, so we'll handle it differently
            return ConversationHandler.END
    else:
        # User hasn't joined yet
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("✅ I've Joined", callback_data="check_channel")]
        ])
        await query.edit_message_text(
            f"<b>❌ YOU HAVEN'T JOINED THE CHANNEL YET!</b>\n\n"
            f"I can't see you in {CHANNEL_USERNAME}\n\n"
            f"<b>PLEASE MAKE SURE:</b>\n"
            f"1. You clicked the link\n"
            f"2. You pressed 'Join' in Telegram\n"
            f"3. Wait a few seconds\n"
            f"4. Try 'I've Joined' again\n\n"
            f"If you're having issues, try restarting Telegram.",
            parse_mode="HTML",
            reply_markup=keyboard
        )

# ---------------- Input Handlers ----------------
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text:
        await update.message.reply_text("❌ Please enter your name or nickname in text format.")
        return NAME
    name = update.message.text.strip()
    if len(name) > 100:
        await update.message.reply_text("❌ Name too long! Max 100 characters.")
        return NAME
    context.user_data['name'] = name

    keyboard = [[InlineKeyboardButton("Male", callback_data="Male"),
                 InlineKeyboardButton("Female", callback_data="Female")]]
    await update.message.reply_text("What's your gender?", reply_markup=InlineKeyboardMarkup(keyboard))
    return GENDER

async def get_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['gender'] = query.data

    keyboard = [
        [InlineKeyboardButton("Main Campus", callback_data="Main Campus")],
        [InlineKeyboardButton("Woliso Campus", callback_data="Woliso Campus")],
        [InlineKeyboardButton("HHC", callback_data="HHC")],
        [InlineKeyboardButton("Guder Mamo Mezemir Campus", callback_data="Guder Mamo Mezemir Campus")]
    ]
    await query.edit_message_text("Which campus is your second home? 📍", reply_markup=InlineKeyboardMarkup(keyboard))
    return CAMPUS

async def get_campus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['campus'] = query.data

    keyboard = [[InlineKeyboardButton("Skip", callback_data="skip")]]
    await query.edit_message_text("Send your profile picture 📸 or press Skip", reply_markup=InlineKeyboardMarkup(keyboard))
    return PHOTO

async def get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "skip":
        context.user_data['photo_file_id'] = None
        return await ask_bio(update, context)

    if update.message.photo:
        context.user_data['photo_file_id'] = update.message.photo[-1].file_id
        return await ask_bio(update, context)

    await update.message.reply_text("Please send a photo or press Skip.")
    return PHOTO

async def ask_bio(update, context):
    keyboard = [[InlineKeyboardButton("Skip", callback_data="skip")]]
    if update.callback_query:
        await update.callback_query.edit_message_text("Set your bio 📝 (or press Skip)", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("Set your bio 📝 (or press Skip)", reply_markup=InlineKeyboardMarkup(keyboard))
    return BIO

async def get_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "skip":
        context.user_data['bio'] = None
    elif update.message and update.message.text:
        bio = update.message.text.strip()
        if len(bio) > 300:
            await update.message.reply_text("❌ Bio too long! Max 300 characters.")
            return BIO
        context.user_data['bio'] = bio
    else:
        await update.message.reply_text("❌ Please enter text or press Skip.")
        return BIO

    keyboard = [[InlineKeyboardButton("Skip", callback_data="skip")]]
    if update.callback_query:
        await update.callback_query.edit_message_text("Set your hobbies 🏀🎨 (or press Skip)", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text("Set your hobbies 🏀🎨 (or press Skip)", reply_markup=InlineKeyboardMarkup(keyboard))
    return HOBBIES

# ---------------- Registration End & Preference ----------------
async def get_hobbies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "skip":
        context.user_data['hobbies'] = None
    elif update.message and update.message.text:
        context.user_data['hobbies'] = update.message.text.strip()
    
    keyboard = [
        [InlineKeyboardButton("Males 👨", callback_data="pref_Male")],
        [InlineKeyboardButton("Females 👩", callback_data="pref_Female")],
        [InlineKeyboardButton("Both 🌈", callback_data="pref_Both")]
    ]
    text = "Who are you interested in meeting?"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    return PREFERENCE

async def get_preference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['preference'] = query.data.replace("pref_", "")
    return await show_profile(update, context)

# ---------------- Show Profile ----------------
async def show_profile(update, context):
    name = context.user_data.get('name')
    gender = context.user_data.get('gender')
    campus = context.user_data.get('campus')
    bio = context.user_data.get('bio') or "Not set"
    hobbies = context.user_data.get('hobbies') or "Not set"
    photo_id = context.user_data.get('photo_file_id')

    profile_text = (
        "<b>✨ CHECK OUT YOUR PROFILE! ✨</b>\n\n"
        f"<b>👤 Name:</b> {name}\n"
        f"<b>⚧ Gender:</b> {gender}\n"
        f"<b>📍 Campus:</b> {campus}\n"
        f"<b>📝 Bio:</b> {bio}\n"
        f"<b>🎯 Hobbies:</b> {hobbies}\n\n"
        "<b>✅ Confirm to save or ✏️ Edit to fix something.</b>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Edit ✏️", callback_data="edit_profile")],
        [InlineKeyboardButton("Confirm ✅", callback_data="confirm")]
    ])
    
    if update.callback_query:
        query = update.callback_query
        if query.message.photo:
            await query.edit_message_caption(
                caption=profile_text, 
                reply_markup=keyboard, 
                parse_mode="HTML"
            )
        else:
            if photo_id:
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id, 
                    photo=photo_id, 
                    caption=profile_text, 
                    reply_markup=keyboard, 
                    parse_mode="HTML"
                )
            else:
                await query.edit_message_text(
                    text=profile_text, 
                    reply_markup=keyboard, 
                    parse_mode="HTML"
                )
    else:
        if photo_id:
            await update.message.reply_photo(
                photo=photo_id, 
                caption=profile_text, 
                reply_markup=keyboard, 
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                profile_text, 
                reply_markup=keyboard, 
                parse_mode="HTML"
            )
    return REVIEW

# ---------------- Review / Edit ----------------
async def review_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        await save_profile(update, context)
        
        # Clear any editing context
        if 'editing' in context.user_data:
            context.user_data.pop('editing', None)
        
        # Clear the message reply markup
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except:
            pass  # If there's no markup, just continue
        
        welcome_text = (
            "🎉 Registration Complete!\n\n"
            "You can now use the menu buttons below to find people."
        )
        await query.message.reply_text(
            text=welcome_text, 
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END

    elif query.data == "edit_profile":
        # Set editing flag
        context.user_data['editing'] = True
        
        keyboard = [
            [InlineKeyboardButton("Name", callback_data="edit_name"),
             InlineKeyboardButton("Gender", callback_data="edit_gender")],
            [InlineKeyboardButton("Campus", callback_data="edit_campus"),
             InlineKeyboardButton("Photo", callback_data="edit_photo")],
            [InlineKeyboardButton("Bio", callback_data="edit_bio"),
             InlineKeyboardButton("Hobbies", callback_data="edit_hobbies")]
        ]
        edit_markup = InlineKeyboardMarkup(keyboard)
        text = "🔧 Which part do you want to edit?"
        
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=edit_markup)
        else:
            await query.edit_message_text(text=text, reply_markup=edit_markup)
        
        return EDIT_CHOICE

# ---------------- Edit Choice ----------------
async def edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    
    prompts = {
        "edit_name": "📝 Send me your new Name:",
        "edit_gender": "⚧ Pick your Gender:",
        "edit_campus": "📍 Pick your Campus:",
        "edit_photo": "📸 Upload a new Photo:",
        "edit_bio": "📝 Send me your new Bio:",
        "edit_hobbies": "🎯 Send me your new Hobbies:"
    }
    
    text = prompts.get(choice, "What would you like to edit?")
    keyboard = None

    if choice == "edit_gender":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Male", callback_data="Male"), InlineKeyboardButton("Female", callback_data="Female")]])
    elif choice == "edit_campus":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Main", callback_data="Main Campus")],
            [InlineKeyboardButton("Woliso", callback_data="Woliso Campus")],
            [InlineKeyboardButton("HHC", callback_data="HHC")],
            [InlineKeyboardButton("Guder", callback_data="Guder Mamo Mezemir Campus")]
        ])
    elif choice in ["edit_photo", "edit_bio", "edit_hobbies"]:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Skip", callback_data="skip")]])

    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=keyboard)
    else:
        await query.edit_message_text(text=text, reply_markup=keyboard)

    state_map = {
        "edit_name": EDIT_NAME, "edit_gender": EDIT_GENDER,
        "edit_campus": EDIT_CAMPUS, "edit_photo": EDIT_PHOTO,
        "edit_bio": EDIT_BIO, "edit_hobbies": EDIT_HOBBIES
    }
    return state_map.get(choice)

# ---------------- Edit Inputs ----------------
async def edit_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text:
        await update.message.reply_text("❌ Please send a valid name.")
        return EDIT_NAME
    context.user_data['name'] = update.message.text.strip()
    return await show_profile(update, context)

async def edit_gender_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['gender'] = query.data
    return await show_profile(update, context)

async def edit_campus_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['campus'] = query.data
    return await show_profile(update, context)

async def edit_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.data == "skip":
            context.user_data['photo_file_id'] = None
        return await show_profile(update, context)

    if update.message.photo:
        context.user_data['photo_file_id'] = update.message.photo[-1].file_id
        return await show_profile(update, context)
    
    await update.message.reply_text("Please send a photo 📸 or press Skip")
    return EDIT_PHOTO

async def edit_bio_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "skip":
            context.user_data['bio'] = None
        return await show_profile(update, context)

    if update.message and update.message.text:
        context.user_data['bio'] = update.message.text.strip()
        return await show_profile(update, context)
    
    await update.message.reply_text("❌ Please send text or press Skip.")
    return EDIT_BIO

async def edit_hobbies_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.data == "skip":
            context.user_data['hobbies'] = None
        return await show_profile(update, context)

    if update.message and update.message.text:
        context.user_data['hobbies'] = update.message.text.strip()
        return await show_profile(update, context)
    
    await update.message.reply_text("❌ Please send text or press Skip.")
    return EDIT_HOBBIES

# ---------------- Cancel ----------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled. Use /start to begin again.")
    return ConversationHandler.END

# ---------------- Main Menu ----------------
def get_main_menu():
    """Get main menu without matches button"""
    keyboard = [
        ["🔥 Find Matches", "👤 My Profile"],
        ["⚙️ Settings", "📢 Report User"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------------- Report System ----------------
async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start report process"""
    user_id = update.effective_user.id
    
    # Check if user is in a chat
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            chat_row = await cur.fetchone()
            if chat_row:
                partner_id = chat_row[0]
                context.user_data['reporting_user_id'] = partner_id
                
                await update.message.reply_text(
                    "<b>⚠️ REPORTING USER</b>\n\n"
                    "You are about to report the user you're currently chatting with.\n"
                    "Please describe the reason for your report:",
                    parse_mode="HTML"
                )
                return REPORT_REASON
    
    await update.message.reply_text(
        "<b>📢 REPORT A USER</b>\n\n"
        "To report a user, please use this command:\n"
        "/report <user_id> <reason>\n\n"
        "Or if you're in a chat with someone, just use /report and describe the issue.",
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get report reason and process it"""
    reason = update.message.text.strip()
    user_id = update.effective_user.id
    reported_id = context.user_data.get('reporting_user_id')
    
    if not reported_id:
        await update.message.reply_text("❌ Could not identify the user to report.")
        return ConversationHandler.END
    
    if len(reason) > 500:
        await update.message.reply_text("❌ Reason too long! Max 500 characters.")
        return REPORT_REASON
    
    # Save report to database
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, ?)",
            (user_id, reported_id, reason)
        )
        await db.commit()
    
    # Notify admin
    admin_message = (
        f"<b>🚨 NEW USER REPORT</b>\n\n"
        f"<b>👤 Reporter:</b> {user_id}\n"
        f"<b>⚠️ Reported User:</b> {reported_id}\n"
        f"<b>📝 Reason:</b> {reason}\n\n"
        f"Use /admin to review this report."
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID, 
            text=admin_message, 
            parse_mode="HTML"
        )
    except:
        pass
    
    await update.message.reply_text(
        "✅ Thank you for your report. We will review it and take appropriate action.\n\n"
        "If this was an emergency, please contact the administration directly."
    )
    return ConversationHandler.END

# ---------------- Profile Management ----------------
async def set_preference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if user is in a chat
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            chat_row = await cur.fetchone()
            if chat_row:
                await update.message.reply_text("❌ You are currently in a chat. Please use /stop to end your current conversation before changing settings.")
                return
    
    keyboard = [
        [InlineKeyboardButton("Show Males 👨", callback_data="pref_Male")],
        [InlineKeyboardButton("Show Females 👩", callback_data="pref_Female")],
        [InlineKeyboardButton("Show Both ", callback_data="pref_Both")]
    ]
    await update.message.reply_text("Who do you want to meet?", reply_markup=InlineKeyboardMarkup(keyboard))

async def save_preference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pref = query.data.replace("pref_", "")
    user_id = query.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET preference = ? WHERE telegram_id = ?", (pref, user_id))
        await db.commit()

    await query.answer()
    await query.edit_message_text(f"✅ Preference updated! I will now show you: {pref}")

async def find_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if user is banned
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row and row[0] == 1:
                text = "❌ You have been banned from using this bot."
                if update.callback_query:
                    await update.callback_query.message.reply_text(text)
                else:
                    await update.message.reply_text(text)
                return
    
    # Check if user is in a chat
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            chat_row = await cur.fetchone()
            if chat_row:
                text = "❌ You are currently in a chat. Please use /stop to end your current conversation before finding new matches."
                if update.callback_query:
                    await update.callback_query.message.reply_text(text)
                else:
                    await update.message.reply_text(text)
                return
    
    is_callback = update.callback_query is not None
    user_id = update.effective_user.id
    
    if is_callback:
        await update.callback_query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT preference FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                text = "❌ Create a profile first using /start."
                if is_callback:
                    await update.callback_query.message.reply_text(text)
                else:
                    await update.message.reply_text(text)
                return
            
            pref = row[0]

        # Don't show banned users
        if pref == "Both":
            gender_condition = "gender IN ('Male', 'Female') AND is_banned = 0"
            params = (user_id, user_id)
        else:
            gender_condition = "gender = ? AND is_banned = 0"
            params = (pref, user_id, user_id)

        query = f"""
        SELECT telegram_id, name, campus, bio, photo_file_id
        FROM users
        WHERE {gender_condition}
        AND telegram_id != ?
        AND telegram_id NOT IN (
            SELECT liked_id FROM swipes WHERE liker_id = ?
        )
        ORDER BY RANDOM()
        LIMIT 1
        """
        
        async with db.execute(query, params) as cur:
            match = await cur.fetchone()

    if not match:
        text = f"😔 No new profiles matching your preference ({pref}) right now."
        if is_callback:
            if update.callback_query.message.photo:
                await update.callback_query.edit_message_caption(caption=text)
            else:
                await update.callback_query.edit_message_text(text=text)
        else:
            await update.message.reply_text(text)
        return

    match_id, name, campus, bio, photo = match
    text = f"🔥 New Profile\n👤 {name}\n📍 {campus}\n📝 {bio or 'No bio'}"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Like", callback_data=f"like_{match_id}"),
         InlineKeyboardButton("➡️ Next", callback_data="find_next")],
        [InlineKeyboardButton("🚫 Report", callback_data=f"report_{match_id}")]
    ])

    if is_callback:
        try:
            await update.callback_query.message.delete()
            if photo:
                await context.bot.send_photo(chat_id=user_id, photo=photo, caption=text, reply_markup=keyboard)
            else:
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        except:
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
    else:
        if photo:
            await update.message.reply_photo(photo=photo, caption=text, reply_markup=keyboard)
        else:
            await update.message.reply_text(text, reply_markup=keyboard)

async def handle_like(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if user is banned
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_banned FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row and row[0] == 1:
                await update.callback_query.answer("❌ You have been banned from using this bot.")
                return
    
    # Check if user is in a chat
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            chat_row = await cur.fetchone()
            if chat_row:
                await update.callback_query.answer("❌ You are currently in a chat. Please use /stop to end your current conversation before liking new profiles.")
                return
    
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("report_"):
        # Handle report from profile view
        reported_id = int(query.data.split('_')[1])
        context.user_data['reporting_user_id'] = reported_id
        
        await query.edit_message_caption(caption="⚠️ Please describe the reason for reporting this user:")
        return REPORT_REASON
    
    user_id = update.effective_user.id 
    liked_id = int(query.data.split('_')[1]) 

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO swipes (liker_id, liked_id) VALUES (?, ?)", (user_id, liked_id))
        await db.commit()

        async with db.execute("SELECT 1 FROM swipes WHERE liker_id = ? AND liked_id = ?", (liked_id, user_id)) as cur:
            is_match = await cur.fetchone()

        async with db.execute("SELECT name, photo_file_id FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            me = await cur.fetchone()

    if is_match:
        match_alert = "<b>🎆 BOOM! IT'S A MATCH! 🎆</b>\n\nYou both liked each other! Don't wait, say hi! 👋"
        
        # Check if the matched user is in a chat
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (liked_id,)) as cur:
                liked_user_chat = await cur.fetchone()
                if liked_user_chat:
                    # Notify the liker that the other user is busy
                    await query.message.reply_text("🎯 You have a match! However, your match is currently in another conversation. Try again later!")
                    return await find_match(update, context)
        
        await context.bot.send_message(
            chat_id=liked_id, 
            text=f"{match_alert}\n\nMatched with: {me[0]}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Send Message", callback_data=f"chat_{user_id}")]])
        )
        
        await query.message.reply_text(
            text=match_alert,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Start Chatting", callback_data=f"chat_{liked_id}")]])
        )
    else:
        await query.edit_message_caption(caption="⚡ Like sent! Looking for more...")
        
        try:
            caption = f"<b>🔥 SOMEONE LIKED YOU!</b>\n\n👤 {me[0]} just swiped right. Swipe /find to see who it is!"
            if me[1]:
                await context.bot.send_photo(
                    chat_id=liked_id, 
                    photo=me[1], 
                    caption=caption, 
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💖 Like Back", callback_data=f"like_{user_id}")]])
                )
            else:
                await context.bot.send_message(
                    chat_id=liked_id, 
                    text=caption, 
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💖 Like Back", callback_data=f"like_{user_id}")]])
                )
        except: 
            pass

    return await find_match(update, context)

async def show_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, gender, campus, bio, hobbies, photo_file_id FROM users WHERE telegram_id = ?", 
            (user_id,)
        ) as cur:
            user = await cur.fetchone()

    if not user:
        await update.message.reply_text("❌ You don't have a profile yet! Type /start.")
        return

    name, gender, campus, bio, hobbies, photo_id = user
    
    profile_text = (
        "<b>👤 YOUR PROFILE</b>\n\n"
        f"<b>✨ Name:</b> {name}\n"
        f"<b>⚧ Gender:</b> {gender}\n"
        f"<b>📍 Campus:</b> {campus}\n"
        f"<b>📝 Bio:</b> {bio or 'Not set'}\n"
        f"<b>🎯 Hobbies:</b> {hobbies or 'Not set'}"
    )

    # Use start_edit_profile callback for existing profile edit
    keyboard = [[InlineKeyboardButton("Edit Profile ✏️", callback_data="start_edit_profile")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if photo_id:
        await update.message.reply_photo(
            photo=photo_id, 
            caption=profile_text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            profile_text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )

# ---------------- Edit Profile System (Outside Conversation) ----------------
async def start_edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start editing profile from existing profile view"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Load existing profile data into context.user_data for editing
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, gender, campus, photo_file_id, bio, hobbies, preference FROM users WHERE telegram_id = ?", 
            (user_id,)
        ) as cur:
            user = await cur.fetchone()
    
    if user:
        name, gender, campus, photo_id, bio, hobbies, preference = user
        context.user_data['name'] = name
        context.user_data['gender'] = gender
        context.user_data['campus'] = campus
        context.user_data['photo_file_id'] = photo_id
        context.user_data['bio'] = bio
        context.user_data['hobbies'] = hobbies
        context.user_data['preference'] = preference
        context.user_data['editing_existing'] = True  # Flag to indicate editing existing profile
    
    # Show edit menu
    keyboard = [
        [InlineKeyboardButton("Name", callback_data="edit_name_existing"),
         InlineKeyboardButton("Gender", callback_data="edit_gender_existing")],
        [InlineKeyboardButton("Campus", callback_data="edit_campus_existing"),
         InlineKeyboardButton("Photo", callback_data="edit_photo_existing")],
        [InlineKeyboardButton("Bio", callback_data="edit_bio_existing"),
         InlineKeyboardButton("Hobbies", callback_data="edit_hobbies_existing")],
        [InlineKeyboardButton("✅ Done Editing", callback_data="finish_edit")]
    ]
    
    try:
        if query.message.photo:
            await query.edit_message_caption(
                caption="<b>🔧 EDIT YOUR PROFILE</b>\n\nWhich part do you want to edit?",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                "<b>🔧 EDIT YOUR PROFILE</b>\n\nWhich part do you want to edit?",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        print(f"Error in start_edit_profile: {e}")
        # Send a new message if editing fails
        await context.bot.send_message(
            chat_id=user_id,
            text="<b>🔧 EDIT YOUR PROFILE</b>\n\nWhich part do you want to edit?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_edit_existing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle edit choices for existing profile"""
    query = update.callback_query
    await query.answer()
    
    choice = query.data.replace("_existing", "")
    
    prompts = {
        "edit_name": "📝 Send me your new Name (text message):",
        "edit_gender": "⚧ Pick your Gender:",
        "edit_campus": "📍 Pick your Campus:",
        "edit_photo": "📸 Upload a new Photo (send as photo) or click Skip:",
        "edit_bio": "📝 Send me your new Bio (text message) or click Skip:",
        "edit_hobbies": "🎯 Send me your new Hobbies (text message) or click Skip:"
    }
    
    text = prompts.get(choice, "What would you like to edit?")
    keyboard = None

    if choice == "edit_gender":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Male", callback_data="save_gender_Male"), InlineKeyboardButton("Female", callback_data="save_gender_Female")]])
    elif choice == "edit_campus":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Main Campus", callback_data="save_campus_Main Campus")],
            [InlineKeyboardButton("Woliso Campus", callback_data="save_campus_Woliso Campus")],
            [InlineKeyboardButton("HHC", callback_data="save_campus_HHC")],
            [InlineKeyboardButton("Guder Mamo Mezemir Campus", callback_data="save_campus_Guder Mamo Mezemir Campus")]
        ])
    elif choice in ["edit_photo", "edit_bio", "edit_hobbies"]:
        field = choice.replace("edit_", "")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Skip", callback_data=f"skip_{field}")]])
    
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=keyboard)
        else:
            await query.edit_message_text(text=text, reply_markup=keyboard)
    except Exception as e:
        print(f"Error editing message: {e}")
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=text,
            reply_markup=keyboard
        )

async def handle_save_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save edited field and return to edit menu"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if query.data.startswith("save_gender_"):
        gender = query.data.replace("save_gender_", "")
        context.user_data['gender'] = gender
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET gender = ? WHERE telegram_id = ?", (gender, user_id))
            await db.commit()
        
    elif query.data.startswith("save_campus_"):
        campus = query.data.replace("save_campus_", "")
        context.user_data['campus'] = campus
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET campus = ? WHERE telegram_id = ?", (campus, user_id))
            await db.commit()
        
    elif query.data.startswith("skip_"):
        field = query.data.replace("skip_", "")
        if field == "photo":
            context.user_data['photo_file_id'] = None
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET photo_file_id = NULL WHERE telegram_id = ?", (user_id,))
                await db.commit()
        elif field == "bio":
            context.user_data['bio'] = None
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET bio = NULL WHERE telegram_id = ?", (user_id,))
                await db.commit()
        elif field == "hobbies":
            context.user_data['hobbies'] = None
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET hobbies = NULL WHERE telegram_id = ?", (user_id,))
                await db.commit()
    
    # Return to edit menu
    keyboard = [
        [InlineKeyboardButton("Name", callback_data="edit_name_existing"),
         InlineKeyboardButton("Gender", callback_data="edit_gender_existing")],
        [InlineKeyboardButton("Campus", callback_data="edit_campus_existing"),
         InlineKeyboardButton("Photo", callback_data="edit_photo_existing")],
        [InlineKeyboardButton("Bio", callback_data="edit_bio_existing"),
         InlineKeyboardButton("Hobbies", callback_data="edit_hobbies_existing")],
        [InlineKeyboardButton("✅ Done Editing", callback_data="finish_edit")]
    ]
    
    try:
        await query.edit_message_text(
            "✅ Updated! What else would you like to edit?\n\nOr click 'Done Editing' to finish.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except:
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ Updated! What else would you like to edit?\n\nOr click 'Done Editing' to finish.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_text_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text edits for name, bio, hobbies from existing profile"""
    user_id = update.effective_user.id
    
    # Check if we're in edit mode
    if 'editing_existing' not in context.user_data:
        # Not in edit mode, check if user is in chat
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
                chat_row = await cur.fetchone()
                if chat_row:
                    # User is in chat, relay message instead
                    await chat_relay(update, context)
                    return
        
        # Not in chat, not editing - ignore or show help
        # Check if user has a profile
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as cur:
                has_profile = await cur.fetchone()
        
        if has_profile:
            # User has profile but not editing, show profile
            await show_my_profile(update, context)
        else:
            # User doesn't have profile
            await update.message.reply_text("❌ You don't have a profile yet! Use /start to create one.")
        return
    
    text = update.message.text.strip()
    
    if not text:
        await update.message.reply_text("❌ Please enter valid text.")
        return
    
    # Determine which field is being edited based on context
    # We need to track the last edit action
    field = None
    
    # Check if we can determine the field from context
    if 'last_edit_field' in context.user_data:
        field = context.user_data['last_edit_field']
    else:
        # Try to guess based on text length
        if len(text) < 50:  # Likely a name
            field = 'name'
        else:  # Likely a bio or hobbies
            field = 'bio'
    
    if not field:
        await update.message.reply_text("❌ I'm not sure what you're editing. Please use the edit buttons.")
        return
    
    # Save to context
    context.user_data[field] = text
    
    # Save to database
    async with aiosqlite.connect(DB_PATH) as db:
        update_query = f"UPDATE users SET {field} = ? WHERE telegram_id = ?"
        await db.execute(update_query, (text, user_id))
        await db.commit()
    
    # Show edit menu again
    keyboard = [
        [InlineKeyboardButton("Name", callback_data="edit_name_existing"),
         InlineKeyboardButton("Gender", callback_data="edit_gender_existing")],
        [InlineKeyboardButton("Campus", callback_data="edit_campus_existing"),
         InlineKeyboardButton("Photo", callback_data="edit_photo_existing")],
        [InlineKeyboardButton("Bio", callback_data="edit_bio_existing"),
         InlineKeyboardButton("Hobbies", callback_data="edit_hobbies_existing")],
        [InlineKeyboardButton("✅ Done Editing", callback_data="finish_edit")]
    ]
    
    await update.message.reply_text(
        f"✅ {field.capitalize()} updated! What else would you like to edit?\n\nOr click 'Done Editing' to finish.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_photo_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo edit from existing profile"""
    user_id = update.effective_user.id
    
    # Check if we're in edit mode
    if 'editing_existing' not in context.user_data:
        # Check if user is in chat
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
                chat_row = await cur.fetchone()
                if chat_row:
                    # User is in chat, relay photo instead
                    await photo_relay(update, context)
                    return
        return
    
    if update.message.photo:
        context.user_data['photo_file_id'] = update.message.photo[-1].file_id
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET photo_file_id = ? WHERE telegram_id = ?",
                (context.user_data['photo_file_id'], user_id)
            )
            await db.commit()
        
        # Show edit menu again
        keyboard = [
            [InlineKeyboardButton("Name", callback_data="edit_name_existing"),
             InlineKeyboardButton("Gender", callback_data="edit_gender_existing")],
            [InlineKeyboardButton("Campus", callback_data="edit_campus_existing"),
             InlineKeyboardButton("Photo", callback_data="edit_photo_existing")],
            [InlineKeyboardButton("Bio", callback_data="edit_bio_existing"),
             InlineKeyboardButton("Hobbies", callback_data="edit_hobbies_existing")],
            [InlineKeyboardButton("✅ Done Editing", callback_data="finish_edit")]
        ]
        
        await update.message.reply_text(
            "✅ Photo updated! What else would you like to edit?\n\nOr click 'Done Editing' to finish.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def finish_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish editing and return to profile view"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Clear editing flag
    context.user_data.pop('editing_existing', None)
    context.user_data.pop('last_edit_field', None)
    
    # Show updated profile
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, gender, campus, bio, hobbies, photo_file_id FROM users WHERE telegram_id = ?", 
            (user_id,)
        ) as cur:
            user = await cur.fetchone()

    if user:
        name, gender, campus, bio, hobbies, photo_id = user
        
        profile_text = (
            "<b>👤 YOUR PROFILE (UPDATED)</b>\n\n"
            f"<b>✨ Name:</b> {name}\n"
            f"<b>⚧ Gender:</b> {gender}\n"
            f"<b>📍 Campus:</b> {campus}\n"
            f"<b>📝 Bio:</b> {bio or 'Not set'}\n"
            f"<b>🎯 Hobbies:</b> {hobbies or 'Not set'}"
        )

        keyboard = [[InlineKeyboardButton("Edit Profile ✏️", callback_data="start_edit_profile")]]
        
        try:
            # Check if the original message had a photo
            if query.message.photo:
                # If original had photo, edit the caption
                await query.edit_message_caption(
                    caption=profile_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                # If original was text, edit the text
                await query.edit_message_text(
                    profile_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        except Exception as e:
            print(f"Error in finish_edit: {e}")
            # Send new message if editing fails
            if photo_id:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo_id,
                    caption=profile_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=profile_text,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

# ---------------- Admin Panel ----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to access this command.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 View All Users", callback_data="admin_users")],
        [InlineKeyboardButton("🚫 Banned Users", callback_data="admin_banned")],
        [InlineKeyboardButton("🚨 Reports", callback_data="admin_reports")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔍 Search User", callback_data="admin_search")]
    ]
    
    await update.message.reply_text(
        "<b>🔧 ADMIN PANEL</b>\n\n"
        "Select an option below:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics"""
    query = update.callback_query
    await query.answer()
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Total users
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]
        
        # Active users (created in last 7 days)
        async with db.execute("SELECT COUNT(*) FROM users WHERE created_at > datetime('now', '-7 days')") as cur:
            active_users = (await cur.fetchone())[0]
        
        # Banned users
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1") as cur:
            banned_users = (await cur.fetchone())[0]
        
        # Total matches
        async with db.execute("""
            SELECT COUNT(*) FROM (
                SELECT s1.liker_id, s1.liked_id 
                FROM swipes s1
                INNER JOIN swipes s2 ON s1.liker_id = s2.liked_id AND s1.liked_id = s2.liker_id
                WHERE s1.liker_id < s1.liked_id
            )
        """) as cur:
            total_matches = (await cur.fetchone())[0]
        
        # Total reports
        async with db.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'") as cur:
            pending_reports = (await cur.fetchone())[0]
        
        # Active chats
        async with db.execute("SELECT COUNT(*) FROM active_chats") as cur:
            active_chats = (await cur.fetchone())[0]
    
    stats_text = (
        f"<b>📊 BOT STATISTICS</b>\n\n"
        f"<b>👥 Total Users:</b> {total_users}\n"
        f"<b>📈 Active Users (7 days):</b> {active_users}\n"
        f"<b>🚫 Banned Users:</b> {banned_users}\n"
        f"<b>💖 Total Matches:</b> {total_matches}\n"
        f"<b>🚨 Pending Reports:</b> {pending_reports}\n"
        f"<b>💬 Active Chats:</b> {active_chats}\n\n"
        f"<b>📅 Last updated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]
    await query.edit_message_text(stats_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all users"""
    query = update.callback_query
    await query.answer()
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT telegram_id, username, name, campus, created_at 
            FROM users 
            WHERE is_banned = 0 
            ORDER BY created_at DESC 
            LIMIT 50
        """) as cur:
            users = await cur.fetchall()
    
    if not users:
        await query.edit_message_text("No users found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]))
        return
    
    users_text = "<b>👥 RECENT USERS</b>\n\n"
    for i, user in enumerate(users, 1):
        user_id, username, name, campus, created_at = user
        users_text += f"{i}. {name} (@{username or 'No username'})\n"
        users_text += f"   <b>ID:</b> {user_id} | <b>Campus:</b> {campus}\n"
        users_text += f"   <b>Joined:</b> {created_at[:10]}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]
    await query.edit_message_text(users_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending reports"""
    query = update.callback_query
    await query.answer()
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT r.id, r.reporter_id, r.reported_id, r.reason, r.created_at,
                   u1.name as reporter_name, u2.name as reported_name
            FROM reports r
            LEFT JOIN users u1 ON r.reporter_id = u1.telegram_id
            LEFT JOIN users u2 ON r.reported_id = u2.telegram_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
            LIMIT 20
        """) as cur:
            reports = await cur.fetchall()
    
    if not reports:
        await query.edit_message_text("No pending reports.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]))
        return
    
    reports_text = "<b>🚨 PENDING REPORTS</b>\n\n"
    for report in reports:
        report_id, reporter_id, reported_id, reason, created_at, reporter_name, reported_name = report
        reports_text += f"<b>📝 Report #{report_id}</b>\n"
        reports_text += f"<b>👤 Reporter:</b> {reporter_name} (ID: {reporter_id})\n"
        reports_text += f"<b>⚠️ Reported:</b> {reported_name} (ID: {reported_id})\n"
        reports_text += f"<b>📄 Reason:</b> {reason[:100]}...\n"
        reports_text += f"<b>📅 Date:</b> {created_at[:10]}\n"
        
        # Add action buttons for this report
        keyboard = [
            [
                InlineKeyboardButton(f"✅ Approve #{report_id}", callback_data=f"approve_{report_id}"),
                InlineKeyboardButton(f"❌ Reject #{report_id}", callback_data=f"reject_{report_id}")
            ],
            [
                InlineKeyboardButton(f"👁️ View #{reported_id}", callback_data=f"view_{reported_id}"),
                InlineKeyboardButton(f"🚫 Ban #{reported_id}", callback_data=f"ban_{reported_id}")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ]
        
        await query.edit_message_text(reports_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]
    await query.edit_message_text(reports_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle report actions"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = ADMIN_USER_ID
    
    if data.startswith("approve_"):
        report_id = int(data.split('_')[1])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE reports SET status = 'approved' WHERE id = ?", (report_id,))
            await db.commit()
        await query.answer("✅ Report approved!")
        
    elif data.startswith("reject_"):
        report_id = int(data.split('_')[1])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE reports SET status = 'rejected' WHERE id = ?", (report_id,))
            await db.commit()
        await query.answer("❌ Report rejected!")
        
    elif data.startswith("ban_"):
        banned_id = int(data.split('_')[1])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (banned_id,))
            await db.commit()
            
            # End any active chats for this user
            await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (banned_id, banned_id))
            await db.commit()
        
        await query.answer(f"✅ User {banned_id} has been banned!")
        
        # Notify the banned user
        try:
            await context.bot.send_message(
                chat_id=banned_id,
                text="❌ You have been banned from using AU Dating Bot due to violating our community guidelines."
            )
        except:
            pass
    
    elif data.startswith("view_"):
        user_to_view = int(data.split('_')[1])
        await view_user_profile(update, context, user_to_view)
        return
    
    # Go back to reports list
    await admin_reports(update, context)

async def view_user_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """View a specific user's profile (admin function)"""
    query = update.callback_query
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT name, gender, campus, bio, hobbies, photo_file_id, username, created_at, is_banned
            FROM users WHERE telegram_id = ?
        """, (user_id,)) as cur:
            user = await cur.fetchone()
    
    if not user:
        await query.edit_message_text("User not found.")
        return
    
    name, gender, campus, bio, hobbies, photo_id, username, created_at, is_banned = user
    
    profile_text = (
        f"<b>👤 USER PROFILE</b>\n\n"
        f"<b>✨ Name:</b> {name}\n"
        f"<b>⚧ Gender:</b> {gender}\n"
        f"<b>📍 Campus:</b> {campus}\n"
        f"<b>📝 Bio:</b> {bio or 'No bio'}\n"
        f"<b>🎯 Hobbies:</b> {hobbies or 'No hobbies'}\n"
        f"<b>👤 Username:</b> @{username or 'No username'}\n"
        f"<b>🆔 User ID:</b> {user_id}\n"
        f"<b>📅 Joined:</b> {created_at[:10]}\n"
        f"<b>🚫 Status:</b> {'Banned' if is_banned else 'Active'}\n"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_{user_id}"),
            InlineKeyboardButton("✅ Unban User", callback_data=f"unban_{user_id}")
        ],
        [InlineKeyboardButton("🔙 Back to Reports", callback_data="admin_reports")]
    ]
    
    if photo_id:
        await query.message.delete()
        await context.bot.send_photo(
            chat_id=ADMIN_USER_ID,
            photo=photo_id,
            caption=profile_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(
            profile_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broadcast process"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "<b>📢 BROADCAST MESSAGE</b>\n\n"
        "Please send the message you want to broadcast to all users.\n"
        "You can include text, photos, or documents.\n\n"
        "Type /cancel to abort.",
        parse_mode="HTML"
    )
    
    # Set context for broadcast
    context.user_data['broadcasting'] = True

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast message from admin"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        return
    
    if 'broadcasting' not in context.user_data:
        return
    
    # Get all active users (not banned)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT telegram_id FROM users WHERE is_banned = 0") as cur:
            users = await cur.fetchall()
    
    total_users = len(users)
    successful = 0
    failed = 0
    
    # Send to each user
    for user in users:
        try:
            if update.message.text:
                await context.bot.send_message(
                    chat_id=user[0],
                    text=f"<b>📢 Announcement from Admin</b>\n\n{update.message.text}",
                    parse_mode="HTML"
                )
            elif update.message.photo:
                await context.bot.send_photo(
                    chat_id=user[0],
                    photo=update.message.photo[-1].file_id,
                    caption=f"<b>📢 Announcement from Admin</b>\n\n{update.message.caption or ''}",
                    parse_mode="HTML"
                )
            elif update.message.document:
                await context.bot.send_document(
                    chat_id=user[0],
                    document=update.message.document.file_id,
                    caption=f"<b>📢 Announcement from Admin</b>\n\n{update.message.caption or ''}",
                    parse_mode="HTML"
                )
            successful += 1
        except Exception as e:
            failed += 1
            print(f"Failed to send to {user[0]}: {e}")
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.1)
    
    # Clear broadcasting state
    context.user_data.pop('broadcasting', None)
    
    await update.message.reply_text(
        f"✅ Broadcast completed!\n\n"
        f"📤 Sent to: {successful} users\n"
        f"❌ Failed: {failed} users\n"
        f"👥 Total: {total_users} users"
    )

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to admin panel"""
    query = update.callback_query
    await query.answer()
    await admin_panel(update, context)

# ---------------- Chat System with Permission ----------------
async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    partner_id = int(query.data.split('_')[1])
    
    # Check if user is already in a chat
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            existing_chat = await cur.fetchone()
            if existing_chat:
                await query.message.reply_text("❌ You are already in a chat! Use /stop to end your current conversation before starting a new one.")
                return
        
        # Check if there's a pending request from this user to this partner
        async with db.execute("""
            SELECT id FROM chat_requests 
            WHERE requester_id = ? AND requested_id = ? AND status = 'pending'
        """, (partner_id, user_id)) as cur:
            pending_request = await cur.fetchone()
            
        if pending_request:
            # Partner already requested to chat with this user
            await db.execute("DELETE FROM chat_requests WHERE id = ?", (pending_request[0],))
            await db.commit()
            # Allow the chat to proceed
        else:
            # Check if partner is already in a chat
            async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (partner_id,)) as cur:
                partner_chat = await cur.fetchone()
                if partner_chat:
                    # Create a chat request
                    await db.execute(
                        "INSERT INTO chat_requests (requester_id, requested_id) VALUES (?, ?)",
                        (user_id, partner_id)
                    )
                    await db.commit()
                    
                    # Notify the partner about the request
                    try:
                        await context.bot.send_message(
                            chat_id=partner_id,
                            text=f"<b>💬 Chat Request</b>\n\n"
                                 f"Someone wants to chat with you! Use /requests to view pending requests.",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                    
                    await query.message.reply_text(
                        "📨 Chat request sent! The other user will be notified.\n"
                        "You can check your pending requests with /requests."
                    )
                    return

        # Clear any old active chats for both users
        await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (user_id, user_id))
        await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (partner_id, partner_id))
        
        # Create the new connection (Both ways)
        await db.execute("INSERT INTO active_chats (user_id, partner_id) VALUES (?, ?)", (user_id, partner_id))
        await db.execute("INSERT INTO active_chats (user_id, partner_id) VALUES (?, ?)", (partner_id, user_id))
        await db.commit()

        # Get names for personalization
        async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (partner_id,)) as cur:
            row = await cur.fetchone()
            partner_name = row[0] if row else "your match"
        
        async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            row_me = await cur.fetchone()
            my_name = row_me[0] if row_me else "Someone"

    ice_breaker = (
        "<b>🎬 THE STAGE IS YOURS!</b>\n\n"
        "You are now connected. Don't be shy—start with a 'Hi' or your favorite emoji! 🥂\n\n"
        "<i>💡 Type /stop at any time to end this chat.</i>"
    )

    msg_text = f"<b>✅ CONNECTION ESTABLISHED WITH {partner_name}!</b>\n\n{ice_breaker}"
    if query.message.photo:
        await query.edit_message_caption(caption=msg_text, parse_mode="HTML")
    else:
        await query.edit_message_text(text=msg_text, parse_mode="HTML")
    
    try:
        partner_alert = (
            f"<b>🎆 BOOM! You are now chatting with {my_name}!</b>\n\n"
            f"{ice_breaker}"
        )
        await context.bot.send_message(
            chat_id=partner_id,
            text=partner_alert,
            parse_mode="HTML"
        )
    except:
        pass

async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View pending chat requests"""
    user_id = update.effective_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT cr.id, cr.requester_id, u.name, u.campus
            FROM chat_requests cr
            JOIN users u ON cr.requester_id = u.telegram_id
            WHERE cr.requested_id = ? AND cr.status = 'pending'
            ORDER BY cr.created_at DESC
        """, (user_id,)) as cur:
            requests = await cur.fetchall()
    
    if not requests:
        await update.message.reply_text("You have no pending chat requests.")
        return
    
    keyboard = []
    for req in requests:
        req_id, requester_id, name, campus = req
        keyboard.append([
            InlineKeyboardButton(f"✅ Accept {name}", callback_data=f"accept_{req_id}"),
            InlineKeyboardButton(f"❌ Decline {name}", callback_data=f"decline_{req_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🗑️ Clear All", callback_data="clear_requests")])
    
    await update.message.reply_text(
        "<b>📨 PENDING CHAT REQUESTS</b>\n\n"
        "You have pending requests to chat. Accept or decline below:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_request_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle chat request actions"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data.startswith("accept_"):
        req_id = int(data.split('_')[1])
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Get request details
            async with db.execute("""
                SELECT requester_id FROM chat_requests WHERE id = ? AND requested_id = ?
            """, (req_id, user_id)) as cur:
                request = await cur.fetchone()
            
            if request:
                requester_id = request[0]
                
                # Update request status
                await db.execute("UPDATE chat_requests SET status = 'accepted' WHERE id = ?", (req_id,))
                
                # Start the chat
                await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (user_id, user_id))
                await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (requester_id, requester_id))
                
                await db.execute("INSERT INTO active_chats (user_id, partner_id) VALUES (?, ?)", (user_id, requester_id))
                await db.execute("INSERT INTO active_chats (user_id, partner_id) VALUES (?, ?)", (requester_id, user_id))
                await db.commit()
                
                # Get names
                async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (requester_id,)) as cur:
                    requester_name = (await cur.fetchone())[0]
                
                async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as cur:
                    my_name = (await cur.fetchone())[0]
                
                ice_breaker = (
                    "<b>🎬 THE STAGE IS YOURS!</b>\n\n"
                    "You are now connected. Don't be shy—start with a 'Hi' or your favorite emoji! 🥂\n\n"
                    "<i>💡 Type /stop at any time to end this chat.</i>"
                )
                
                # Notify both users
                await query.edit_message_text(
                    f"<b>✅ CHAT STARTED WITH {requester_name}!</b>\n\n{ice_breaker}",
                    parse_mode="HTML"
                )
                
                try:
                    await context.bot.send_message(
                        chat_id=requester_id,
                        text=f"<b>✅ YOUR CHAT REQUEST WAS ACCEPTED!</b>\n\n"
                             f"You are now connected with {my_name}!\n\n{ice_breaker}",
                        parse_mode="HTML"
                    )
                except:
                    pass
    
    elif data.startswith("decline_"):
        req_id = int(data.split('_')[1])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE chat_requests SET status = 'declined' WHERE id = ?", (req_id,))
            await db.commit()
        await query.answer("❌ Request declined!")
        await query.edit_message_text("Request declined.")
    
    elif data == "clear_requests":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM chat_requests WHERE requested_id = ? AND status = 'pending'", (user_id,))
            await db.commit()
        await query.answer("🗑️ All requests cleared!")
        await query.edit_message_text("All pending requests have been cleared.")

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = None
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Get partner_id before deleting
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row:
                partner_id = row[0]
        
        # Delete chat connections
        await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (user_id, user_id))
        await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (partner_id, partner_id))
        await db.commit()
        
        # Create a chat request if partner wants to reconnect
        if partner_id:
            await db.execute(
                "INSERT INTO chat_requests (requester_id, requested_id, status) VALUES (?, ?, 'pending')",
                (partner_id, user_id)
            )
            await db.commit()
    
    # Notify the partner if they exist
    if partner_id:
        try:
            await context.bot.send_message(
                chat_id=partner_id,
                text="<b>❌ YOUR CHAT PARTNER HAS ENDED THE CONVERSATION.</b>\n\n"
                     "If you want to reconnect, they will need to accept your new request.\n"
                     "Use /requests to manage reconnection requests."
            )
        except:
            pass
    
    await update.message.reply_text("📴 Chat ended. The other user will need your permission to reconnect.")

# ---------------- Chat Relay Functions ----------------
async def chat_relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        
        if row:
            partner_id = row[0]
            async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as name_cur:
                name_row = await name_cur.fetchone()
                sender_name = name_row[0] if name_row else "User"

            try:
                await context.bot.send_message(
                    chat_id=partner_id, 
                    text=f"💬 {sender_name}: {update.message.text}"
                )
            except Exception:
                # Cleanup if the partner blocked the bot or disappeared
                await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (user_id, user_id))
                await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (partner_id, partner_id))
                await db.commit()
                await update.message.reply_text("❌ Your partner is no longer available. Chat ended.")

async def photo_relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relay photos between matched users in active chat"""
    user_id = update.effective_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if user is in an active chat
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            
        if row:
            partner_id = row[0]
            
            # Get sender's name
            async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as name_cur:
                name_row = await name_cur.fetchone()
                sender_name = name_row[0] if name_row else "User"
            
            # Send photo to partner
            try:
                await context.bot.send_photo(
                    chat_id=partner_id,
                    photo=update.message.photo[-1].file_id,
                    caption=f"📷 Photo from {sender_name}"
                )
            except Exception as e:
                print(f"Error sending photo: {e}")
                # Clean up if partner is unavailable
                await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (user_id, user_id))
                await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (partner_id, partner_id))
                await db.commit()
                await update.message.reply_text("❌ Your partner is no longer available. Chat ended.")

# ---------------- Main Application Setup ----------------
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        GENDER: [CallbackQueryHandler(get_gender)],
        CAMPUS: [CallbackQueryHandler(get_campus)],
        PHOTO: [MessageHandler(filters.PHOTO, get_photo), CallbackQueryHandler(get_photo, pattern="^skip$")],
        BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bio), CallbackQueryHandler(get_bio, pattern="^skip$")],
        HOBBIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hobbies), CallbackQueryHandler(get_hobbies, pattern="^skip$")],
        PREFERENCE: [CallbackQueryHandler(get_preference, pattern="^pref_")],
        REVIEW: [CallbackQueryHandler(review_profile, pattern="^(confirm|edit_profile)$")],
        EDIT_CHOICE: [CallbackQueryHandler(edit_choice, pattern="^edit_(name|gender|campus|photo|bio|hobbies)$")],
        EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_input)],
        EDIT_GENDER: [CallbackQueryHandler(edit_gender_input)],
        EDIT_CAMPUS: [CallbackQueryHandler(edit_campus_input)],
        EDIT_PHOTO: [MessageHandler(filters.PHOTO, edit_photo_input), CallbackQueryHandler(edit_photo_input, pattern="^skip$")],
        EDIT_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bio_input), CallbackQueryHandler(edit_bio_input, pattern="^skip$")],
        EDIT_HOBBIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_hobbies_input), CallbackQueryHandler(edit_hobbies_input, pattern="^skip$")],
        REPORT_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_reason)]
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    per_message=False
)

if __name__ == "__main__":
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    app = ApplicationBuilder().token("8598994507:AAEnbvlFGyS2gZs4mkLzbCeYk6NtbyN8ZVM").build()

    # 1. Conversation Handler
    app.add_handler(conv_handler)

    # 2. Command Handlers
    app.add_handler(CommandHandler("find", find_match))
    app.add_handler(CommandHandler("myprofile", show_my_profile))
    app.add_handler(CommandHandler("settings", set_preference))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("report", report_user))
    app.add_handler(CommandHandler("requests", view_requests))
    app.add_handler(CommandHandler("admin", admin_panel))

    # 3. Callback Query Handlers
    app.add_handler(CallbackQueryHandler(handle_like, pattern="^(like_|report_)"))
    app.add_handler(CallbackQueryHandler(start_chat, pattern="^chat_"))
    app.add_handler(CallbackQueryHandler(find_match, pattern="find_next"))
    app.add_handler(CallbackQueryHandler(save_preference, pattern="^pref_"))
    app.add_handler(CallbackQueryHandler(start_edit_profile, pattern="^start_edit_profile$"))
    app.add_handler(CallbackQueryHandler(handle_edit_existing, pattern="^edit_(name|gender|campus|photo|bio|hobbies)_existing$"))
    app.add_handler(CallbackQueryHandler(handle_save_edit, pattern="^(save_gender_|save_campus_|skip_photo|skip_bio|skip_hobbies)$"))
    app.add_handler(CallbackQueryHandler(finish_edit, pattern="^finish_edit$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_reports, pattern="^admin_reports$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_handle_report, pattern="^(approve_|reject_|ban_|unban_|view_)"))
    app.add_handler(CallbackQueryHandler(handle_request_action, pattern="^(accept_|decline_|clear_requests)"))
    app.add_handler(CallbackQueryHandler(check_channel_callback, pattern="^check_channel$"))

    # 4. Main Menu Button Handlers
    app.add_handler(MessageHandler(filters.Regex("^🔥 Find Matches$"), find_match))
    app.add_handler(MessageHandler(filters.Regex("^👤 My Profile$"), show_my_profile))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Settings$"), set_preference))
    app.add_handler(MessageHandler(filters.Regex("^📢 Report User$"), report_user))

    # 5. Edit Profile Text Handlers (Add these BEFORE the general text handlers)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_edit))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_edit))

    # 6. Message Relays (MUST be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_relay))
    app.add_handler(MessageHandler(filters.PHOTO, photo_relay))
    
    # 7. Admin broadcast handler
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL, handle_broadcast_message))

    print("✅ AU Dating Bot is running! Press Ctrl+C to stop.")
    app.run_polling()
