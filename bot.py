import sys
import os
import json
import asyncio
import asyncpg
import aiohttp  
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, ConversationHandler, filters, CallbackQueryHandler
)
from dotenv import load_dotenv
from aiohttp import web

# Configure UTF-8 encoding for Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Load environment variables
load_dotenv()

# Define conversation states
(NAME, GENDER, CAMPUS, PHOTO, BIO, HOBBIES, PREFERENCE, REVIEW, 
 EDIT_CHOICE, EDIT_NAME, EDIT_GENDER, EDIT_CAMPUS, 
 EDIT_PHOTO, EDIT_BIO, EDIT_HOBBIES, REPORT_REASON) = range(16)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@AmboU_confession").strip()
CHECK_CHANNEL = os.getenv("CHECK_CHANNEL", "false").lower() in ("true", "1", "yes")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_SSL = os.getenv("DATABASE_SSL", "auto").strip().lower()
PORT = int(os.getenv("PORT", "8080"))
RENDER_URL = os.getenv("RENDER_URL", "").strip()
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "auto").strip().lower()

def validate_config():
    """Validate required environment variables before starting bot"""
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
    print(f"✅ Channel verification: {'Enabled' if CHECK_CHANNEL else 'Disabled'}")
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
async def init_db(application=None):
    """Initialize PostgreSQL database tables with flexible SSL support"""
    global db_pool
    
    print("=" * 50)
    print("🔄 Initializing database connection...")
    logger.info("Starting database initialization")
    
    if not DATABASE_URL:
        print("❌ ERROR: DATABASE_URL environment variable is missing!")
        logger.error("DATABASE_URL environment variable is missing!")
        raise ValueError("DATABASE_URL is required")
    
    # Make a copy of the DATABASE_URL to modify
    db_url = DATABASE_URL
    is_local = "localhost" in db_url or "127.0.0.1" in db_url
    
    # SSL configuration: auto / require / disable
    if DATABASE_SSL == "auto":
        ssl_config = False if is_local else 'require'
    elif DATABASE_SSL in ("false", "0", "disable", "no"):
        ssl_config = False
    else:
        ssl_config = 'require'
    
    # For Supabase with SSL
    if ("supabase" in db_url or "pooler.supabase.com" in db_url) and ssl_config:
        print("🔧 Configuring SSL for Supabase connection...")
        if "?" in db_url:
            base_url = db_url.split("?")[0]
            params = db_url.split("?")[1].split("&")
            params = [p for p in params if not p.startswith("sslmode=")]
            db_url = base_url + "?" + "&".join(params) if params else base_url
        else:
            base_url = db_url
        
        if "?" in db_url:
            db_url += "&sslmode=require"
        else:
            db_url += "?sslmode=require"
        print(f"✅ SSL configured for Supabase")
    
    safe_url = mask_database_url(db_url)
    print(f"📦 Connecting to: {safe_url} (ssl={ssl_config})")
    logger.info(f"Connecting to database: {safe_url}")
    
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
            print(f"Attempt {attempt + 1}/{max_retries}...")
            logger.info(f"Database connection attempt {attempt + 1}/{max_retries}")
            
            db_pool = await asyncpg.create_pool(
                dsn=db_url,
                min_size=1,
                max_size=10,
                max_inactive_connection_lifetime=300,
                command_timeout=60,
                timeout=30,
                statement_cache_size=0,
                ssl=ssl_config
            )
            
            # Test the connection
            async with db_pool.acquire() as conn:
                db_version = await conn.fetchval("SELECT version()")
                print(f"✅ Connected to PostgreSQL: {db_version.split(',')[0]}")
                logger.info(f"Successfully connected to PostgreSQL")
                
                test_result = await conn.fetchval("SELECT 1 + 1")
                print(f"✅ Database test query: 1 + 1 = {test_result}")
            
            print("📊 Creating/verifying database tables...")
            logger.info("Creating/verifying database tables")
            await create_tables()
            
            print("✅ Database initialized successfully!")
            logger.info("Database initialized successfully")
            print("=" * 50)
            return
            
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

async def close_db(application=None):
    """Close PostgreSQL database connection pool"""
    global db_pool
    if db_pool:
        print("🔄 Closing database connection pool...")
        await db_pool.close()
        db_pool = None
        print("✅ Database connection pool closed.")

