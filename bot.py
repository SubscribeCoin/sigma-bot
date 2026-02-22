import os
import sqlite3
from datetime import date

import discord
from discord import app_commands
from dotenv import load_dotenv

from flask import Flask
from threading import Thread

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# --- Render 포트 바인딩(필수) ---
app = Flask(__name__)

@app.get("/")
def home():
    return "OK"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web, daemon=True).start()
# --- /Render 포트 바인딩 ---

DB_PATH = "sigma.db"
DAILY_REWARD = 100_000  # 출석 보상

WELCOME_CHANNEL_ID = 0  # ⭐ 환영 메시지 보낼 채널 ID (0이면 서버 시스템 채널 사용)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                total_checkins INTEGER NOT NULL DEFAULT 0,
                last_checkin TEXT,
                joined_at TEXT
            )
            """
        )

def migrate_db():
    """기존 sigma.db에 joined_at 컬럼이 없을 수 있어서 안전하게 추가"""
    with db() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "joined_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN joined_at TEXT")

def ensure_user(conn: sqlite3.Connection, user_id: int):
    conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))

def get_user(conn: sqlite3.Connection, user_id: int):
    ensure_user(conn, user_id)
    return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def format_won(n: int) -> str:
    return f"{n:,}₩"

class SigmaClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True  # ✅ 멤버 입장 이벤트에 필요 (필수)
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        init_db()
        migrate_db()  # ✅ 기존 DB에도 joined_at 추가
        await self.tree.sync()

client = SigmaClient()

@client.event
async def on_ready():
    print(f"✅ SIGMA 로그인 완료: {client.user}")

# ✅ 멤버 입장 시 자동 프로필/입장일 표시
@client.event
async def on_member_join(member: discord.Member):
    if member.bot:
        return

    joined_str = member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "알 수 없음"

    with db() as conn:
        user = get_user(conn, member.id)

        # joined_at 저장 (이미 있으면 유지)
        if not user["joined_at"]:
            conn.execute(
                "UPDATE users SET joined_at=? WHERE user_id=?",
                (joined_str, member.id)
            )
            user = get_user(conn, member.id)

    # 환영 메시지 보낼 채널 결정
    channel = None
    if WELCOME_CHANNEL_ID:
        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)

    if channel is None:
        channel = member.guild.system_channel

    if channel is None:
        return  # 보낼 채널이 없으면 종료

    embed = discord.Embed(
        title="👋 새 멤버 입장!",
        description=f"{member.mention} 님 환영합니다!\nSIGMA 프로필이 자동 생성되었습니다.",
    )
    embed.set_author(name=str(member), icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="🆔 USER ID", value=str(member.id), inline=False)
    embed.add_field(name="📅 서버 입장일", value=user["joined_at"] or joined_str, inline=True)
    embed.add_field(name="💰 현재 잔고", value=format_won(user["balance"]), inline=True)
    embed.add_field(name="✅ 총 출석", value=f"{user['total_checkins']}회", inline=True)

    await channel.send(embed=embed)

# -------------------------
# /출석
# -------------------------
@client.tree.command(name="출석", description="하루 1회 출석 보상을 받습니다.")
async def checkin(interaction: discord.Interaction):
    today = date.today().isoformat()

    with db() as conn:
        user = get_user(conn, interaction.user.id)

        if user["last_checkin"] == today:
            embed = discord.Embed(
                title="✅ 이미 출석했어요",
                description="오늘은 이미 출석 보상을 받았습니다.",
            )
            embed.add_field(name="현재 잔고", value=format_won(user["balance"]), inline=True)
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        new_balance = user["balance"] + DAILY_REWARD
        new_total = user["total_checkins"] + 1

        conn.execute(
            "UPDATE users SET balance=?, total_checkins=?, last_checkin=? WHERE user_id=?",
            (new_balance, new_total, today, interaction.user.id),
        )

    embed = discord.Embed(
        title="✅ 출석 완료!",
        description=f"**{format_won(DAILY_REWARD)}** 지급되었습니다.",
    )
    embed.add_field(name="현재 잔고", value=format_won(new_balance), inline=True)
    embed.add_field(name="총 출석", value=f"{new_total}회", inline=True)
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

# -------------------------
# /프로필
# -------------------------
@client.tree.command(name="프로필", description="내 SIGMA 프로필을 확인합니다.")
async def profile(interaction: discord.Interaction):
    with db() as conn:
        user = get_user(conn, interaction.user.id)

    embed = discord.Embed(
        title="SIGMA PROFILE",
        description="시그마 봇과 함께하는 Play Game.",
    )

    embed.add_field(name="💰 현재 잔고", value=f"**{format_won(user['balance'])}**", inline=False)
    embed.add_field(name="📅 총 출석", value=f"{user['total_checkins']}회", inline=True)
    embed.add_field(name="🕒 마지막 출석", value=user["last_checkin"] or "없음", inline=True)
    embed.add_field(name="📥 서버 입장일", value=user["joined_at"] or "기록 없음", inline=True)

    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)

    await interaction.response.send_message(embed=embed)

# 테스트용 유지 (원하면 지워도 됨)
@client.tree.command(name="ping", description="SIGMA 응답 테스트")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong 🗿")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN이 .env에 없습니다.")


client.run(TOKEN)
