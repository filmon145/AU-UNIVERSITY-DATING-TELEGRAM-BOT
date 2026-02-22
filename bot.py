import sys
import os
import asyncio
import asyncpg
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, ConversationHandler, filters, CallbackQueryHandler
)
from dotenv import load_dotenv
from aiohttp import web

# Load environment variables
load_dotenv()

# Define conversation states
(NAME, GENDER, CAMPUS, PHOTO, BIO, HOBBIES, PREFERENCE, REVIEW, 
 EDIT_CHOICE, EDIT_NAME, EDIT_GENDER, EDIT_CAMPUS, 
 EDIT_PHOTO, EDIT_BIO, EDIT_HOBBIES, REPORT_REASON) = range(16)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@AmboU_confession")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", "8080"))

# Validate required environment variables
if not BOT_TOKEN:
    print("❌ ERROR: BOT_TOKEN environment variable is required!")
    sys.exit(1)

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL environment variable is required!")
    sys.exit(1)

print("=" * 50)
print("🚀 Starting AU Dating Bot...")
print(f"✅ Bot token: {BOT_TOKEN[:10]}...")
print(f"✅ Database: {DATABASE_URL[:30]}...")
print(f"✅ Port: {PORT}")
print("=" * 50)

# Database connection pool
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database connection pool
db_pool = None

# ---------------- Database Functions ----------------
async def init_db():
    """Initialize PostgreSQL database tables with Supabase SSL support"""
    global db_pool
    
    print("=" * 50)
    print("🔄 Initializing database connection...")
    logger.info("Starting database initialization")
    
    # Check if DATABASE_URL exists
    if not DATABASE_URL:
        print("❌ ERROR: DATABASE_URL environment variable is missing!")
        logger.error("DATABASE_URL environment variable is missing!")
        raise ValueError("DATABASE_URL is required")
    
    # Make a copy of the DATABASE_URL to modify
    db_url = DATABASE_URL
    
    # Ensure Supabase connection uses SSL
    if "supabase" in db_url and "sslmode" not in db_url:
        print("🔒 Adding SSL requirement for Supabase connection...")
        # Add SSL mode for Supabase
        if "?" in db_url:
            db_url += "&sslmode=require"
        else:
            db_url += "?sslmode=require"
        print(f"✅ SSL enabled for Supabase")
    
    # Show partial URL for debugging (don't show full password)
    if "postgresql://" in db_url:
        # Mask the password for security
        parts = db_url.split("@")
        if len(parts) == 2:
            safe_url = parts[0].split(":")[0] + ":***@" + parts[1]
            print(f"📦 Connecting to: {safe_url}")
            logger.info(f"Connecting to database: {safe_url}")
        else:
            print(f"📦 Database URL: {db_url[:50]}...")
    
    max_retries = 3
    retry_delay = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            print(f"Attempt {attempt + 1}/{max_retries}...")
            logger.info(f"Database connection attempt {attempt + 1}/{max_retries}")
            
            # Create connection pool with proper timeouts and SSL
            db_pool = await asyncpg.create_pool(
                dsn=db_url,  # Use the modified URL with SSL
                min_size=1,
                max_size=10,
                max_inactive_connection_lifetime=300,  # 5 minutes
                command_timeout=60,
                timeout=30,  # Connection timeout
                statement_cache_size=0,  # Disable statement cache for now
                ssl=True  # Explicitly enable SSL
            )
            
            # Test the connection
            async with db_pool.acquire() as conn:
                # Simple test query
                db_version = await conn.fetchval("SELECT version()")
                print(f"✅ Connected to PostgreSQL: {db_version.split(',')[0]}")
                logger.info(f"Successfully connected to PostgreSQL")
                
                # Test if we can execute queries
                test_result = await conn.fetchval("SELECT 1 + 1")
                print(f"✅ Database test query: 1 + 1 = {test_result}")
            
            # Create tables
            print("📊 Creating/verifying database tables...")
            logger.info("Creating/verifying database tables")
            await create_tables()
            
            print("✅ Database initialized successfully!")
            logger.info("Database initialized successfully")
            print("=" * 50)
            return
            
        except asyncpg.exceptions.ConnectionDoesNotExistError as e:
            print(f"❌ Connection failed. Database might not be ready: {e}")
            logger.error(f"Connection failed: {e}")
            if attempt < max_retries - 1:
                print(f"⏳ Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                print("❌ Max retries reached. Database connection failed.")
                logger.error("Max retries reached. Database connection failed.")
                raise
                
        except asyncpg.exceptions.InvalidPasswordError as e:
            print("❌ Invalid database password. Check your DATABASE_URL.")
            logger.error(f"Invalid password: {e}")
            raise
            
        except Exception as e:
            print(f"❌ Database error: {type(e).__name__}: {e}")
            logger.error(f"Database error: {type(e).__name__}: {e}")
            if attempt < max_retries - 1:
                print(f"⏳ Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                print("❌ Max retries reached. Could not initialize database.")
                logger.error("Max retries reached. Could not initialize database.")
                raise
async def create_tables():
    """Create all required tables"""
    async with db_pool.acquire() as conn:
        # Users table - stores user profiles
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username TEXT,
            name TEXT NOT NULL,
            gender TEXT NOT NULL,
            campus TEXT NOT NULL,
            photo_file_id TEXT,
            bio TEXT,
            hobbies TEXT,
            preference TEXT DEFAULT 'Both',
            is_banned BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            last_active TIMESTAMP DEFAULT NOW()
        )
        """)
        print("  ✅ users table")
        
        # Swipes table - stores likes/swipes
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS swipes (
            id SERIAL PRIMARY KEY,
            liker_id BIGINT NOT NULL,
            liked_id BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(liker_id, liked_id)
        )
        """)
        print("  ✅ swipes table")
        
        # Active chats table - stores currently active conversations
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS active_chats (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            partner_id BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id),
            UNIQUE(partner_id)
        )
        """)
        print("  ✅ active_chats table")
        
        # Chat requests table - stores pending chat requests
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_requests (
            id SERIAL PRIMARY KEY,
            requester_id BIGINT NOT NULL,
            requested_id BIGINT NOT NULL,
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(requester_id, requested_id, status)
        )
        """)
        print("  ✅ chat_requests table")
        
        # Reports table - stores user reports
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY,
            reporter_id BIGINT NOT NULL,
            reported_id BIGINT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'resolved', 'dismissed')),
            admin_notes TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """)
        print("  ✅ reports table")
        
        # Channel check table - tracks who joined the channel
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_checks (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            has_joined BOOLEAN DEFAULT FALSE,
            last_checked TIMESTAMP DEFAULT NOW(),
            joined_at TIMESTAMP,
            UNIQUE(user_id)
        )
        """)
        print("  ✅ channel_checks table")
        
        print("✅ All tables created/verified successfully!")