def mask_database_url(url):
    """Mask password in database URL for safe logging"""
    if "postgresql://" in url:
        parts = url.split("@")
        if len(parts) == 2:
            credentials = parts[0].split(":")
            if len(credentials) >= 2:
                return f"{credentials[0]}:***@{parts[1]}"
    return url[:50] + "..."
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

        # Passes table - stores users skipped during search so they are not shown twice
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS passes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            passed_id BIGINT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, passed_id)
        )
        """)
        print("  ✅ passes table")
        
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
        
        # Chat messages table - stores conversation history between matched users
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            sender_id BIGINT NOT NULL,
            recipient_id BIGINT NOT NULL,
            message_type TEXT NOT NULL DEFAULT 'text',
            content TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_sender ON chat_messages(sender_id);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_recipient ON chat_messages(recipient_id);
        CREATE INDEX IF NOT EXISTS idx_chat_messages_created ON chat_messages(created_at);
        """)
        print("  ✅ chat_messages table")
        
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
    """Check if user is a member of the required channel (optional based on CHECK_CHANNEL)"""
    if not CHECK_CHANNEL or not CHANNEL_USERNAME:
        return True
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
    
    # Check if admin is searching for a user
    if 'admin_searching' in context.user_data and user_id == ADMIN_USER_ID:
        await admin_handle_search(update, context)
        return

    # Check if user is submitting a report reason
    if 'reporting_user_id' in context.user_data:
        await report_reason(update, context)
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
                # Store message for conversation history
                await conn.execute(
                    "INSERT INTO chat_messages (sender_id, recipient_id, message_type, content) VALUES ($1, $2, 'text', $3)",
                    user_id, partner_id, update.message.text
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
                # Store photo record for conversation history
                caption_text = update.message.caption or ""
                photo_content = f"[Photo] {caption_text}".strip()
                await conn.execute(
                    "INSERT INTO chat_messages (sender_id, recipient_id, message_type, content) VALUES ($1, $2, 'photo', $3)",
                    user_id, partner_id, photo_content
                )
            except Exception as e:
                print(f"Error sending photo: {e}")
                await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", user_id)
                await conn.execute("DELETE FROM active_chats WHERE user_id = $1 OR partner_id = $1", partner_id)
                await update.message.reply_text("❌ Your partner is no longer available. Chat ended.")

# ---------------- Report System ----------------
async def report_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start report process or handle direct /report <id> <reason>"""
    user_id = update.effective_user.id
    
    # Handle direct command: /report <user_id> <reason>
    if context.args and len(context.args) >= 2:
        try:
            reported_id = int(context.args[0])
            reason = " ".join(context.args[1:]).strip()
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO reports (reporter_id, reported_id, reason) VALUES ($1, $2, $3)",
                    user_id, reported_id, reason
                )
            await update.message.reply_text("✅ Report submitted successfully. Thank you.")
            if ADMIN_USER_ID:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_USER_ID,
                        text=f"<b>🚨 NEW USER REPORT</b>\n\n<b>👤 Reporter:</b> {user_id}\n<b>⚠️ Reported User:</b> {reported_id}\n<b>📝 Reason:</b> {reason}\n\nUse /admin to review.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            return
        except ValueError:
            pass

    # Check if user is in a chat
    async with db_pool.acquire() as conn:
        chat_row = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
        if chat_row:
            partner_id = chat_row['partner_id']
            context.user_data['reporting_user_id'] = partner_id
            
            await update.message.reply_text(
                "<b>⚠️ REPORTING USER</b>\n\n"
                "You are about to report the user you're currently chatting with.\n"
                "Please send a message describing the reason for your report:",
                parse_mode="HTML"
            )
            return
    
    await update.message.reply_text(
        "<b>📢 REPORT A USER</b>\n\n"
        "To report a user, please use:\n"
        "<code>/report &lt;user_id&gt; &lt;reason&gt;</code>\n\n"
        "Or if you are currently chatting with someone, use /report to report them directly.",
        parse_mode="HTML"
    )

async def report_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get report reason and process it"""
    reason = update.message.text.strip()
    user_id = update.effective_user.id
    reported_id = context.user_data.pop('reporting_user_id', None)
    
    if not reported_id:
        await update.message.reply_text("❌ Could not identify the user to report.")
        return
    
    if len(reason) > 500:
        context.user_data['reporting_user_id'] = reported_id
        await update.message.reply_text("❌ Reason too long! Max 500 characters. Please send a shorter reason:")
        return
    
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
        except Exception:
            pass
    
    await update.message.reply_text(
        "✅ Thank you for your report. We will review it and take appropriate action.\n\n"
        "If this was an emergency, please contact the administration directly."
    )

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
        [InlineKeyboardButton("Show Both 👫", callback_data="pref_Both")],
        [InlineKeyboardButton("🔄 Reset Passed Profiles", callback_data="reset_passes")]
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

async def reset_passes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow user to reset their passed profiles to browse them again"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM passes WHERE user_id = $1", user_id)
        
    context.user_data.pop('current_viewed_profile_id', None)
    context.user_data.pop('skipped_ids', None)
    await query.edit_message_text("✅ Passed profiles have been reset! You can now see them again with /find.")

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
        if update.callback_query.data == "find_next":
            prev_id = context.user_data.get('current_viewed_profile_id')
            if prev_id:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO passes (user_id, passed_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        user_id, prev_id
                    )

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

        # Don't show:
        # - Banned users
        # - Users already liked (swipes)
        # - Users already skipped/passed (passes)
        # - Users currently in active chats
        if pref == "Both":
            query = """
            SELECT u.telegram_id, u.name, u.gender, u.campus, u.bio, u.photo_file_id
            FROM users u
            WHERE u.gender IN ('Male', 'Female') 
            AND u.is_banned = FALSE
            AND u.telegram_id != $1
            AND u.telegram_id NOT IN (
                SELECT liked_id FROM swipes WHERE liker_id = $1
            )
            AND u.telegram_id NOT IN (
                SELECT passed_id FROM passes WHERE user_id = $1
            )
            AND u.telegram_id NOT IN (
                SELECT user_id FROM active_chats 
                UNION 
                SELECT partner_id FROM active_chats
            )
            ORDER BY RANDOM()
            LIMIT 1
            """
            params = (user_id,)
        else:
            query = """
            SELECT u.telegram_id, u.name, u.gender, u.campus, u.bio, u.photo_file_id
            FROM users u
            WHERE u.gender = $1 
            AND u.is_banned = FALSE
            AND u.telegram_id != $2
            AND u.telegram_id NOT IN (
                SELECT liked_id FROM swipes WHERE liker_id = $2
            )
            AND u.telegram_id NOT IN (
                SELECT passed_id FROM passes WHERE user_id = $2
            )
            AND u.telegram_id NOT IN (
                SELECT user_id FROM active_chats 
                UNION 
                SELECT partner_id FROM active_chats
            )
            ORDER BY RANDOM()
            LIMIT 1
            """
            params = (pref, user_id)
        
        match = await conn.fetchrow(query, *params)

    if not match:
        text = (
            f"😔 No new profiles matching your preference ({pref}) right now.\n\n"
            "Check back later as new members join, or use /settings to reset your passed profiles."
        )
        if is_callback:
            try:
                await update.callback_query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await update.callback_query.message.reply_text(text)
        else:
            await update.message.reply_text(text)
        return

    match_id = match['telegram_id']
    context.user_data['current_viewed_profile_id'] = match_id
    name = match['name']
    gender = match['gender']
    campus = match['campus']
    bio = match['bio']
    photo = match['photo_file_id']
    
    # Add gender to the display with appropriate emoji
    gender_emoji = "👨" if gender == "Male" else "👩" if gender == "Female" else "⚧"
    
    text = (
        f"🔥 <b>New Profile</b>\n\n"
        f"<b>👤 Name:</b> {name}\n"
        f"<b>{gender_emoji} Gender:</b> {gender}\n"
        f"<b>📍 Campus:</b> {campus}\n"
        f"<b>📝 Bio:</b> {bio or 'Not set'}"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Like", callback_data=f"like_{match_id}"),
         InlineKeyboardButton("➡️ Next", callback_data="find_next")],
        [InlineKeyboardButton("🚫 Report", callback_data=f"report_{match_id}")]
    ])

    if is_callback:
        # DO NOT delete previously shown message; remove its buttons so it stays in chat history
        try:
            await update.callback_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
            
        if photo:
            await context.bot.send_photo(
                chat_id=user_id, 
                photo=photo, 
                caption=text, 
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await context.bot.send_message(
                chat_id=user_id, 
                text=text, 
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    else:
        if photo:
            await update.message.reply_photo(
                photo=photo, 
                caption=text, 
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                text, 
                reply_markup=keyboard,
                parse_mode="HTML"
            )

async def show_my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's own profile"""
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
        
        prompt_text = "⚠️ Please send a message describing the reason for reporting this user:"
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=prompt_text)
            else:
                await query.edit_message_text(text=prompt_text)
        except Exception:
            await query.message.reply_text(prompt_text)
        return
    
    user_id = update.effective_user.id 
    liked_id = int(query.data.split('_')[1]) 

    async with db_pool.acquire() as conn:
        # Insert the like
        await conn.execute("INSERT INTO swipes (liker_id, liked_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, liked_id)
        # Remove from passes if it was there
        await conn.execute("DELETE FROM passes WHERE user_id = $1 AND passed_id = $2", user_id, liked_id)

        # Check if it's a match (the liked user already liked the current user)
        is_match = await conn.fetchrow("SELECT 1 FROM swipes WHERE liker_id = $1 AND liked_id = $2", liked_id, user_id)

        # Get current user's info for notifications
        me = await conn.fetchrow("SELECT name, gender, photo_file_id FROM users WHERE telegram_id = $1", user_id)
        
        # Get liked user's info
        liked_user = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", liked_id)
        liked_name = liked_user['name'] if liked_user else "someone"

    # Send confirmation to the liker that their like was sent
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ You liked <b>{liked_name}</b>! We'll notify you if they like you back.",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Failed to send like confirmation: {e}")

    if is_match:
        # IT'S A MATCH! 🎉
        match_alert = "<b>🎆 BOOM! IT'S A MATCH! 🎆</b>\n\nYou both liked each other! Don't wait, say hi! 👋"
        
        # Check if the matched user is in a chat
        async with db_pool.acquire() as conn:
            liked_user_chat = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", liked_id)
            if liked_user_chat:
                # Notify the liker that the other user is busy
                await query.message.reply_text("🎯 You have a match! However, your match is currently in another conversation. Try again later!")
                return await find_match(update, context)
        
        # Notify the liked user about the match
        await context.bot.send_message(
            chat_id=liked_id, 
            text=f"{match_alert}\n\nMatched with: {me['name']}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Send Message", callback_data=f"chat_{user_id}")]])
        )
        
        # Notify the current user about the match
        await query.message.reply_text(
            text=match_alert,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💬 Start Chatting", callback_data=f"chat_{liked_id}")]])
        )

        # Real-time Match Notification to Admin
        if ADMIN_USER_ID:
            try:
                async with db_pool.acquire() as conn:
                    user1_row = await conn.fetchrow("SELECT name, gender, username, campus FROM users WHERE telegram_id = $1", user_id)
                    user2_row = await conn.fetchrow("SELECT name, gender, username, campus FROM users WHERE telegram_id = $1", liked_id)
                
                u1_name = user1_row['name'] if user1_row else (me['name'] if me else "Unknown")
                u1_gender = user1_row['gender'] if user1_row else (me['gender'] if me else "Unknown")
                u1_user = f"@{user1_row['username']}" if user1_row and user1_row['username'] else "No username"
                u1_campus = user1_row['campus'] if user1_row else "Unknown"

                u2_name = user2_row['name'] if user2_row else liked_name
                u2_gender = user2_row['gender'] if user2_row else "Unknown"
                u2_user = f"@{user2_row['username']}" if user2_row and user2_row['username'] else "No username"
                u2_campus = user2_row['campus'] if user2_row else "Unknown"

                admin_match_msg = (
                    f"🎉 <b>NEW MATCH ALERT!</b>\n\n"
                    f"👤 <b>User 1:</b> {u1_name} ({u1_gender})\n"
                    f"   ├ 🆔 <code>{user_id}</code>\n"
                    f"   ├ 📛 {u1_user}\n"
                    f"   └ 📍 {u1_campus}\n\n"
                    f"👤 <b>User 2:</b> {u2_name} ({u2_gender})\n"
                    f"   ├ 🆔 <code>{liked_id}</code>\n"
                    f"   └ 📛 {u2_user}\n"
                    f"   └ 📍 {u2_campus}\n\n"
                    f"⏰ <b>Matched at:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                admin_kb = [
                    [
                        InlineKeyboardButton(f"👤 {u1_name}", callback_data=f"admin_view_user_{user_id}"),
                        InlineKeyboardButton(f"👤 {u2_name}", callback_data=f"admin_view_user_{liked_id}")
                    ],
                    [
                        InlineKeyboardButton("💬 View Chat History", callback_data=f"admin_view_convo_{min(user_id, liked_id)}_{max(user_id, liked_id)}")
                    ]
                ]
                await context.bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text=admin_match_msg,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(admin_kb)
                )
            except Exception as e:
                logger.error(f"Failed to notify admin of match: {e}")
    else:
        # Not a match yet - remove buttons on the previous card so it stays in chat history
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        
        # Send notification to the liked user that someone liked them
        try:
            gender_emoji = "👨" if me['gender'] == "Male" else "👩" if me['gender'] == "Female" else "⚧"
            caption = f"<b>🔥 SOMEONE LIKED YOU!</b>\n\n{gender_emoji} <b>{me['name']}</b> just swiped right on your profile. Swipe /find to see who it is!"
            
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
        except Exception as e:
            print(f"Failed to send like notification to {liked_id}: {e}")

    # Continue showing more profiles
    return await find_match(update, context)

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
# ---------------- Enhanced Admin Functions ----------------

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user management panel"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📋 All Users", callback_data="admin_list_users")],
        [InlineKeyboardButton("🔍 Search User", callback_data="admin_search_user")],
        [InlineKeyboardButton("🚫 Banned Users", callback_data="admin_banned_users")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
    ]
    
    await query.edit_message_text(
        "<b>👥 USER MANAGEMENT</b>\n\n"
        "Select an option below:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all users with pagination"""
    query = update.callback_query
    await query.answer()
    
    # Get page number from callback or default to 1
    page = int(context.user_data.get('admin_user_page', 1))
    users_per_page = 5
    
    async with db_pool.acquire() as conn:
        # Get total count
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        
        # Get users for current page
        offset = (page - 1) * users_per_page
        users = await conn.fetch("""
            SELECT telegram_id, username, name, gender, campus, is_banned, created_at
            FROM users 
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
        """, users_per_page, offset)
    
    if not users:
        await query.edit_message_text(
            "📭 No users found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_users")]])
        )
        return
    
    # Build message
    text = f"<b>📋 USERS (Page {page}/{max(1, (total_users + users_per_page - 1) // users_per_page)})</b>\n\n"
    
    keyboard = []
    for user in users:
        status = "🔴 BANNED" if user['is_banned'] else "🟢 ACTIVE"
        username_display = f"@{user['username']}" if user['username'] else "No username"
        
        text += f"<b>ID:</b> <code>{user['telegram_id']}</code>\n"
        text += f"<b>Name:</b> {user['name']}\n"
        text += f"<b>Username:</b> {username_display}\n"
        text += f"<b>Gender:</b> {user['gender']}\n"
        text += f"<b>Campus:</b> {user['campus']}\n"
        text += f"<b>Status:</b> {status}\n"
        text += f"<b>Joined:</b> {user['created_at'].strftime('%Y-%m-%d')}\n"
        text += "─" * 30 + "\n"
        
        # Add action buttons for each user
        keyboard.append([
            InlineKeyboardButton(f"👤 {user['name']}", callback_data=f"admin_view_user_{user['telegram_id']}")
        ])
    
    # Pagination buttons
    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"admin_users_page_{page-1}"))
    if offset + users_per_page < total_users:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"admin_users_page_{page+1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton("🔙 Back to User Mgmt", callback_data="admin_users")])
    keyboard.append([InlineKeyboardButton("🏠 Main Admin", callback_data="admin_back")])
    
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_users_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user list pagination"""
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.split('_')[-1])
    context.user_data['admin_user_page'] = page
    
    # Call list users again
    await admin_list_users(update, context)

async def admin_view_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View detailed user information"""
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split('_')[-1])
    
    async with db_pool.acquire() as conn:
        # Get user details
        user = await conn.fetchrow("""
            SELECT * FROM users WHERE telegram_id = $1
        """, user_id)
        
        if not user:
            await query.edit_message_text("❌ User not found.")
            return
        
        # Get user stats
        likes_given = await conn.fetchval("SELECT COUNT(*) FROM swipes WHERE liker_id = $1", user_id)
        likes_received = await conn.fetchval("SELECT COUNT(*) FROM swipes WHERE liked_id = $1", user_id)
        
        # Get matches
        matches = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT s1.liker_id, s1.liked_id 
                FROM swipes s1
                INNER JOIN swipes s2 ON s1.liker_id = s2.liked_id AND s1.liked_id = s2.liker_id
                WHERE s1.liker_id = $1 OR s1.liked_id = $1
            ) as matches
        """, user_id)
        
        # Get reports
        reports_made = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE reporter_id = $1", user_id)
        reports_received = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE reported_id = $1 AND status = 'pending'", user_id)
        
        # Check if currently in chat
        in_chat = await conn.fetchrow("SELECT partner_id FROM active_chats WHERE user_id = $1", user_id)
    
    # Build detailed profile
    username_display = f"@{user['username']}" if user['username'] else "No username"
    status = "🔴 BANNED" if user['is_banned'] else "🟢 ACTIVE"
    chat_status = "💬 In chat" if in_chat else "💤 Not in chat"
    
    profile_text = (
        f"<b>👤 USER DETAILS</b>\n\n"
        f"<b>🆔 Telegram ID:</b> <code>{user['telegram_id']}</code>\n"
        f"<b>📛 Username:</b> {username_display}\n"
        f"<b>✨ Name:</b> {user['name']}\n"
        f"<b>⚧ Gender:</b> {user['gender']}\n"
        f"<b>📍 Campus:</b> {user['campus']}\n"
        f"<b>📝 Bio:</b> {user['bio'] or 'Not set'}\n"
        f"<b>🎯 Hobbies:</b> {user['hobbies'] or 'Not set'}\n"
        f"<b>🎯 Preference:</b> {user['preference']}\n"
        f"<b>📊 Status:</b> {status}\n"
        f"<b>💬 Chat:</b> {chat_status}\n\n"
        f"<b>📈 STATISTICS</b>\n"
        f"<b>❤️ Likes Given:</b> {likes_given}\n"
        f"<b>💖 Likes Received:</b> {likes_received}\n"
        f"<b>💕 Total Matches:</b> {matches}\n"
        f"<b>📝 Reports Made:</b> {reports_made}\n"
        f"<b>⚠️ Reports Received:</b> {reports_received}\n\n"
        f"<b>📅 Joined:</b> {user['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
        f"<b>🕒 Last Active:</b> {user['last_active'].strftime('%Y-%m-%d %H:%M') if user['last_active'] else 'Never'}"
    )
    
    # Action buttons
    keyboard = []
    
    if user['is_banned']:
        keyboard.append([InlineKeyboardButton("✅ Unban User", callback_data=f"admin_unban_{user['telegram_id']}")])
    else:
        keyboard.append([InlineKeyboardButton("🔴 Ban User", callback_data=f"admin_ban_{user['telegram_id']}")])
    
    keyboard.append([InlineKeyboardButton("📨 Send Message", callback_data=f"admin_message_{user['telegram_id']}")])
    keyboard.append([InlineKeyboardButton("📊 View Swipes", callback_data=f"admin_swipes_{user['telegram_id']}")])
    keyboard.append([InlineKeyboardButton("💬 View Chat History", callback_data=f"admin_chat_history_{user['telegram_id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Users", callback_data="admin_list_users")])
    keyboard.append([InlineKeyboardButton("🏠 Main Admin", callback_data="admin_back")])
    
    # Send user photo if exists
    try:
        if user['photo_file_id']:
            await query.message.delete()
            await context.bot.send_photo(
                chat_id=query.from_user.id,
                photo=user['photo_file_id'],
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
    except:
        await query.edit_message_text(
            profile_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def admin_ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban a user"""
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split('_')[-1])
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned = TRUE WHERE telegram_id = $1", user_id)
        
        # Get user info for logging
        user = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", user_id)
    
    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="<b>❌ ACCOUNT BANNED</b>\n\nYour account has been banned by an administrator. If you believe this is a mistake, please contact support.",
            parse_mode="HTML"
        )
    except:
        pass
    
    await query.edit_message_text(
        f"✅ User {user['name']} ({user_id}) has been banned.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_list_users")]])
    )

