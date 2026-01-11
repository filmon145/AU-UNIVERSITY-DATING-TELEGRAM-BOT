import sys
import asyncio
import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, ConversationHandler, filters, CallbackQueryHandler
)
(NAME, GENDER, CAMPUS, PHOTO, BIO, HOBBIES, PREFERENCE, REVIEW, 
 EDIT_CHOICE, EDIT_NAME, EDIT_GENDER, EDIT_CAMPUS, 
 EDIT_PHOTO, EDIT_BIO, EDIT_HOBBIES) = range(15)

DB_PATH = "au_dating_bot.db"
# ---------------- Database ----------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE,
            name TEXT, gender TEXT, campus TEXT, 
            photo_file_id TEXT, bio TEXT, hobbies TEXT, 
            preference TEXT DEFAULT 'Both'
        )""")
        await db.execute("CREATE TABLE IF NOT EXISTS swipes (liker_id INTEGER, liked_id INTEGER, UNIQUE(liker_id, liked_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS active_chats (user_id INTEGER PRIMARY KEY, partner_id INTEGER)")
        await db.commit()

async def save_profile(update, context):
    # Use effective_user to safely get the ID from either a message or a button click
    user = update.effective_user
    if not user:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO users 
            (telegram_id, name, gender, campus, photo_file_id, bio, hobbies, preference) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user.id,
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

# ---------------- Start ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            user = await cur.fetchone()
    
    if user:
        await update.message.reply_text(f"Welcome back, {user[0]}! Use /find to meet people or /settings to change preferences.")
        return ConversationHandler.END # Stop the registration from starting
    
    await update.message.reply_text("Welcome! Let's create your profile. What's your name?")
    return NAME

# ---------------- Input Handlers ----------------
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text:
        await update.message.reply_text("❌ Please enter your name in text format.")
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
    # Fix 1: Properly saving preference and bridging to show_profile
    context.user_data['preference'] = query.data.replace("pref_", "")
    return await show_profile(update, context)

# ---------------- Show Profile (Fixing Photo Crash) ----------------

async def show_profile(update, context):
    name = context.user_data.get('name')
    gender = context.user_data.get('gender')
    campus = context.user_data.get('campus')
    bio = context.user_data.get('bio') or "Not set"
    hobbies = context.user_data.get('hobbies') or "Not set"
    photo_id = context.user_data.get('photo_file_id')

    profile_text = (
        f"✨ *Check out your profile!* ✨\n\n"
        f"👤 Name: {name}\n"
        f"⚧ Gender: {gender}\n"
        f"📍 Campus: {campus}\n"
        f"📝 Bio: {bio}\n"
        f"🎯 Hobbies: {hobbies}\n\n"
        "✅ Confirm to save or ✏️ Edit to fix something."
    )

    keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("Edit ✏️", callback_data="edit_profile")],
    [InlineKeyboardButton("Confirm ✅", callback_data="confirm")]
])
    # Fix 2: Safety check to prevent bot from crashing when photo_id is None
    if update.callback_query:
        query = update.callback_query
        if query.message.photo:
            await query.edit_message_caption(caption=profile_text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            if photo_id:
                await query.message.delete()
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_id, caption=profile_text, reply_markup=keyboard, parse_mode="Markdown")
            else:
                await query.edit_message_text(text=profile_text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        if photo_id:
            await update.message.reply_photo(photo=photo_id, caption=profile_text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await update.message.reply_text(profile_text, reply_markup=keyboard, parse_mode="Markdown")
    return REVIEW

# ---------------- Review / Edit ----------------
async def review_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        # 1. Save to DB
        await save_profile(update, context)
        
        # 2. Cleanup: Remove the Inline buttons
        await query.edit_message_reply_markup(reply_markup=None)
        
        # 3. Send success message
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
        # Merged logic: Define buttons and send the menu
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
    
    # Fix 3: Added missing Gender, Campus, and Hobbies logic to Edit Choice
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
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Main", callback_data="Main Campus"), InlineKeyboardButton("Woliso", callback_data="Woliso Campus")], [InlineKeyboardButton("HHC", callback_data="HHC"), InlineKeyboardButton("Guder", callback_data="Guder Campus")]])
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
    if update.message.text.lower() != "keep":
        context.user_data['name'] = update.message.text
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
    # Check if they clicked the "Skip" button
    if update.callback_query:
        await update.callback_query.answer()
        return await show_profile(update, context)

    # If they sent a photo
    if update.message.photo:
        context.user_data['photo_file_id'] = update.message.photo[-1].file_id
        return await show_profile(update, context)
    
    await update.message.reply_text("Please send a photo 📸 or press Skip")
    return EDIT_PHOTO

async def edit_bio_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # If they clicked "Skip"
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        return await show_profile(update, context)

    # If they sent text
    if update.message and update.message.text:
        context.user_data['bio'] = update.message.text
        return await show_profile(update, context)
    
    await update.message.reply_text("❌ Please send text or press Skip.")
    return EDIT_BIO

async def edit_hobbies_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if they clicked the "Skip" button
    if update.callback_query:
        await update.callback_query.answer()
        return await show_profile(update, context)

    if update.message and update.message.text:
        context.user_data['hobbies'] = update.message.text
        return await show_profile(update, context)
    
    await update.message.reply_text("❌ Please send text or press Skip.")
    return EDIT_HOBBIES

# ---------------- Cancel ----------------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled. Use /start to begin again.")
    return ConversationHandler.END





# --- Add these anywhere in the middle of your script with your other functions ---

async def set_preference(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    # Determine if this was called by a command (/find) or a button click (Next)
    is_callback = update.callback_query is not None
    user_id = update.effective_user.id
    
    if is_callback:
        await update.callback_query.answer()

    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Get user's saved preference from the database
        async with db.execute("SELECT preference FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                text = "❌ Create a profile first using /start."
                if is_callback:
                    await update.callback_query.message.reply_text(text)
                else:
                    await update.message.reply_text(text)
                return
            
            pref = row[0]  # This will be 'Male', 'Female', or 'Both'

        # 2. Build the SQL query based on the preference
        if pref == "Both":
            gender_condition = "gender IN ('Male', 'Female')"
            params = (user_id, user_id)
        else:
            gender_condition = "gender = ?"
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

    # 3. Handle the result (Same as before but handles the "Next" button click correctly)
    if not match:
        text = f"😔 No new profiles matching your preference ({pref}) right now."
        if is_callback:
            # Check if message has photo to edit correctly
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
         InlineKeyboardButton("➡️ Next", callback_data="find_next")]
    ])

    if is_callback:
        try:
            # Clean up the old message and send the new one
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
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id 
    liked_id = int(query.data.split('_')[1]) 

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO swipes (liker_id, liked_id) VALUES (?, ?)", (user_id, liked_id))
        await db.commit()

        # Check for mutual match
        async with db.execute("SELECT 1 FROM swipes WHERE liker_id = ? AND liked_id = ?", (liked_id, user_id)) as cur:
            is_match = await cur.fetchone()

        # Get data to notify the other person
        async with db.execute("SELECT name, photo_file_id FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            me = await cur.fetchone()

    if is_match:
        match_alert = "🎆 *BOOM! IT'S A MATCH!* 🎆\n\nYou both liked each other! Don't wait, say hi! 👋"
        
        # Notify the Liked person
        await context.bot.send_message(
            chat_id=liked_id, 
            text=f"{match_alert}\n\nMatched with: {me[0]}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Send Message", callback_data=f"chat_{user_id}")]])
        )
        # Notify the Liker
        await query.message.reply_text(
            text=match_alert,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Start Chatting", callback_data=f"chat_{liked_id}")]])
        )
    else:
        # Just a normal like - Notify the sender and then notify the receiver
        await query.edit_message_caption(caption="⚡ Like sent! Looking for more...")
        
        try:
            caption = f"🔥 *Someone liked you!*\n\n👤 {me[0]} just swiped right. Swipe /find to see who it is!"
            if me[1]: # if has photo
                await context.bot.send_photo(chat_id=liked_id, photo=me[1], caption=caption, 
                                             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💖 Like Back", callback_data=f"like_{user_id}")]]))
            else:
                await context.bot.send_message(chat_id=liked_id, text=caption, 
                                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💖 Like Back", callback_data=f"like_{user_id}")]]))
        except: pass

    return await find_match(update, context)


async def show_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Fetch data from the database, NOT from context.user_data
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
        f"👤 *YOUR PROFILE*\n\n"
        f"✨ Name: {name}\n"
        f"⚧ Gender: {gender}\n"
        f"📍 Campus: {campus}\n"
        f"📝 Bio: {bio}\n"
        f"🎯 Hobbies: {hobbies}"
    )

    # We use callback_data="edit" so the button works with your existing edit logic
    keyboard = [[InlineKeyboardButton("Edit Profile ✏️", callback_data="edit_profile")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if photo_id:
        await update.message.reply_photo(
            photo=photo_id, 
            caption=profile_text, 
            parse_mode="Markdown", 
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            profile_text, 
            parse_mode="Markdown", 
            reply_markup=reply_markup
        )



    

async def list_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        query = """
        SELECT u.telegram_id, u.name 
        FROM users u
        JOIN swipes s1 ON u.telegram_id = s1.liked_id
        JOIN swipes s2 ON u.telegram_id = s2.liker_id
        WHERE s1.liker_id = ? AND s2.liked_id = ?
        """
        async with db.execute(query, (user_id, user_id)) as cur:
            matches = await cur.fetchall()

    if not matches:
        await update.message.reply_text("You have no matches yet. Use /find to discover people!")
        return

    keyboard = [[InlineKeyboardButton(f"Chat with {m[1]}", callback_data=f"chat_{m[0]}")] for m in matches]
    await update.message.reply_text("Your Matches:", reply_markup=InlineKeyboardMarkup(keyboard))



async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    partner_id = int(query.data.split('_')[1])

    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Clear any old active chats for both users (Existing Logic)
        await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (user_id, user_id))
        await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (partner_id, partner_id))
        
        # 2. Create the new connection (Both ways) (Existing Logic)
        await db.execute("INSERT INTO active_chats (user_id, partner_id) VALUES (?, ?)", (user_id, partner_id))
        await db.execute("INSERT INTO active_chats (user_id, partner_id) VALUES (?, ?)", (partner_id, user_id))
        await db.commit()

        # 3. Get names for personalization
        async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (partner_id,)) as cur:
            row = await cur.fetchone()
            partner_name = row[0] if row else "your match"
        
        async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as cur:
            row_me = await cur.fetchone()
            my_name = row_me[0] if row_me else "Someone"

    # 4. The Ice-Breaker Message
    ice_breaker = (
        "🎬 *The stage is yours!*\n\n"
        "You are now connected. Don't be shy—start with a 'Hi' or your favorite emoji! 🥂\n\n"
        "💡 _Type /stop at any time to end this chat._"
    )

    # Update the current user's screen
    msg_text = f"✅ *Connection Established with {partner_name}!*\n\n{ice_breaker}"
    if query.message.photo:
        await query.edit_message_caption(caption=msg_text, parse_mode="Markdown")
    else:
        await query.edit_message_text(text=msg_text, parse_mode="Markdown")
    
    # 5. Notify the partner with an exciting alert
    try:
        partner_alert = (
            f"🎆 *BOOM!* You are now chatting with *{my_name}*!\n\n"
            f"{ice_breaker}"
        )
        await context.bot.send_message(
            chat_id=partner_id,
            text=partner_alert,
            parse_mode="Markdown"
        )
    except:
        pass






def get_main_menu():
    keyboard = [
        ["🔥 Find Matches", "👤 My Profile"],
        ["💖 Matches", "⚙️ Settings"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def photo_relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relays photos between matched users in an active chat."""
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()

        if row:
            partner_id = row[0]
            # Get the sender's CUSTOM name from the database
            async with db.execute("SELECT name FROM users WHERE telegram_id = ?", (user_id,)) as name_cur:
                name_row = await name_cur.fetchone()
                sender_name = name_row[0] if name_row else "User"

            await context.bot.send_photo(
                chat_id=partner_id, 
                photo=update.message.photo[-1].file_id,
                caption=f"📷 Photo from {sender_name}"
            )