async def save_profile(update, context):
    """Save user profile to PostgreSQL with better error handling"""
    try:
        user = update.effective_user
        if not user:
            print("❌ No user in update")
            return False
        
        async with db_pool.acquire() as conn:
            # Get all values with explicit defaults
            user_id = user.id
            username = user.username or ""
            name = context.user_data.get('name') or "Unknown"
            gender = context.user_data.get('gender') or "Unknown"
            campus = context.user_data.get('campus') or "Unknown"
            photo_file_id = context.user_data.get('photo_file_id')
            bio = context.user_data.get('bio')
            hobbies = context.user_data.get('hobbies')
            preference = context.user_data.get('preference') or "Both"
            
            print(f"DEBUG: Saving profile for {user_id}, name: {name}")
            
            # First check if user exists
            existing = await conn.fetchrow(
                "SELECT telegram_id FROM users WHERE telegram_id = $1", 
                user_id
            )
            
            if existing:
                # Update existing user
                await conn.execute("""
                    UPDATE users SET
                    username = $1, 
                    name = $2, 
                    gender = $3, 
                    campus = $4,
                    photo_file_id = $5, 
                    bio = $6, 
                    hobbies = $7, 
                    preference = $8,
                    updated_at = NOW()
                    WHERE telegram_id = $9
                """, 
                username, name, gender, campus, photo_file_id, 
                bio, hobbies, preference, user_id
                )
                print(f"✅ Updated profile for user {user_id}")
            else:
                # Insert new user - FIXED
                await conn.execute("""
                    INSERT INTO users 
                    (telegram_id, username, name, gender, campus, 
                     photo_file_id, bio, hobbies, preference) 
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """, 
                user_id, username, name, gender, campus, 
                photo_file_id, bio, hobbies, preference
                )
                print(f"✅ Created new profile for user {user_id}")
            
            # ✅ DEBUG: Check if user was saved
            await debug_user_exists(user_id)
            
            return True
            
    except Exception as e:
        # Get user ID safely
        user_id = "unknown"
        try:
            if 'user' in locals() and user:
                user_id = user.id
        except:
            pass
        
        print(f"❌ Error saving profile for user {user_id}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
async def get_user_by_telegram_id(user_id: int):
    """Get user by Telegram ID"""
    try:
        async with db_pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id = $1", 
                user_id
            )
    except Exception as e:
        print(f"❌ Error getting user {user_id}: {e}")
        return None

async def is_user_banned(user_id: int) -> bool:
    """Check if user is banned"""
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT is_banned FROM users WHERE telegram_id = $1", 
                user_id
            )
            return result if result else False
    except Exception as e:
        print(f"❌ Error checking ban status for user {user_id}: {e}")
        return False

async def update_last_active(user_id: int):
    """Update user's last active timestamp"""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET last_active = NOW() WHERE telegram_id = $1", 
                user_id
            )
    except:
        pass  # Silently fail for this non-critical operation