async def admin_unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban a user"""
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split('_')[-1])
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned = FALSE WHERE telegram_id = $1", user_id)
        
        # Get user info for logging
        user = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", user_id)
    
    # Notify user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="<b>✅ ACCOUNT UNBANNED</b>\n\nYour account has been unbanned. You can now use the bot again.",
            parse_mode="HTML"
        )
    except:
        pass
    
    await query.edit_message_text(
        f"✅ User {user['name']} ({user_id}) has been unbanned.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_list_users")]])
    )

async def admin_banned_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all banned users"""
    query = update.callback_query
    await query.answer()
    
    async with db_pool.acquire() as conn:
        users = await conn.fetch("""
            SELECT telegram_id, name, username, created_at 
            FROM users 
            WHERE is_banned = TRUE
            ORDER BY updated_at DESC
        """)
    
    if not users:
        await query.edit_message_text(
            "✅ No banned users.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_users")]])
        )
        return
    
    text = "<b>🚫 BANNED USERS</b>\n\n"
    keyboard = []
    
    for user in users:
        username_display = f"(@{user['username']})" if user['username'] else ""
        text += f"<b>👤 {user['name']}</b> {username_display}\n"
        text += f"<b>ID:</b> <code>{user['telegram_id']}</code>\n"
        text += f"<b>Banned since:</b> {user['created_at'].strftime('%Y-%m-%d')}\n"
        text += "─" * 30 + "\n"
        
        keyboard.append([InlineKeyboardButton(f"✅ Unban {user['name']}", callback_data=f"admin_unban_{user['telegram_id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_users")])
    
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start user search"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['admin_searching'] = True
    
    await query.edit_message_text(
        "<b>🔍 SEARCH USER</b>\n\n"
        "Send me the Telegram ID, username, or name of the user you want to search for.\n\n"
        "Type /cancel to cancel.",
        parse_mode="HTML"
    )

