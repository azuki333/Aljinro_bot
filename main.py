import discord
from discord.ext import commands
import os
import game_logic

# Discordのインテント（権限）設定
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user} (ID: {bot.user.id})")
    print("ワンナイト人狼ボットが準備完了しました！")

@bot.event
async def on_message(message):
    # ボット自身のメッセージは無視
    if message.author.bot:
        return

    # 夜の行動コマンド（!fortune, !steal, !hunt, !witch 等）がDMやチャンネルで打たれた場合
    if message.content.startswith("!") and game_logic.game["phase"] == "night":
        await game_logic.handle_night_commands(message)
        return

    # 通常のコマンド処理を実行できるようにする
    await bot.process_commands(message)

# ==================== ゲーム起動・操作コマンド ====================

@bot.command(name="jinro")
async def jinro(ctx, action: str = None, mode: str = "solo"):
    """ワンナイト人狼を開始・操作するメインコマンド"""
    
    # 1. ゲーム開始
    if action == "start":
        if game_logic.game["is_running"]:
            await ctx.send("⚠️ すでにゲームが実行中です。リセットするには `!jinro reset` を打ってください。")
            return
        
        # 役職カスタム設定画面を表示
        view = game_logic.RoleCountSelectView(mode=mode, interaction_user=ctx.author)
        embed = view.create_embed()
        await ctx.send("🎴 **役職の枚数を設定してください**", embed=embed, view=view)

    # 2. 観戦モードなどの進行（次へ）
    elif action == "next":
        if not game_logic.game["is_running"]:
            await ctx.send("⚠️ 現在進行中のゲームはありません。")
            return
        
        if game_logic.game["mode"] == "watch" and game_logic.game["phase"] == "discussion":
            await game_logic.step_watch_discussion(ctx.channel)
        else:
            await ctx.send("⚠️ 現在のフェイズでは `!jinro next` は使用できません。")

    # 3. 強制リセット
    elif action == "reset":
        game_logic.reset_game_state()
        await ctx.send("🔄 ゲームの状態を強制リセットしました。")

    # 4. ヘルプ・使い方の表示
    else:
        embed = discord.Embed(
            title="🐺 ワンナイト人狼 へようこそ！",
            description="コマンドの使い方一覧です。",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="🎮 ゲーム開始",
            value="`!jinro start` (または `!jinro start solo`)\n役職カスタム画面が表示され、設定後にゲームが始まります。",
            inline=False
        )
        embed.add_field(
            name="👀 観戦モード開始",
            value="`!jinro start watch`\nAI同士の対戦を観戦できます (`!jinro next` で進行)",
            inline=False
        )
        embed.add_field(
            name="🌙 夜の能力コマンド (DM推奨)",
            value=(
                "- 占い師: `!fortune [プレイヤー名 / 墓場]`\n"
                "- 怪盗: `!steal [プレイヤー名]`\n"
                "- 狩人: `!hunt [プレイヤー名]`\n"
                "- 魔女っ子: `!witch [プレイヤー名]`"
            ),
            inline=False
        )
        embed.add_field(
            name="🔄 リセット",
            value="`!jinro reset`",
            inline=False
        )
        await ctx.send(embed=embed)

# ボットの起動（Discordトーン保持）
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ エラー: DISCORD_TOKEN の環境変数が設定されていません。")