async def debug_user_exists(user_id: int):
    """Debug function to check if user exists in database"""
    try:
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id = $1", 
                user_id
            )
            if user:
                print(f"✅ DEBUG: User {user_id} exists in database:")
                print(f"   Name: {user['name']}")
                print(f"   Created: {user['created_at']}")
                return True
            else:
                print(f"❌ DEBUG: User {user_id} NOT found in database")
                return False
    except Exception as e:
        print(f"❌ DEBUG Error: {e}")
        return False
# Add this function right after the debug_user_exists function

async def debug_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to check database"""
    user_id = update.effective_user.id
    
    await update.message.reply_text(f"🔍 Checking database for user {user_id}...")
    
    async with db_pool.acquire() as conn:
        # Check if user exists
        user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id = $1", user_id)
        if user:
            await update.message.reply_text(
                f"✅ User found in database:\n"
                f"Name: {user['name']}\n"
                f"Gender: {user['gender']}\n"
                f"Campus: {user['campus']}\n"
                f"Created: {user['created_at']}"
            )
        else:
            await update.message.reply_text("❌ User NOT found in database")
        
        # Get total user count
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
        await update.message.reply_text(f"📊 Total users in database: {count}")


# ---------------- Channel Check ----------------
async def check_channel_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is a member of the required channel"""
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        print(f"Warning checking channel membership: {e}")
        return False
async def update_channel_check(user_id: int, has_joined: bool):
    """Update channel check status in database"""
    try:
        async with db_pool.acquire() as conn:
            # Delete old record first, then insert new
            await conn.execute("DELETE FROM channel_checks WHERE user_id = $1", user_id)
            await conn.execute("INSERT INTO channel_checks (user_id, has_joined) VALUES ($1, $2)", 
                              user_id, has_joined)
    except Exception as e:
        print(f"Warning: Failed to update channel check for user {user_id}: {e}")