async def admin_handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user search query"""
    if 'admin_searching' not in context.user_data:
        return
    
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        return
    
    search_term = update.message.text.strip()
    
    # Cancel search
    if search_term.startswith('/cancel'):
        context.user_data.pop('admin_searching', None)
        await update.message.reply_text("Search cancelled.")
        return
    
    async with db_pool.acquire() as conn:
        # Try to search by telegram_id (exact match)
        try:
            telegram_id = int(search_term)
            users = await conn.fetch("SELECT * FROM users WHERE telegram_id = $1", telegram_id)
        except ValueError:
            # Search by username or name
            users = await conn.fetch("""
                SELECT * FROM users 
                WHERE username ILIKE $1 OR name ILIKE $1
                ORDER BY created_at DESC
                LIMIT 10
            """, f"%{search_term}%")
    
    if not users:
        await update.message.reply_text("❌ No users found matching your search.")
        return
    
    # Show search results
    text = f"<b>🔍 SEARCH RESULTS for '{search_term}'</b>\n\n"
    keyboard = []
    
    for user in users:
        status = "🔴 BANNED" if user['is_banned'] else "🟢 ACTIVE"
        username_display = f"@{user['username']}" if user['username'] else "No username"
        
        text += f"<b>👤 {user['name']}</b>\n"
        text += f"<b>ID:</b> <code>{user['telegram_id']}</code>\n"
        text += f"<b>Username:</b> {username_display}\n"
        text += f"<b>Status:</b> {status}\n"
        text += "─" * 30 + "\n"
        
        keyboard.append([InlineKeyboardButton(f"View {user['name']}", callback_data=f"admin_view_user_{user['telegram_id']}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_users")])
    
    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    context.user_data.pop('admin_searching', None)

# ---------------- Enhanced Broadcast System ----------------

# Broadcast states (make sure these numbers don't conflict with other states)
BROADCAST_TEXT, BROADCAST_MEDIA = range(16, 18)  # Using 16 and 17 to avoid conflicts

async def admin_broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show broadcast options"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📝 Text Only", callback_data="broadcast_text")],
        [InlineKeyboardButton("🖼️ Photo + Caption", callback_data="broadcast_photo")],
        [InlineKeyboardButton("🎥 Video + Caption", callback_data="broadcast_video")],
        [InlineKeyboardButton("📎 Document + Caption", callback_data="broadcast_document")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
    ]
    
    await query.edit_message_text(
        "<b>📢 BROADCAST MENU</b>\n\n"
        "Choose what type of content you want to broadcast to all users:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broadcast process based on type"""
    query = update.callback_query
    await query.answer()
    
    broadcast_type = query.data.replace("broadcast_", "")
    context.user_data['broadcast_type'] = broadcast_type
    context.user_data['broadcasting'] = True
    
    messages = {
        "text": "📝 Send the text message you want to broadcast:",
        "photo": "🖼️ Send the photo you want to broadcast (as a photo, not file):",
        "video": "🎥 Send the video you want to broadcast:",
        "document": "📎 Send the document you want to broadcast:"
    }
    
    await query.edit_message_text(
        f"<b>📢 BROADCAST</b>\n\n{messages[broadcast_type]}\n\nType /cancel to cancel.",
        parse_mode="HTML"
    )
    
    # Return the appropriate state
    if broadcast_type == "text":
        return BROADCAST_TEXT
    else:
        return BROADCAST_MEDIA

async def broadcast_receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and process text broadcast"""
    print("📝 broadcast_receive_text called")
    
    if 'broadcast_type' not in context.user_data:
        print("❌ No broadcast_type in user_data")
        await update.message.reply_text("❌ Broadcast session expired. Please start over.")
        return ConversationHandler.END
    
    text = update.message.text
    
    # Cancel if requested
    if text.startswith('/cancel'):
        context.user_data.clear()
        await update.message.reply_text("Broadcast cancelled.")
        return ConversationHandler.END
    
    # Store the text
    context.user_data['broadcast_text'] = text
    print(f"✅ Stored broadcast text: {text[:50]}...")
    
    # Create keyboard with buttons
    keyboard = [
        [InlineKeyboardButton("✅ Send to All Users", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send preview
    preview_text = f"<b>📢 BROADCAST PREVIEW</b>\n\n{text}"
    
    await update.message.reply_text(
        preview_text,
        parse_mode="HTML",
        reply_markup=reply_markup
    )
    
    print("✅ Preview sent with buttons")
    return ConversationHandler.END

async def broadcast_receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive and process media broadcast"""
    print("📸 broadcast_receive_media called")
    
    if 'broadcast_type' not in context.user_data:
        print("❌ No broadcast_type in user_data")
        await update.message.reply_text("❌ Broadcast session expired. Please start over.")
        return ConversationHandler.END
    
    broadcast_type = context.user_data['broadcast_type']
    print(f"Broadcast type: {broadcast_type}")
    
    # Store media info based on type
    if broadcast_type == "photo" and update.message.photo:
        context.user_data['broadcast_media'] = update.message.photo[-1].file_id
        context.user_data['broadcast_caption'] = update.message.caption or ""
        print(f"✅ Stored photo: {context.user_data['broadcast_media']}")
        print(f"✅ Stored caption: {context.user_data['broadcast_caption']}")
        
    elif broadcast_type == "video" and update.message.video:
        context.user_data['broadcast_media'] = update.message.video.file_id
        context.user_data['broadcast_caption'] = update.message.caption or ""
        print(f"✅ Stored video: {context.user_data['broadcast_media']}")
        
    elif broadcast_type == "document" and update.message.document:
        context.user_data['broadcast_media'] = update.message.document.file_id
        context.user_data['broadcast_caption'] = update.message.caption or ""
        print(f"✅ Stored document: {context.user_data['broadcast_media']}")
        
    else:
        await update.message.reply_text(f"❌ Please send a valid {broadcast_type}.")
        return BROADCAST_MEDIA
    
    # Show preview immediately
    await show_broadcast_preview(update, context)
    return ConversationHandler.END

