from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands
import os
import asyncio

from game_logic import (
    game, reset_game_state, call_llm, RoleCountSelectView,
    setup_game, handle_jinro_command, start_voting_phase, Tally_and_finish
)

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # DMでの投票や夜行動の処理
    if isinstance(message.channel, discord.DMChannel):
        content = message.content.strip()
        if content.startswith("!vote"):
            if not game["is_running"] or game["phase"] != "voting":
                await message.channel.send("⚠️ 現在は投票フェーズではありません。")
                return
            target = content.replace("!vote", "").strip()
            voter_name = next((n for n, p in game["players"].items() if not p["is_ai"] and p["user_obj"] and p["user_obj"].id == message.author.id), None)
            if not voter_name:
                await message.channel.send("⚠️ あなたはこのゲームに参加していません。")
                return
            if target != "平和" and target not in game["players"]:
                await message.channel.send(f"⚠️ プレイヤー「{target}」は存在しません。")
                return
            game["votes"][voter_name] = target
            await message.channel.send(f"🗳️ **{target}** に投票を受け付けました。")
            
            # 全員の投票が揃ったら集計
            if len(game["votes"]) == len(game["players"]):
                if game.get("channel"):
                    await game["channel"].send("✅ 全員の投票が完了しました！結果を集計します...")
                await Tally_and_finish()
            return

        # 夜の行動（占い師、怪盗、狩人、魔女っ子）
        if game["is_running"] and game["phase"] == "night":
            player_entry = next(((n, p) for n, p in game["players"].items() if not p["is_ai"] and p["user_obj"] and p["user_obj"].id == message.author.id), (None, None))
            n, p = player_entry
            if not n:
                await message.channel.send("⚠️ あなたはこのゲームに参加していません。")
                return
            
            content_lower = content.lower()
            if content_lower.startswith("!fortune "):
                if p["role"] != "占い師":
                    await message.channel.send("⚠️️ あなたは占い師ではありません。")
                    return
                target = content.replace("!fortune", "").strip()
                if target == "墓場":
                    if len(game["center_cards"]) >= 2:
                        await message.channel.send(f"🔮 墓場のカード: {game['center_cards'][0]} と {game['center_cards'][1]}")
                    else:
                        await message.channel.send("🔮 墓場のカード情報がありません。")
                elif target in game["players"]:
                    if target == n:
                        await message.channel.send("⚠️ 自分自身は占えません。")
                        return
                    await message.channel.send(f"🔮 {target} の役職は 『{game['players'][target]['role']}』 です。")
                else:
                    await message.channel.send(f"⚠️ プレイヤー「{target}」が見つかりません。")
                return

            elif content_lower.startswith("!steal "):
                if p["role"] != "怪盗":
                    await message.channel.send("⚠️ あなたは怪盗ではありません。")
                    return
                target = content.replace("!steal", "").strip()
                if target in game["players"]:
                    if target == n:
                        await message.channel.send("⚠️ 自分から盗むことはできません。")
                        return
                    old_role = p["role"]
                    target_role = game["players"][target]["role"]
                    game["players"][n]["role"] = target_role
                    game["players"][target]["role"] = old_role
                    await message.channel.send(f"🕵 {target} から役職を盗みました！ あなたの新しい役職は **{target_role}** です。")
                else:
                    await message.channel.send(f"⚠️ プレイヤー「{target}」が見つかりません。")
                return

            elif content_lower.startswith("!hunt "):
                if p["role"] != "狩人":
                    await message.channel.send("⚠️ あなたは狩人ではありません。")
                    return
                target = content.replace("!hunt", "").strip()
                if target in game["players"]:
                    game["hunter_targets"][n] = target
                    await message.channel.send(f"🎯 {target} を道連れ対象に指定しました。")
                else:
                    await message.channel.send(f"⚠️ プレイヤー「{target}」が見つかりません。")
                return

            elif content_lower.startswith("!witch "):
                if p["role"] != "魔女っ子":
                    await message.channel.send("⚠️ あなたは魔女っ子ではありません。")
                    return
                target = content.replace("!witch", "").strip()
                if target in game["players"]:
                    if target == n:
                        await message.channel.send("⚠️ 自分自身は覗き見れません。")
                        return
                    await message.channel.send(f"🧙‍♀️ {target} の役職は 『{game['players'][target]['role']}』 です。")
                else:
                    await message.channel.send(f"⚠️ プレイヤー「{target}」が見つかりません。")
                return

    # サーバー内チャンネルでの発言処理
    if game["is_running"] and game["channel"] and message.channel.id == game["channel"].id:
        actual_text = message.content.strip()
        if actual_text.startswith("!jinro"):
            actual_text = actual_text.replace("!jinro", "").strip()
        if actual_text:
            await handle_jinro_command(message, actual_text, message.author.display_name)
            
    await bot.process_commands(message)

@bot.command()
async def jinro(ctx, mode: str = None, *args):
    global game
    if mode == "stop":
        if not game["is_running"]:
            await ctx.send("⚠️ 現在進行中のゲームはありません。")
            return
        reset_game_state()
        await ctx.send("🛑 ゲームを強制終了しました。")
        return

    if mode == "test":
        prompt = " ".join(args) if args else "こんにちは！動作テストです。"
        async with ctx.typing():
            res = await call_llm(prompt, debug=True)
            await ctx.send(res or "❌ 応答なし")
        return

    if game["is_running"]:
        await ctx.send("⚠️ すでにゲームが進行中です。")
        return

    if mode == "solo":
        view = RoleCountSelectView("solo", [ctx.author])
        await ctx.send(embed=view.create_embed(), view=view)
    elif mode == "watch":
        view = RoleCountSelectView("watch", [])
        await ctx.send(embed=view.create_embed(), view=view)
    elif mode == "multi":
        mentions = ctx.message.mentions
        if not mentions:
            await ctx.send("⚠️ 参加者をメンションしてください（例: `!jinro multi @user1 @user2`）。")
            return
        human_users = [ctx.author] + [m for m in mentions if m != ctx.author]
        if len(human_users) > 5:
            await ctx.send("⚠️ 人間プレイヤーは最大5人までです。")
            return
        view = RoleCountSelectView("multi", human_users)
        await ctx.send(embed=view.create_embed(), view=view)
    else:
        await ctx.send(
            "🐺 **ワンナイト人狼へようこそ！**\n"
            "以下のコマンドで遊べます：\n"
            "・`!jinro solo` : 1人プレイ（あなた＋AI4人）\n"
            "・`!jinro multi @メンション...` : マルチプレイ（人間最大5人、不足分はAI）\n"
            "・`!jinro watch` : 観戦モード（AI5人による自動対戦）\n"
            "・`!jinro stop` : ゲーム強制終了\n"
            "・`!jinro test [文章]` : LLM接続テスト"
        )

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
if TOKEN:
    bot.run(TOKEN)
else:
    print("⚠️ DISCORD_BOT_TOKEN が設定されていません。環境変数またはコードにトークンを設定してください。")