# ---------------- Start ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    print(f"🔍 DEBUG: /start called by user {user_id}")
    await debug_user_exists(user_id)
    
    # Clear any previous context data
    context.user_data.clear()
    
    # Check if user is banned
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_banned FROM users WHERE telegram_id = $1", user_id)
        if row and row['is_banned']:
            await update.message.reply_text("❌ You have been banned from using this bot.")
            return ConversationHandler.END
    
    # Check channel membership
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
    
    # Check if user is already in a chat
    async with db_pool.acquire() as conn:
        chat_row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
        if chat_row:
            await update.message.reply_text("❌ You are currently in a chat. Please use /stop to end your current conversation before starting a new registration.")
            return ConversationHandler.END
    
    # Check if user already has a profile - FIXED QUERY
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT name, telegram_id FROM users WHERE telegram_id = $1", 
            user_id
        )
    
    if user:
        await update.message.reply_text(
            f"Welcome back, {user['name']}! 🤗\n\n"
            f"Use /find to meet people or /myprofile to view your profile.\n"
            f"Use /settings to change preferences.\n"
            f"Use /report to report inappropriate behavior.",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    
    # New user - start registration
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
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", user_id)
        
        if user:
            # Existing user
            await query.edit_message_text(
                f"<b>✅ WELCOME BACK, {user['name']}! 🤗</b>\n\n"
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
            await context.bot.send_message(
                chat_id=user_id,
                text="What's your name or nickname?",
                parse_mode="HTML"
            )
            return ConversationHandler.END
    else:
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

async def review_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm":
        success = await save_profile(update, context)  # ✅ Get the return value
        
        user_id = update.effective_user.id
        print(f"🔍 DEBUG: Profile save {'successful' if success else 'failed'} for user {user_id}")
        
        if 'editing' in context.user_data:
            context.user_data.pop('editing', None)
        
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except:
            pass
        
        if success:
            welcome_text = (
                "🎉 Registration Complete!\n\n"
                "You can now use the menu buttons below to find people."
            )
        else:
            welcome_text = (
                "❌ Failed to save your profile. Please try again or contact support."
            )
        
        await query.message.reply_text(
            text=welcome_text, 
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    # ... rest of your code

    elif query.data == "edit_profile":
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

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Registration cancelled. Use /start to begin again.")
    return ConversationHandler.END

def get_main_menu():
    """Get main menu without matches button"""
    keyboard = [
        ["🔥 Find Matches", "👤 My Profile"],
        ["⚙️ Settings", "📢 Report User"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------------- Chat System ----------------
async def chat_relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relay text messages between matched users"""
    # Check if update.effective_user exists
    if not update.effective_user:
        print("Warning: update.effective_user is None in chat_relay")
        return
    
    user_id = update.effective_user.id
    
    if not update.message or not update.message.text:
        return
    
    # Check if user is in edit mode first
    if 'editing_existing' in context.user_data:
        # Handle text edit instead
        await handle_text_edit(update, context)
        return
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
        
        if row:
            partner_id = row['partner_id']
            name_row = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", user_id)
            sender_name = name_row['name'] if name_row else "User"

            try:
                await context.bot.send_message(
                    chat_id=partner_id, 
                    text=f"💬 {sender_name}: {update.message.text}"
                )
            except Exception as e:
                print(f"Error relaying message: {e}")
                # Clean up if partner is unavailable
                await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", user_id)
                await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", partner_id)
                await update.message.reply_text("❌ Your partner is no longer available. Chat ended.")

async def photo_relay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Relay photos between matched users in active chat"""
    # Check if update.effective_user exists
    if not update.effective_user:
        print("Warning: update.effective_user is None in photo_relay")
        return
    
    user_id = update.effective_user.id
    
    # Check if user is in edit mode first
    if 'editing_existing' in context.user_data:
        # Handle photo edit instead
        await handle_photo_edit(update, context)
        return
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
            
        if row:
            partner_id = row['partner_id']
            name_row = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", user_id)
            sender_name = name_row['name'] if name_row else "User"
            
            try:
                await context.bot.send_photo(
                    chat_id=partner_id,
                    photo=update.message.photo[-1].file_id,
                    caption=f"📷 Photo from {sender_name}"
                )
            except Exception as e:
                print(f"Error sending photo: {e}")
                await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", user_id)
                await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", partner_id)
                await update.message.reply_text("❌ Your partner is no longer available. Chat ended.")

# ---------------- Report System ----------------
async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start report process"""
    user_id = update.effective_user.id
    
    # Check if user is in a chat
    async with db_pool.acquire() as conn:
        chat_row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
        if chat_row:
            partner_id = chat_row['partner_id']
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
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reports (reporter_id, reported_id, reason) VALUES ($1, $2, $3)",
            user_id, reported_id, reason
        )
    
    # Notify admin if admin ID is set
    if ADMIN_USER_ID:
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
    async with db_pool.acquire() as conn:
        chat_row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
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

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET preference = $1 WHERE telegram_id = $2", pref, user_id)

    await query.answer()
    await query.edit_message_text(f"✅ Preference updated! I will now show you: {pref}")

async def find_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if user is banned
    user_id = update.effective_user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_banned FROM users WHERE telegram_id = $1", user_id)
        if row and row['is_banned']:
            text = "❌ You have been banned from using this bot."
            if update.callback_query:
                await update.callback_query.message.reply_text(text)
            else:
                await update.message.reply_text(text)
            return
    
    # Check if user is in a chat
    async with db_pool.acquire() as conn:
        chat_row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
        if chat_row:
            text = "❌ You are currently in a chat. Please use /stop to end your current conversation before finding new matches."
            if update.callback_query:
                await update.callback_query.message.reply_text(text)
            else:
                await update.message.reply_text(text)
            return
    
    is_callback = update.callback_query is not None
    
    if is_callback:
        await update.callback_query.answer()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT preference FROM users WHERE telegram_id = $1", user_id)
        if not row:
            text = "❌ Create a profile first using /start."
            if is_callback:
                await update.callback_query.message.reply_text(text)
            else:
                await update.message.reply_text(text)
            return
        
        pref = row['preference']

        # Don't show banned users
        if pref == "Both":
            query = """
            SELECT telegram_id, name, campus, bio, photo_file_id
            FROM users
            WHERE gender IN ('Male', 'Female') AND is_banned = FALSE
            AND telegram_id != $1
            AND telegram_id NOT IN (
                SELECT liked_id FROM swipes WHERE liker_id = $1
            )
            ORDER BY RANDOM()
            LIMIT 1
            """
            params = (user_id,)
        else:
            query = """
            SELECT telegram_id, name, campus, bio, photo_file_id
            FROM users
            WHERE gender = $1 AND is_banned = FALSE
            AND telegram_id != $2
            AND telegram_id NOT IN (
                SELECT liked_id FROM swipes WHERE liker_id = $2
            )
            ORDER BY RANDOM()
            LIMIT 1
            """
            params = (pref, user_id)
        
        match = await conn.fetchrow(query, *params)

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

    match_id = match['telegram_id']
    name = match['name']
    campus = match['campus']
    bio = match['bio']
    photo = match['photo_file_id']
    
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
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT is_banned FROM users WHERE telegram_id = $1", user_id)
        if row and row['is_banned']:
            await update.callback_query.answer("❌ You have been banned from using this bot.")
            return
    
    # Check if user is in a chat
    async with db_pool.acquire() as conn:
        chat_row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
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

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO swipes (liker_id, liked_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, liked_id)

        is_match = await conn.fetchrow("SELECT 1 FROM swipes WHERE liker_id = $1 AND liked_id = $2", liked_id, user_id)

        me = await conn.fetchrow("SELECT name, photo_file_id FROM users WHERE telegram_id = $1", user_id)

    if is_match:
        match_alert = "<b>🎆 BOOM! IT'S A MATCH! 🎆</b>\n\nYou both liked each other! Don't wait, say hi! 👋"
        
        # Check if the matched user is in a chat
        async with db_pool.acquire() as conn:
            liked_user_chat = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", liked_id)
            if liked_user_chat:
                # Notify the liker that the other user is busy
                await query.message.reply_text("🎯 You have a match! However, your match is currently in another conversation. Try again later!")
                return await find_match(update, context)
        
        await context.bot.send_message(
            chat_id=liked_id, 
            text=f"{match_alert}\n\nMatched with: {me['name']}",
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
            caption = f"<b>🔥 SOMEONE LIKED YOU!</b>\n\n👤 {me['name']} just swiped right. Swipe /find to see who it is!"
            if me['photo_file_id']:
                await context.bot.send_photo(
                    chat_id=liked_id, 
                    photo=me['photo_file_id'], 
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
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT name, gender, campus, bio, hobbies, photo_file_id FROM users WHERE telegram_id = $1", 
            user_id
        )

    if not user:
        await update.message.reply_text("❌ You don't have a profile yet! Type /start.")
        return

    name = user['name']
    gender = user['gender']
    campus = user['campus']
    bio = user['bio']
    hobbies = user['hobbies']
    photo_id = user['photo_file_id']
    
    profile_text = (
        "<b>👤 YOUR PROFILE</b>\n\n"
        f"<b>✨ Name:</b> {name}\n"
        f"<b>⚧ Gender:</b> {gender}\n"
        f"<b>📍 Campus:</b> {campus}\n"
        f"<b>📝 Bio:</b> {bio or 'Not set'}\n"
        f"<b>🎯 Hobbies:</b> {hobbies or 'Not set'}"
    )

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

# ---------------- Edit Profile System ----------------
async def start_edit_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start editing profile from existing profile view"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Load existing profile data into context.user_data for editing
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT name, gender, campus, photo_file_id, bio, hobbies, preference FROM users WHERE telegram_id = $1", 
            user_id
        )
    
    if user:
        context.user_data['name'] = user['name']
        context.user_data['gender'] = user['gender']
        context.user_data['campus'] = user['campus']
        context.user_data['photo_file_id'] = user['photo_file_id']
        context.user_data['bio'] = user['bio']
        context.user_data['hobbies'] = user['hobbies']
        context.user_data['preference'] = user['preference']
        context.user_data['editing_existing'] = True
    
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
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET gender = $1 WHERE telegram_id = $2", gender, user_id)
        
    elif query.data.startswith("save_campus_"):
        campus = query.data.replace("save_campus_", "")
        context.user_data['campus'] = campus
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE users SET campus = $1 WHERE telegram_id = $2", campus, user_id)
        
    elif query.data.startswith("skip_"):
        field = query.data.replace("skip_", "")
        if field == "photo":
            context.user_data['photo_file_id'] = None
            async with db_pool.acquire() as conn:
                await conn.execute("UPDATE users SET photo_file_id = NULL WHERE telegram_id = $1", user_id)
        elif field == "bio":
            context.user_data['bio'] = None
            async with db_pool.acquire() as conn:
                await conn.execute("UPDATE users SET bio = NULL WHERE telegram_id = $1", user_id)
        elif field == "hobbies":
            context.user_data['hobbies'] = None
            async with db_pool.acquire() as conn:
                await conn.execute("UPDATE users SET hobbies = NULL WHERE telegram_id = $1", user_id)
    
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
        async with db_pool.acquire() as conn:
            chat_row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
            if chat_row:
                # User is in chat, relay message instead
                await chat_relay(update, context)
                return
        
        # Not in chat, not editing - check if user has a profile
        async with db_pool.acquire() as conn:
            has_profile = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", user_id)
        
        if has_profile:
            await show_my_profile(update, context)
        else:
            await update.message.reply_text("❌ You don't have a profile yet! Use /start to create one.")
        return
    
    text = update.message.text.strip()
    
    if not text:
        await update.message.reply_text("❌ Please enter valid text.")
        return
    
    # Determine which field is being edited
    field = None
    
    if 'last_edit_field' in context.user_data:
        field = context.user_data['last_edit_field']
    else:
        if len(text) < 50:
            field = 'name'
        else:
            field = 'bio'
    
    if not field:
        await update.message.reply_text("❌ I'm not sure what you're editing. Please use the edit buttons.")
        return
    
    # Save to context
    context.user_data[field] = text
    
    # Save to database
    async with db_pool.acquire() as conn:
        await conn.execute(f"UPDATE users SET {field} = $1 WHERE telegram_id = $2", text, user_id)
    
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
        async with db_pool.acquire() as conn:
            chat_row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
            if chat_row:
                # User is in chat, relay photo instead
                await photo_relay(update, context)
                return
        return
    
    if update.message.photo:
        context.user_data['photo_file_id'] = update.message.photo[-1].file_id
        
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET photo_file_id = $1 WHERE telegram_id = $2",
                context.user_data['photo_file_id'], user_id
            )
        
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
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT name, gender, campus, bio, hobbies, photo_file_id FROM users WHERE telegram_id = $1", 
            user_id
        )

    if user:
        name = user['name']
        gender = user['gender']
        campus = user['campus']
        bio = user['bio']
        hobbies = user['hobbies']
        photo_id = user['photo_file_id']
        
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
            if query.message.photo:
                await query.edit_message_caption(
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
        except Exception as e:
            print(f"Error in finish_edit: {e}")
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
    
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to access this command.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🚨 Reports", callback_data="admin_reports")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="admin_back")]
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
    
    async with db_pool.acquire() as conn:
        # Total users
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        
        # Active users (created in last 7 days)
        active_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '7 days'")
        
        # Banned users
        banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE")
        
        # Total matches
        total_matches = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT s1.liker_id, s1.liked_id 
                FROM swipes s1
                INNER JOIN swipes s2 ON s1.liker_id = s2.liked_id AND s1.liked_id = s2.liker_id
                WHERE s1.liker_id < s1.liked_id
            ) as matches
        """)
        
        # Total reports
        pending_reports = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
        
        # Active chats
        active_chats = await conn.fetchval("SELECT COUNT(*) FROM active_chats")
    
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

async def admin_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending reports"""
    query = update.callback_query
    await query.answer()
    
    async with db_pool.acquire() as conn:
        reports = await conn.fetch("""
            SELECT r.id, r.reporter_id, r.reported_id, r.reason, r.created_at,
                   u1.name as reporter_name, u2.name as reported_name
            FROM reports r
            LEFT JOIN users u1 ON r.reporter_id = u1.telegram_id
            LEFT JOIN users u2 ON r.reported_id = u2.telegram_id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
            LIMIT 10
        """)
    
    if not reports:
        await query.edit_message_text(
            "✅ No pending reports.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
        )
        return
    
    text = "<b>🚨 PENDING REPORTS</b>\n\n"
    keyboard = []
    
    for report in reports:
        report_id = report['id']
        text += f"<b>Report ID:</b> {report_id}\n"
        text += f"<b>Reporter:</b> {report['reporter_name']} ({report['reporter_id']})\n"
        text += f"<b>Reported:</b> {report['reported_name']} ({report['reported_id']})\n"
        text += f"<b>Reason:</b> {report['reason'][:100]}...\n"
        text += f"<b>Date:</b> {report['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
        text += "-" * 30 + "\n"
        
        keyboard.append([
            InlineKeyboardButton(f"✅ Approve {report_id}", callback_data=f"approve_{report_id}"),
            InlineKeyboardButton(f"❌ Reject {report_id}", callback_data=f"reject_{report_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
    
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle report approval/rejection"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("approve_"):
        report_id = int(query.data.split('_')[1])
        action = "approved"
        status = "approved"
    elif query.data.startswith("reject_"):
        report_id = int(query.data.split('_')[1])
        action = "rejected"
        status = "rejected"
    else:
        return
    
    async with db_pool.acquire() as conn:
        # Get report details
        report = await conn.fetchrow("""
            SELECT reporter_id, reported_id, reason FROM reports WHERE id = $1
        """, report_id)
        
        if report:
            # Update report status
            await conn.execute("UPDATE reports SET status = $1 WHERE id = $2", status, report_id)
            
            # If approved, ban the reported user
            if status == "approved":
                await conn.execute("UPDATE users SET is_banned = TRUE WHERE telegram_id = $1", report['reported_id'])
                
                # Notify the reported user
                try:
                    await context.bot.send_message(
                        chat_id=report['reported_id'],
                        text="❌ Your account has been banned due to user reports. Contact admin for appeal."
                    )
                except:
                    pass
    
    await query.edit_message_text(
        f"✅ Report {report_id} {action}!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_reports")]])
    )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broadcast process"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['broadcasting'] = True
    
    await query.edit_message_text(
        "<b>📢 BROADCAST MESSAGE</b>\n\n"
        "Send the message you want to broadcast to all users.\n"
        "You can send text, photo, or document.\n\n"
        "Type /cancel to cancel.",
        parse_mode="HTML"
    )

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast message"""
    if 'broadcasting' not in context.user_data:
        return
    
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        return
    
    # Cancel broadcast
    if update.message.text and update.message.text.startswith('/cancel'):
        context.user_data.pop('broadcasting', None)
        await update.message.reply_text("Broadcast cancelled.")
        return
    
    # Get all users
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT telegram_id FROM users WHERE is_banned = FALSE")
    
    total = len(users)
    success = 0
    failed = 0
    
    await update.message.reply_text(f"📤 Broadcasting to {total} users...")
    
    # Send to each user
    for user in users:
        try:
            if update.message.text:
                await context.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=f"<b>📢 ADMIN ANNOUNCEMENT</b>\n\n{update.message.text}",
                    parse_mode="HTML"
                )
            elif update.message.photo:
                await context.bot.send_photo(
                    chat_id=user['telegram_id'],
                    photo=update.message.photo[-1].file_id,
                    caption=f"<b>📢 ADMIN ANNOUNCEMENT</b>\n\n{update.message.caption or ''}",
                    parse_mode="HTML"
                )
            elif update.message.document:
                await context.bot.send_document(
                    chat_id=user['telegram_id'],
                    document=update.message.document.file_id,
                    caption=f"<b>📢 ADMIN ANNOUNCEMENT</b>\n\n{update.message.caption or ''}",
                    parse_mode="HTML"
                )
            success += 1
        except Exception as e:
            failed += 1
            print(f"Failed to send to {user['telegram_id']}: {e}")
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.1)
    
    context.user_data.pop('broadcasting', None)
    
    await update.message.reply_text(
        f"✅ Broadcast completed!\n\n"
        f"✅ Successful: {success}\n"
        f"❌ Failed: {failed}"
    )

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to admin panel"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🚨 Reports", callback_data="admin_reports")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="admin_back")]
    ]
    
    await query.edit_message_text(
        "<b>🔧 ADMIN PANEL</b>\n\n"
        "Select an option below:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------------- Chat System ----------------
async def start_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    partner_id = int(query.data.split('_')[1])
    
    async with db_pool.acquire() as conn:
        # Check if user is already in a chat
        existing_chat = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
        if existing_chat:
            await query.message.reply_text("❌ You are already in a chat! Use /stop to end your current conversation before starting a new one.")
            return
        
        # Check pending request
        pending_request = await conn.fetchrow("""
            SELECT id FROM chat_requests 
            WHERE requester_id = $1 AND requested_id = $2 AND status = 'pending'
        """, partner_id, user_id)
        
        if pending_request:
            await conn.execute("DELETE FROM chat_requests WHERE id = $1", pending_request['id'])
        else:
            # Check if partner is already in a chat
            partner_chat = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", partner_id)
            if partner_chat:
                await conn.execute(
                    "INSERT INTO chat_requests (requester_id, requested_id) VALUES ($1, $2)",
                    user_id, partner_id
                )
                
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

        # Clear any old active chats
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", user_id)
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", partner_id)
        
        # Create the new connection
        await conn.execute("INSERT INTO active_chats (user_id, partner_id) VALUES ($1, $2)", user_id, partner_id)
        await conn.execute("INSERT INTO active_chats (user_id, partner_id) VALUES ($1, $2)", partner_id, user_id)

        # Get names
        partner_row = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", partner_id)
        partner_name = partner_row['name'] if partner_row else "your match"
        
        my_row = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", user_id)
        my_name = my_row['name'] if my_row else "Someone"

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

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    partner_id = None
    
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
        if row:
            partner_id = row['partner_id']
        
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", user_id)
        await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", partner_id)
        
        if partner_id:
            await conn.execute(
                "INSERT INTO chat_requests (requester_id, requested_id, status) VALUES ($1, $2, 'pending')",
                partner_id, user_id
            )
    
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

async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View pending chat requests"""
    user_id = update.effective_user.id
    
    async with db_pool.acquire() as conn:
        requests = await conn.fetch("""
            SELECT cr.id, cr.requester_id, u.name, u.campus
            FROM chat_requests cr
            JOIN users u ON cr.requester_id = u.telegram_id
            WHERE cr.requested_id = $1 AND cr.status = 'pending'
            ORDER BY cr.created_at DESC
        """, user_id)
    
    if not requests:
        await update.message.reply_text("You have no pending chat requests.")
        return
    
    keyboard = []
    for req in requests:
        req_id = req['id']
        requester_id = req['requester_id']
        name = req['name']
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
    
    if query.data.startswith("accept_"):
        request_id = int(query.data.split('_')[1])
        
        async with db_pool.acquire() as conn:
            # Get request details
            request = await conn.fetchrow("""
                SELECT requester_id, requested_id FROM chat_requests WHERE id = $1
            """, request_id)
            
            if request:
                requester_id = request['requester_id']
                requested_id = request['requested_id']
                
                # Clear old chats
                await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", requester_id)
                await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", requested_id)
                
                # Create new chat
                await conn.execute("INSERT INTO active_chats (user_id, partner_id) VALUES ($1, $2)", requester_id, requested_id)
                await conn.execute("INSERT INTO active_chats (user_id, partner_id) VALUES ($1, $2)", requested_id, requester_id)
                
                # Delete the request
                await conn.execute("DELETE FROM chat_requests WHERE id = $1", request_id)
                
                # Get names
                requester_name = await conn.fetchval("SELECT name FROM users WHERE telegram_id = $1", requester_id)
                requested_name = await conn.fetchval("SELECT name FROM users WHERE telegram_id = $1", requested_id)
                
                # Notify both users
                try:
                    await context.bot.send_message(
                        chat_id=requester_id,
                        text=f"<b>✅ CHAT REQUEST ACCEPTED!</b>\n\n"
                             f"You are now connected with {requested_name}! Say hello! 👋",
                        parse_mode="HTML"
                    )
                except:
                    pass
                
                await query.edit_message_text(
                    f"✅ Chat request accepted! You are now connected with {requester_name}.",
                    reply_markup=None
                )
    
    elif query.data.startswith("decline_"):
        request_id = int(query.data.split('_')[1])
        
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM chat_requests WHERE id = $1", request_id)
        
        await query.edit_message_text(
            "❌ Chat request declined.",
            reply_markup=None
        )
    
    elif query.data == "clear_requests":
        user_id = query.from_user.id
        
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM chat_requests WHERE requested_id = $1", user_id)
        
        await query.edit_message_text(
            "🗑️ All pending requests cleared.",
            reply_markup=None
        )

# ---------------- Conversation Handler ----------------
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

# ---------------- MAIN FUNCTION - FIXED FOR RAILWAY ----------------
async def main():
    """Main function that will work perfectly on Railway"""
    
    # Initialize database FIRST
    print("🔄 Initializing database...")
    try:
        await init_db()
        print("✅ Database initialized successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")
        return
    
    # Start health server BEFORE Telegram bot
    print(f"🌐 Starting health server on port {PORT}...")
    
    async def handle_health(request):
        return web.Response(text="Bot is healthy")
    
    health_app = web.Application()
    health_app.router.add_get('/', handle_health)
    health_app.router.add_get('/health', handle_health)
    
    runner = web.AppRunner(health_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"✅ Health server running on http://0.0.0.0:{PORT}")
    
    # Create Telegram application
    print("🤖 Creating Telegram bot application...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add all handlers
    print("🔧 Adding handlers...")
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("find", find_match))
    app.add_handler(CommandHandler("myprofile", show_my_profile))
    app.add_handler(CommandHandler("settings", set_preference))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("report", report_user))
    app.add_handler(CommandHandler("requests", view_requests))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(CommandHandler("debug", debug_db))

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(handle_like, pattern="^(like_|report_)"))
    app.add_handler(CallbackQueryHandler(start_chat, pattern="^chat_"))
    app.add_handler(CallbackQueryHandler(find_match, pattern="find_next"))
    app.add_handler(CallbackQueryHandler(save_preference, pattern="^pref_"))
    app.add_handler(CallbackQueryHandler(start_edit_profile, pattern="^start_edit_profile$"))
    app.add_handler(CallbackQueryHandler(handle_edit_existing, pattern="^edit_(name|gender|campus|photo|bio|hobbies)_existing$"))
    app.add_handler(CallbackQueryHandler(handle_save_edit, pattern="^(save_gender_|save_campus_|skip_)"))
    app.add_handler(CallbackQueryHandler(finish_edit, pattern="^finish_edit$"))
    app.add_handler(CallbackQueryHandler(check_channel_callback, pattern="^check_channel$"))
    
    # Admin callbacks
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_reports, pattern="^admin_reports$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_handle_report, pattern="^(approve_|reject_)"))
    app.add_handler(CallbackQueryHandler(handle_request_action, pattern="^(accept_|decline_|clear_requests)"))

    # Menu button handlers
    app.add_handler(MessageHandler(filters.Regex("^🔥 Find Matches$"), find_match))
    app.add_handler(MessageHandler(filters.Regex("^👤 My Profile$"), show_my_profile))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Settings$"), set_preference))
    app.add_handler(MessageHandler(filters.Regex("^📢 Report User$"), report_user))

    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_relay))
    app.add_handler(MessageHandler(filters.PHOTO, photo_relay))
    
    # Admin broadcast handler
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL, handle_broadcast_message))
    
    print("✅ All handlers added!")
    print(f"👑 Admin User ID: {ADMIN_USER_ID if ADMIN_USER_ID else 'Not set'}")
    print(f"📢 Channel: {CHANNEL_USERNAME}")
    
    # Start the bot
    print("🤖 Starting bot...")
    await app.initialize()
    await app.start()
    
    # Get bot info
    bot_info = await app.bot.get_me()
    print(f"✅ Bot info:")
    print(f"   Name: {bot_info.first_name}")
    print(f"   Username: @{bot_info.username}")
    print(f"   ID: {bot_info.id}")
    
    # Start polling
    print("🤖 Starting polling...")
    await app.updater.start_polling()
    
    print("=" * 50)
    print("🎉 AU DATING BOT IS RUNNING PERFECTLY!")
    print("📱 Send /start to your bot on Telegram")
    print("=" * 50)
    
    # Keep the bot running forever
    # This is CRITICAL for Railway
    try:
        # Create a permanent event to keep the script alive
        stop_event = asyncio.Event()
        await stop_event.wait()  # This waits forever
    except KeyboardInterrupt:
        print("\n👋 Shutting down gracefully...")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
    finally:
        # Clean shutdown
        print("🔄 Cleaning up...")
        await app.stop()
        await app.shutdown()
        await runner.cleanup()
        print("✅ Shutdown complete!")

# Start the bot
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ Fatal error starting bot: {e}")
        import traceback
        traceback.print_exc()