async def show_broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show broadcast preview before sending"""
    print("🖼️ show_broadcast_preview called")
    
    broadcast_type = context.user_data.get('broadcast_type')
    caption = context.user_data.get('broadcast_caption', "")
    
    if not broadcast_type:
        print("❌ No broadcast_type found")
        await update.message.reply_text("❌ Error: Broadcast type not found. Please start over.")
        return
    
    # Create keyboard with buttons
    keyboard = [
        [InlineKeyboardButton("✅ Send to All Users", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    preview_text = f"<b>📢 BROADCAST PREVIEW</b>\n\n"
    if caption:
        preview_text += f"<b>Caption:</b> {caption}\n\n"
    
    # Send preview based on type
    try:
        if broadcast_type == "photo":
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=context.user_data['broadcast_media'],
                caption=preview_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        elif broadcast_type == "video":
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=context.user_data['broadcast_media'],
                caption=preview_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        elif broadcast_type == "document":
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=context.user_data['broadcast_media'],
                caption=preview_text,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:  # text
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=preview_text + context.user_data.get('broadcast_text', ''),
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        print("✅ Preview sent successfully with buttons")
    except Exception as e:
        print(f"❌ Error sending preview: {e}")
        await update.message.reply_text(f"❌ Error: {e}")

async def broadcast_wizard_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and send wizard broadcast to all users"""
    print("✅ broadcast_wizard_confirm called!")
    query = update.callback_query
    await query.answer()
    
    print(f"User data: {context.user_data}")
    
    await query.edit_message_text("📤 Broadcasting to all users... This may take a while.")
    
    # Get all users
    try:
        async with db_pool.acquire() as conn:
            users = await conn.fetch("SELECT telegram_id FROM users WHERE is_banned = FALSE")
    except Exception as e:
        print(f"❌ Database error: {e}")
        await query.edit_message_text("❌ Error accessing database.")
        return
    
    if not users:
        await query.edit_message_text(
            "❌ No users found in database.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
        )
        context.user_data.clear()
        return
    
    total = len(users)
    success = 0
    failed = 0
    failed_users = []
    
    broadcast_type = context.user_data.get('broadcast_type', 'text')
    media_id = context.user_data.get('broadcast_media')
    caption = context.user_data.get('broadcast_caption', "")
    text = context.user_data.get('broadcast_text', "")
    
    # Add broadcast header
    header = "<b>📢 ADMIN ANNOUNCEMENT</b>\n\n"
    full_caption = header + caption
    full_text = header + text
    
    # Send to each user
    for i, user in enumerate(users):
        try:
            if broadcast_type == "photo":
                await context.bot.send_photo(
                    chat_id=user['telegram_id'],
                    photo=media_id,
                    caption=full_caption,
                    parse_mode="HTML"
                )
            elif broadcast_type == "video":
                await context.bot.send_video(
                    chat_id=user['telegram_id'],
                    video=media_id,
                    caption=full_caption,
                    parse_mode="HTML"
                )
            elif broadcast_type == "document":
                await context.bot.send_document(
                    chat_id=user['telegram_id'],
                    document=media_id,
                    caption=full_caption,
                    parse_mode="HTML"
                )
            else:  # text
                await context.bot.send_message(
                    chat_id=user['telegram_id'],
                    text=full_text,
                    parse_mode="HTML"
                )
            success += 1
            
            # Update progress every 10 users
            if i % 10 == 0 and i > 0:
                try:
                    await query.message.edit_text(f"📤 Broadcasting... {i}/{total} sent")
                except:
                    pass  # Message might be too old to edit
                
        except Exception as e:
            failed += 1
            failed_users.append(str(user['telegram_id']))
            print(f"Failed to send to {user['telegram_id']}: {e}")
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.1)
    
    # Clear broadcast data
    context.user_data.clear()
    
    # Send report
    report_text = (
        f"<b>📢 BROADCAST COMPLETE</b>\n\n"
        f"<b>✅ Successful:</b> {success}\n"
        f"<b>❌ Failed:</b> {failed}\n"
        f"<b>👥 Total Users:</b> {total}\n"
    )
    
    if failed_users:
        report_text += f"\n<b>Failed Users:</b> {', '.join(failed_users[:10])}"
        if len(failed_users) > 10:
            report_text += f" and {len(failed_users) - 10} more..."
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]]
    
    try:
        await query.message.edit_text(
            report_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except:
        # If message can't be edited, send new message
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=report_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def broadcast_wizard_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel wizard broadcast"""
    print("❌ broadcast_wizard_cancel called")
    query = update.callback_query
    await query.answer()
    
    context.user_data.clear()
    
    await query.edit_message_text(
        "❌ Broadcast cancelled.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]])
    )
# ---------------- Updated Admin Panel ----------------

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel"""
    user_id = update.effective_user.id
    
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to access this command.")
        return
    
    keyboard = [
        [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🚨 Reports", callback_data="admin_reports")],
        [InlineKeyboardButton("💬 Chat Logs", callback_data="admin_chat_logs")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_menu")],
        [InlineKeyboardButton("📝 System Logs", callback_data="admin_logs")],
        [InlineKeyboardButton("❌ Close Panel", callback_data="admin_close")]
    ]
    
    await update.message.reply_text(
        "<b>🔧 ADMIN PANEL</b>\n\n"
        "Welcome to the administrator dashboard. Select an option below:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent system logs with gender and chat activity"""
    query = update.callback_query
    await query.answer()
    
    async with db_pool.acquire() as conn:
        recent_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '24 hours'") or 0
        recent_boys = await conn.fetchval("SELECT COUNT(*) FROM users WHERE (gender = 'Male' OR LOWER(gender) IN ('male', 'boy')) AND created_at > NOW() - INTERVAL '24 hours'") or 0
        recent_girls = await conn.fetchval("SELECT COUNT(*) FROM users WHERE (gender = 'Female' OR LOWER(gender) IN ('female', 'girl')) AND created_at > NOW() - INTERVAL '24 hours'") or 0
        
        recent_matches = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT s1.liker_id, s1.liked_id 
                FROM swipes s1
                INNER JOIN swipes s2 ON s1.liker_id = s2.liked_id AND s1.liked_id = s2.liker_id
                WHERE s1.created_at > NOW() - INTERVAL '24 hours'
            ) as matches
        """) or 0
        
        active_chats = await conn.fetchval("SELECT COUNT(*) FROM active_chats") or 0
        recent_messages = await conn.fetchval("SELECT COUNT(*) FROM chat_messages WHERE created_at > NOW() - INTERVAL '24 hours'") or 0
    
    log_text = (
        f"<b>📝 SYSTEM LOGS (Last 24h)</b>\n\n"
        f"<b>👥 New Users:</b> {recent_users}\n"
        f"   ├ 👦 Boys: +{recent_boys}\n"
        f"   └ 👧 Girls: +{recent_girls}\n\n"
        f"<b>💕 New Matches:</b> {recent_matches}\n"
        f"<b>💬 Active Chats:</b> {active_chats}\n"
        f"<b>📨 Stored Messages (24h):</b> {recent_messages}\n\n"
        f"<b>🕒 Server Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"<b>✅ Bot Status:</b> Online\n"
        f"<b>📦 Database:</b> Connected"
    )
    
    keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]]
    await query.edit_message_text(log_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def get_stats_data():
    """Helper to fetch all statistics from database including boys and girls breakdown"""
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        
        # Boys and Girls counts
        boys_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE gender = 'Male' OR LOWER(gender) IN ('male', 'boy')") or 0
        girls_count = await conn.fetchval("SELECT COUNT(*) FROM users WHERE gender = 'Female' OR LOWER(gender) IN ('female', 'girl')") or 0
        
        boys_pct = (boys_count / total_users * 100) if total_users > 0 else 0
        girls_pct = (girls_count / total_users * 100) if total_users > 0 else 0
        
        # 24-hour registrations by gender
        new_boys_24h = await conn.fetchval("SELECT COUNT(*) FROM users WHERE (gender = 'Male' OR LOWER(gender) IN ('male', 'boy')) AND created_at > NOW() - INTERVAL '24 hours'") or 0
        new_girls_24h = await conn.fetchval("SELECT COUNT(*) FROM users WHERE (gender = 'Female' OR LOWER(gender) IN ('female', 'girl')) AND created_at > NOW() - INTERVAL '24 hours'") or 0
        
        # Active users (created or active within 7 days)
        active_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '7 days' OR last_active > NOW() - INTERVAL '7 days'") or 0
        
        # Banned users
        banned_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned = TRUE") or 0
        
        # Total matches
        total_matches = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT s1.liker_id, s1.liked_id 
                FROM swipes s1
                INNER JOIN swipes s2 ON s1.liker_id = s2.liked_id AND s1.liked_id = s2.liker_id
                WHERE s1.liker_id < s1.liked_id
            ) as matches
        """) or 0
        
        # Total reports
        pending_reports = await conn.fetchval("SELECT COUNT(*) FROM reports WHERE status = 'pending'") or 0
        
        # Active chats
        active_chats = await conn.fetchval("SELECT COUNT(*) FROM active_chats") or 0
        
        # Total stored messages
        total_messages = await conn.fetchval("SELECT COUNT(*) FROM chat_messages") or 0

    stats_text = (
        f"<b>📊 BOT STATISTICS</b>\n\n"
        f"<b>👥 Total Registered Users:</b> {total_users}\n"
        f"   ├ 👦 <b>Boys:</b> {boys_count} ({boys_pct:.1f}%)\n"
        f"   └ 👧 <b>Girls:</b> {girls_count} ({girls_pct:.1f}%)\n\n"
        f"<b>📈 Activity (Last 24 Hours):</b>\n"
        f"   ├ 👦 New Boys: +{new_boys_24h}\n"
        f"   └ 👧 New Girls: +{new_girls_24h}\n\n"
        f"<b>⚡ Active Users (7 days):</b> {active_users}\n"
        f"<b>💖 Total Matches:</b> {total_matches}\n"
        f"<b>💬 Active Relayed Chats:</b> {active_chats}\n"
        f"<b>📨 Stored Chat Messages:</b> {total_messages}\n"
        f"<b>🚨 Pending Reports:</b> {pending_reports}\n"
        f"<b>🚫 Banned Users:</b> {banned_users}\n\n"
        f"<b>📅 Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return stats_text

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show statistics via callback query"""
    query = update.callback_query
    await query.answer()
    
    stats_text = await get_stats_data()
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]
    ]
    await query.edit_message_text(stats_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct /stats command for admin"""
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ This command is restricted to administrators.")
        return
    
    stats_text = await get_stats_data()
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
        [InlineKeyboardButton("🏠 Main Admin", callback_data="admin_back")]
    ]
    await update.message.reply_text(stats_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_chat_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display recent conversations stored in the database"""
    query = update.callback_query
    await query.answer()
    
    async with db_pool.acquire() as conn:
        recent_pairs = await conn.fetch("""
            SELECT 
                LEAST(sender_id, recipient_id) as u1,
                GREATEST(sender_id, recipient_id) as u2,
                COUNT(*) as msg_count,
                MAX(created_at) as last_msg_time
            FROM chat_messages
            GROUP BY LEAST(sender_id, recipient_id), GREATEST(sender_id, recipient_id)
            ORDER BY last_msg_time DESC
            LIMIT 10
        """)
        
        if not recent_pairs:
            text = (
                "<b>💬 STORED CONVERSATIONS</b>\n\n"
                "ℹ️ No conversations have been recorded yet.\n"
                "Messages exchanged between matched users during active chats will appear here."
            )
            keyboard = [[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")]]
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        
        text = "<b>💬 RECENT CONVERSATIONS</b>\n\nClick any conversation below to inspect messages:\n\n"
        keyboard = []
        
        for pair in recent_pairs:
            u1, u2 = pair['u1'], pair['u2']
            count = pair['msg_count']
            time_str = pair['last_msg_time'].strftime("%m/%d %H:%M")
            
            u1_row = await conn.fetchrow("SELECT name, gender FROM users WHERE telegram_id = $1", u1)
            u2_row = await conn.fetchrow("SELECT name, gender FROM users WHERE telegram_id = $1", u2)
            
            u1_label = u1_row['name'] if u1_row else f"User {u1}"
            u2_label = u2_row['name'] if u2_row else f"User {u2}"
            
            text += f"• <b>{u1_label}</b> ↔️ <b>{u2_label}</b>\n"
            text += f"  └ <i>{count} messages | Last: {time_str}</i>\n"
            
            btn_title = f"💬 {u1_label[:10]} & {u2_label[:10]} ({count})"
            keyboard.append([InlineKeyboardButton(btn_title, callback_data=f"admin_view_convo_{u1}_{u2}")])
            
        keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_back")])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_view_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View message history between two specific users"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    # pattern: admin_view_convo_{u1}_{u2}
    u1 = int(parts[-2])
    u2 = int(parts[-1])
    
    async with db_pool.acquire() as conn:
        u1_row = await conn.fetchrow("SELECT name, username FROM users WHERE telegram_id = $1", u1)
        u2_row = await conn.fetchrow("SELECT name, username FROM users WHERE telegram_id = $1", u2)
        
        u1_name = u1_row['name'] if u1_row else f"User {u1}"
        u2_name = u2_row['name'] if u2_row else f"User {u2}"
        
        messages = await conn.fetch("""
            SELECT cm.sender_id, cm.content, cm.created_at, cm.message_type
            FROM chat_messages cm
            WHERE (cm.sender_id = $1 AND cm.recipient_id = $2)
               OR (cm.sender_id = $2 AND cm.recipient_id = $1)
            ORDER BY cm.created_at ASC
            LIMIT 30
        """, u1, u2)
        
    text = (
        f"<b>📜 CONVERSATION TRANSCRIPT</b>\n"
        f"👥 <b>{u1_name}</b> (<code>{u1}</code>) ↔️ <b>{u2_name}</b> (<code>{u2}</code>)\n"
        f"─" * 30 + "\n\n"
    )
    
    if not messages:
        text += "<i>No messages recorded between these two users.</i>"
    else:
        for msg in messages:
            sender = u1_name if msg['sender_id'] == u1 else u2_name
            time_str = msg['created_at'].strftime("%H:%M:%S")
            content = msg['content'] or ""
            safe_content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            text += f"<b>[{time_str}] {sender}:</b> {safe_content}\n"
            
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>... [truncated due to length] ...</i>"
        
    keyboard = [
        [
            InlineKeyboardButton(f"👤 {u1_name}", callback_data=f"admin_view_user_{u1}"),
            InlineKeyboardButton(f"👤 {u2_name}", callback_data=f"admin_view_user_{u2}")
        ],
        [InlineKeyboardButton("🔙 Back to Chat Logs", callback_data="admin_chat_logs")],
        [InlineKeyboardButton("🏠 Main Admin", callback_data="admin_back")]
    ]
    
    try:
        if query.message.photo:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def admin_chat_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View recent chat history for a single user"""
    query = update.callback_query
    await query.answer()
    
    user_id = int(query.data.split('_')[-1])
    
    async with db_pool.acquire() as conn:
        user_row = await conn.fetchrow("SELECT name, username FROM users WHERE telegram_id = $1", user_id)
        user_name = user_row['name'] if user_row else f"User {user_id}"
        
        messages = await conn.fetch("""
            SELECT cm.sender_id, cm.recipient_id, cm.content, cm.created_at, cm.message_type
            FROM chat_messages cm
            WHERE cm.sender_id = $1 OR cm.recipient_id = $1
            ORDER BY cm.created_at ASC
            LIMIT 30
        """, user_id)
        
    text = (
        f"<b>📜 USER CHAT HISTORY</b>\n"
        f"👤 <b>{user_name}</b> (<code>{user_id}</code>)\n"
        f"─" * 30 + "\n\n"
    )
    
    if not messages:
        text += "<i>No messages recorded for this user yet.</i>"
    else:
        for msg in messages:
            direction = "➡️ Sent to" if msg['sender_id'] == user_id else "⬅️ Received from"
            other_id = msg['recipient_id'] if msg['sender_id'] == user_id else msg['sender_id']
            time_str = msg['created_at'].strftime("%m/%d %H:%M")
            content = (msg['content'] or "").replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            text += f"<b>[{time_str}]</b> {direction} <code>{other_id}</code>:\n{content}\n\n"
            
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>... [truncated due to length] ...</i>"
        
    keyboard = [
        [InlineKeyboardButton(f"👤 Back to {user_name}", callback_data=f"admin_view_user_{user_id}")],
        [InlineKeyboardButton("🔙 Back to Chat Logs", callback_data="admin_chat_logs")],
        [InlineKeyboardButton("🏠 Main Admin", callback_data="admin_back")]
    ]
    
    try:
        if query.message.photo:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def admin_chatlogs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct /chatlogs command: /chatlogs <user_id> or /chatlogs <u1> <u2>"""
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ This command is restricted to administrators.")
        return
        
    if not context.args:
        help_msg = (
            "<b>💬 CHAT LOGS ACCESS</b>\n\n"
            "<b>Usage:</b>\n"
            "• <code>/chatlogs &lt;user_id&gt;</code> — View recent messages sent/received by this user\n"
            "• <code>/chatlogs &lt;user1_id&gt; &lt;user2_id&gt;</code> — View direct conversation between two users\n\n"
            "You can also access chat logs interactively from <code>/admin</code> $\rightarrow$ <b>💬 Chat Logs</b>."
        )
        await update.message.reply_text(help_msg, parse_mode="HTML")
        return
        
    if len(context.args) == 1:
        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Must be numeric.")
            return
            
        async with db_pool.acquire() as conn:
            user_row = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", target_id)
            user_name = user_row['name'] if user_row else f"User {target_id}"
            
            messages = await conn.fetch("""
                SELECT cm.sender_id, cm.recipient_id, cm.content, cm.created_at
                FROM chat_messages cm
                WHERE cm.sender_id = $1 OR cm.recipient_id = $1
                ORDER BY cm.created_at ASC
                LIMIT 30
            """, target_id)
            
        text = f"<b>📜 CHAT LOGS FOR {user_name} (<code>{target_id}</code>)</b>\n" + "─" * 30 + "\n\n"
        if not messages:
            text += "<i>No messages found for this user.</i>"
        else:
            for msg in messages:
                direction = "➡️ Sent to" if msg['sender_id'] == target_id else "⬅️ Received from"
                other_id = msg['recipient_id'] if msg['sender_id'] == target_id else msg['sender_id']
                time_str = msg['created_at'].strftime("%m/%d %H:%M")
                content = (msg['content'] or "").replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                text += f"<b>[{time_str}]</b> {direction} <code>{other_id}</code>:\n{content}\n\n"
                
        if len(text) > 4000:
            text = text[:3950] + "\n\n<i>... [truncated] ...</i>"
        await update.message.reply_text(text, parse_mode="HTML")
        return

    # Two user IDs provided
    try:
        u1 = int(context.args[0])
        u2 = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Both user IDs must be numeric.")
        return
        
    async with db_pool.acquire() as conn:
        u1_row = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", u1)
        u2_row = await conn.fetchrow("SELECT name FROM users WHERE telegram_id = $1", u2)
        u1_name = u1_row['name'] if u1_row else f"User {u1}"
        u2_name = u2_row['name'] if u2_row else f"User {u2}"
        
        messages = await conn.fetch("""
            SELECT cm.sender_id, cm.content, cm.created_at
            FROM chat_messages cm
            WHERE (cm.sender_id = $1 AND cm.recipient_id = $2)
               OR (cm.sender_id = $2 AND cm.recipient_id = $1)
            ORDER BY cm.created_at ASC
            LIMIT 30
        """, u1, u2)
        
    text = f"<b>📜 CONVERSATION: {u1_name} ↔️ {u2_name}</b>\n" + "─" * 30 + "\n\n"
    if not messages:
        text += "<i>No messages recorded between these two users.</i>"
    else:
        for msg in messages:
            sender = u1_name if msg['sender_id'] == u1 else u2_name
            time_str = msg['created_at'].strftime("%H:%M:%S")
            content = (msg['content'] or "").replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            text += f"<b>[{time_str}] {sender}:</b> {content}\n"
            
    if len(text) > 4000:
        text = text[:3950] + "\n\n<i>... [truncated] ...</i>"
    await update.message.reply_text(text, parse_mode="HTML")

async def admin_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close admin panel"""
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        await query.edit_message_text("👋 Admin panel closed.")

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
        [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("🚨 Reports", callback_data="admin_reports")],
        [InlineKeyboardButton("💬 Chat Logs", callback_data="admin_chat_logs")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_menu")],
        [InlineKeyboardButton("📝 System Logs", callback_data="admin_logs")],
        [InlineKeyboardButton("❌ Close Panel", callback_data="admin_close")]
    ]
    
    panel_text = (
        "<b>🔧 ADMIN PANEL</b>\n\n"
        "Welcome to the administrator dashboard. Select an option below:"
    )
    
    try:
        if query.message.photo:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=panel_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                panel_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception:
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=panel_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
# ---------------- Simplified Broadcast System ----------------

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast any message by replying to it - ADMIN ONLY"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ This command is for admins only.")
        return
    
    # Check if replying to a message
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "📢 <b>Broadcast Command</b>\n\n"
            "To broadcast a message:\n"
            "1. Find any message (text, photo, video, etc.)\n"
            "2. Reply to it with /broadcast\n"
            "3. Confirm the broadcast",
            parse_mode="HTML"
        )
        return
    
    # Store the message to broadcast
    context.user_data['broadcast_from_chat_id'] = update.message.reply_to_message.chat_id
    context.user_data['broadcast_message_id'] = update.message.reply_to_message.message_id
    
    # Create preview
    preview_text = "📢 <b>Broadcast Preview</b>\n\n"
    preview_text += "The following message will be sent to all users:\n\n"
    
    msg = update.message.reply_to_message
    if msg.photo:
        preview_text += "📷 <i>[Photo" + (" with caption" if msg.caption else "") + "]</i>"
    elif msg.video:
        preview_text += "🎥 <i>[Video" + (" with caption" if msg.caption else "") + "]</i>"
    elif msg.document:
        preview_text += "📄 <i>[Document" + (" with caption" if msg.caption else "") + "]</i>"
    elif msg.sticker:
        preview_text += "🎭 <i>[Sticker]</i>"
    elif msg.animation:
        preview_text += "🎬 <i>[GIF/Animation" + (" with caption" if msg.caption else "") + "]</i>"
    elif msg.text:
        preview_text += f"💬 <i>\"{msg.text[:100]}\"</i>"
        if len(msg.text) > 100:
            preview_text += "..."
    else:
        preview_text += "❓ <i>[Unsupported message type]</i>"
    
    # Confirmation buttons
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, Broadcast", callback_data="confirm_broadcast"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")
        ]
    ]
    
    await update.message.reply_text(
        preview_text + "\n\n⚠️ <b>Confirm Broadcast</b>\n\nAre you sure you want to broadcast this message to all users?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def broadcast_reply_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm and send reply-based broadcast"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id != ADMIN_USER_ID:
        await query.answer("Unauthorized.", show_alert=True)
        return
    
    # Get stored message info
    from_chat_id = context.user_data.get('broadcast_from_chat_id')
    msg_id = context.user_data.get('broadcast_message_id')
    
    if not from_chat_id or not msg_id:
        await query.edit_message_text("❌ Error: Message data not found.")
        context.user_data.clear()
        return
    
    # Get all active users (non-banned)
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT telegram_id FROM users WHERE is_banned = FALSE")
    
    if not users:
        await query.edit_message_text("❌ No users found in database.")
        context.user_data.clear()
        return
    
    total = len(users)
    successful = 0
    failed = 0
    
    # Send progress message
    progress_msg = await query.message.reply_text(f"📤 Broadcasting... 0/{total}")
    
    for i, user in enumerate(users):
        try:
            # copy_message works for ALL message types!
            await context.bot.copy_message(
                chat_id=user['telegram_id'],
                from_chat_id=from_chat_id,
                message_id=msg_id
            )
            successful += 1
        except Exception as e:
            failed += 1
            print(f"Failed to send to {user['telegram_id']}: {e}")
        
        # Update progress every 10 users
        if i % 10 == 0 and i > 0:
            try:
                await progress_msg.edit_text(f"📤 Broadcasting... {successful + failed}/{total}")
            except:
                pass
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.05)
    
    # Final report
    await progress_msg.edit_text(
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"✅ Successful: {successful}\n"
        f"❌ Failed: {failed}\n"
        f"👥 Total: {total}",
        parse_mode="HTML"
    )
    
    await query.edit_message_text("✅ Broadcast completed.")
    context.user_data.clear()