# ---------------- Chat System ----------------

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ends an active chat session."""
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM active_chats WHERE user_id = ? OR partner_id = ?", (user_id, user_id))
        await db.commit()
    await update.message.reply_text("📴 Chat ended.")

# PASTE STEP 1 HERE:
async def chat_relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relays text messages between matched users in an active chat."""
    user_id = update.effective_user.id
    if not update.message or not update.message.text:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Find who the user is talking to
        async with db.execute("SELECT partner_id FROM active_chats WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        
        if row:
            partner_id = row[0]
            # 2. Get the sender's name for a better chat experience
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
                await db.commit()
                await update.message.reply_text("❌ Your partner is no longer available. Chat ended.")
# ---------------- 1. The Conversation Handler ----------------
# ---------------- Corrected Conversation Handler ----------------
conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        GENDER: [CallbackQueryHandler(get_gender)],
        CAMPUS: [CallbackQueryHandler(get_campus)],
        PHOTO: [MessageHandler(filters.PHOTO, get_photo), CallbackQueryHandler(get_photo, pattern="skip")],
        BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bio), CallbackQueryHandler(get_bio, pattern="skip")],
        HOBBIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hobbies), CallbackQueryHandler(get_hobbies, pattern="skip")],
        PREFERENCE: [CallbackQueryHandler(get_preference, pattern="^pref_")],
        REVIEW: [CallbackQueryHandler(review_profile, pattern="^(confirm|edit_profile)$")],
        EDIT_CHOICE: [CallbackQueryHandler(edit_choice, pattern="^edit_(name|gender|campus|photo|bio|hobbies)$")],
        EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_input)],
        EDIT_GENDER: [CallbackQueryHandler(edit_gender_input)],
        EDIT_CAMPUS: [CallbackQueryHandler(edit_campus_input)],
        EDIT_PHOTO: [MessageHandler(filters.PHOTO, edit_photo_input), CallbackQueryHandler(edit_photo_input, pattern="skip")],
        EDIT_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_bio_input), CallbackQueryHandler(edit_bio_input, pattern="skip")],
        EDIT_HOBBIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_hobbies_input), CallbackQueryHandler(edit_hobbies_input, pattern="skip")]
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