async def broadcast_reply_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel reply-based broadcast"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("❌ Broadcast cancelled.")
    context.user_data.clear()
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
        EDIT_HOBBIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_hobbies_input), CallbackQueryHandler(edit_hobbies_input, pattern="^skip$")]
    },
    fallbacks=[CommandHandler('cancel', cancel)],
    per_message=False
)

# ---------------- MAIN FUNCTION (POLLING & WEBHOOK DUAL-MODE) ----------------
async def main():
    """Main bot entrypoint supporting both long-polling and webhook mode"""
    validate_config()
    
    # Initialize database
    print("🔄 Initializing database...")
    try:
        await init_db()
        print("✅ Database initialized successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")
        return

    # Create Telegram application
    print("🤖 Building Telegram bot application...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    print("🔧 Registering handlers...")
    
    # Registration conversation handler
    app.add_handler(conv_handler)
    
    # Commands
    app.add_handler(CommandHandler("find", find_match))
    app.add_handler(CommandHandler("myprofile", show_my_profile))
    app.add_handler(CommandHandler("settings", set_preference))
    app.add_handler(CommandHandler("stop", stop_chat))
    app.add_handler(CommandHandler("report", report_user))
    app.add_handler(CommandHandler("requests", view_requests))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("stats", admin_stats_command))
    app.add_handler(CommandHandler("chatlogs", admin_chatlogs_command))
    app.add_handler(CommandHandler("debug", debug_db))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(handle_like, pattern="^(like_|report_)"))
    app.add_handler(CallbackQueryHandler(start_chat, pattern="^chat_"))
    app.add_handler(CallbackQueryHandler(find_match, pattern="find_next"))
    app.add_handler(CallbackQueryHandler(save_preference, pattern="^pref_"))
    app.add_handler(CallbackQueryHandler(reset_passes_callback, pattern="^reset_passes$"))
    app.add_handler(CallbackQueryHandler(start_edit_profile, pattern="^start_edit_profile$"))
    app.add_handler(CallbackQueryHandler(handle_edit_existing, pattern="^edit_(name|gender|campus|photo|bio|hobbies)_existing$"))
    app.add_handler(CallbackQueryHandler(handle_save_edit, pattern="^(save_gender_|save_campus_|skip_)"))
    app.add_handler(CallbackQueryHandler(finish_edit, pattern="^finish_edit$"))
    app.add_handler(CallbackQueryHandler(check_channel_callback, pattern="^check_channel$"))
    
    # Broadcast callback handlers (separated to prevent collisions)
    app.add_handler(CallbackQueryHandler(broadcast_reply_confirm, pattern="^confirm_broadcast$"))
    app.add_handler(CallbackQueryHandler(broadcast_reply_cancel, pattern="^cancel_broadcast$"))
    app.add_handler(CallbackQueryHandler(broadcast_wizard_confirm, pattern="^broadcast_confirm$"))
    app.add_handler(CallbackQueryHandler(broadcast_wizard_cancel, pattern="^broadcast_cancel$"))
    
    # Admin callbacks
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_chat_logs, pattern="^admin_chat_logs$"))
    app.add_handler(CallbackQueryHandler(admin_view_conversation, pattern="^admin_view_convo_"))
    app.add_handler(CallbackQueryHandler(admin_chat_history, pattern="^admin_chat_history_"))
    app.add_handler(CallbackQueryHandler(admin_close, pattern="^admin_close$"))
    app.add_handler(CallbackQueryHandler(admin_reports, pattern="^admin_reports$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_handle_report, pattern="^(approve_|reject_)"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_list_users, pattern="^admin_list_users$"))
    app.add_handler(CallbackQueryHandler(admin_users_page, pattern="^admin_users_page_"))
    app.add_handler(CallbackQueryHandler(admin_view_user, pattern="^admin_view_user_"))
    app.add_handler(CallbackQueryHandler(admin_ban_user, pattern="^admin_ban_"))
    app.add_handler(CallbackQueryHandler(admin_unban_user, pattern="^admin_unban_"))
    app.add_handler(CallbackQueryHandler(admin_banned_users, pattern="^admin_banned_users$"))
    app.add_handler(CallbackQueryHandler(admin_search_user, pattern="^admin_search_user$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_menu, pattern="^admin_broadcast_menu$"))
    app.add_handler(CallbackQueryHandler(admin_logs, pattern="^admin_logs$"))
    
    # Chat request handlers
    app.add_handler(CallbackQueryHandler(handle_request_action, pattern="^(accept_|decline_|clear_requests)"))

    # Menu button handlers
    app.add_handler(MessageHandler(filters.Regex("^🔥 Find Matches$"), find_match))
    app.add_handler(MessageHandler(filters.Regex("^👤 My Profile$"), show_my_profile))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Settings$"), set_preference))
    app.add_handler(MessageHandler(filters.Regex("^📢 Report User$"), report_user))

    # Message handlers (chat_relay delegates to edit, search, and report when active)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_relay))
    app.add_handler(MessageHandler(filters.PHOTO, photo_relay))
    
    # Broadcast conversation wizard handler
    broadcast_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(broadcast_start, pattern="^broadcast_")],
        states={
            BROADCAST_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_receive_text)],
            BROADCAST_MEDIA: [
                MessageHandler(filters.PHOTO, broadcast_receive_media),
                MessageHandler(filters.VIDEO, broadcast_receive_media),
                MessageHandler(filters.Document.ALL, broadcast_receive_media),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
        name="broadcast_conversation"
    )
    app.add_handler(broadcast_conv_handler)
    
    print("✅ All handlers registered!")
    print(f"👑 Admin User ID: {ADMIN_USER_ID if ADMIN_USER_ID else 'Not set'}")
    print(f"📢 Channel: {CHANNEL_USERNAME if CHANNEL_USERNAME else 'None'}")
    
    # Decide between Webhook and Polling mode
    is_webhook_mode = bool(RENDER_URL) and USE_WEBHOOK != "false"
    
    if is_webhook_mode:
        # ---------------- WEBHOOK MODE (Cloud / Render) ----------------
        render_clean_url = RENDER_URL.rstrip('/')
        webhook_path = "/webhook"
        webhook_url = f"{render_clean_url}{webhook_path}"
        
        print(f"🌐 Running in WEBHOOK mode with URL: {webhook_url}")
        
        await app.initialize()
        await app.start()
        
        # Configure webhook
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            max_connections=40
        )
        
        # Web server
        web_app = web.Application()
        
        async def handle_health(request):
            return web.Response(text="Bot is healthy")
        
        async def handle_webhook(request):
            try:
                body = await request.read()
                data = json.loads(body.decode('utf-8'))
                if 'update_id' in data:
                    update = Update.de_json(data, app.bot)
                    await app.process_update(update)
                return web.Response(status=200, text="OK")
            except Exception as e:
                logger.error(f"Webhook error: {e}")
                return web.Response(status=500, text=str(e))
        
        async def handle_test(request):
            try:
                bot_info = await app.bot.get_me()
                return web.json_response({
                    "status": "running",
                    "mode": "webhook",
                    "time": str(datetime.now()),
                    "bot_name": bot_info.first_name,
                    "bot_username": bot_info.username,
                    "webhook_url": webhook_url
                })
            except Exception as e:
                return web.json_response({"status": "error", "error": str(e)}, status=500)
        
        web_app.router.add_post(webhook_path, handle_webhook)
        web_app.router.add_get('/', lambda r: web.Response(text="🤖 AU Dating Bot is running."))
        web_app.router.add_get('/health', handle_health)
        web_app.router.add_get('/test', handle_test)
        
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        
        bot_info = await app.bot.get_me()
        print("=" * 50)
        print("🎉 AU DATING BOT IS RUNNING WITH WEBHOOK!")
        print(f"🤖 Bot: @{bot_info.username} ({bot_info.first_name})")
        print(f"📱 Webhook URL: {webhook_url}")
        print("=" * 50)
        
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            print("\n👋 Shutting down webhook bot...")
        finally:
            print("🔄 Cleaning up resources...")
            await app.bot.delete_webhook()
            await app.stop()
            await app.shutdown()
            await runner.cleanup()
            await close_db()
            print("✅ Webhook shutdown complete!")
    
    else:
        # ---------------- POLLING MODE (Local Development) ----------------
        print("🚀 Running in POLLING mode (no RENDER_URL detected)...")
        await app.initialize()
        await app.bot.delete_webhook(drop_pending_updates=True)
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        
        bot_info = await app.bot.get_me()
        print("=" * 50)
        print("🎉 AU DATING BOT IS RUNNING IN POLLING MODE!")
        print(f"🤖 Bot: @{bot_info.username} ({bot_info.first_name})")
        print("💬 Send /start to your bot in Telegram to test.")
        print("🛑 Press Ctrl+C in this terminal to stop.")
        print("=" * 50)
        
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            print("\n👋 Shutting down polling bot...")
        finally:
            print("🔄 Cleaning up resources...")
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            await close_db()
            print("✅ Polling shutdown complete!")

# Start the bot
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 Bot stopped.")
    except Exception as e:
        print(f"❌ Fatal error starting bot: {e}")
        import traceback
        traceback.print_exc()



