# ---------------- 2. The Main Execution Block ----------------
# ---------------- 2. The Main Execution Block ----------------
if __name__ == "__main__":
    # Windows specific event loop fix
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Initialize the database
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    import os
    from dotenv import load_dotenv

    load_dotenv()
    TOKEN = os.getenv("BOT_TOKEN")
    
    # ⚠️ IMPORTANT: Add token validation!
    if not TOKEN:
        print("❌ ERROR: BOT_TOKEN not found in .env file")
        print("Please create a .env file with: BOT_TOKEN=your_token_here")
        exit(1)
    
    app = ApplicationBuilder().token(TOKEN).build()

    # 1. The Conversation Handler (Registration & Editing)
    # This MUST come first so it can capture inputs during registration
    app.add_handler(conv_handler)

    # 2. Main Menu Command Handlers
    app.add_handler(CommandHandler("find", find_match))
    app.add_handler(CommandHandler("matches", list_matches))
    app.add_handler(CommandHandler("myprofile", show_my_profile))
    app.add_handler(CommandHandler("settings", set_preference))
    app.add_handler(CommandHandler("stop", stop_chat))

    # 3. Callback Query Handlers (The "Hidden" logic for buttons)
    # Part 3: This makes the Like button and Start Chat buttons work!
    app.add_handler(CallbackQueryHandler(handle_like, pattern="^like_"))
    app.add_handler(CallbackQueryHandler(start_chat, pattern="^chat_"))
    app.add_handler(CallbackQueryHandler(find_match, pattern="find_next"))
    app.add_handler(CallbackQueryHandler(save_preference, pattern="^pref_"))

    # 4. Main Menu Button Handlers (Text based)
    # This makes the physical buttons at the bottom of the phone work
    app.add_handler(MessageHandler(filters.Regex("^🔥 Find Matches$"), find_match))
    app.add_handler(MessageHandler(filters.Regex("^👤 My Profile$"), show_my_profile))
    app.add_handler(MessageHandler(filters.Regex("^💖 Matches$"), list_matches))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Settings$"), set_preference))

    # 5. Message Relays (The "Catch-All" logic)
    # This MUST be at the very bottom so it doesn't interfere with registration
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_relay))
    app.add_handler(MessageHandler(filters.PHOTO, photo_relay))

    print("✅ AU Dating Bot is running! Press Ctrl+C to stop.")
    
    # Add error handling for polling
    try:
        app.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Bot crashed with error: {e}")
        # Optionally log to file
