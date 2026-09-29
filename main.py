import discord
import urllib.request
import urllib.error
import json
import asyncio
import os
import random
import traceback

# --- 各種モジュールのインポート ---
from game_logic import (
    AI_CHARACTERS, ROLE_EMOJIS, game, send_split_message, 
    call_llm, start_5min_timer, RoleCountSelectView, 
    setup_game, process_night_phase, generate_ai_discussion, 
    handle_jinro_command, start_voting_phase, Tally_and_finish, reset_game_state
)

# --- Discord Client 設定 ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

# --- 環境変数の取得 ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

@client.event
async def on_ready():
    print(f'🤖 起動完了: {client.user.name}')

@client.event
async def on_message(message):
    global game
    if message.author.bot:
        return
    content = message.content.strip()

    try:
        if content == '!help':
            await message.reply("🤖 コマンド: `!jinro solo`, `!jinro multi`, `!jinro watch`, `!chat`, `!test`")
            return

        if content == '!test':
            async with message.channel.typing():
                res = await call_llm("テスト成功」と返答してください。", debug=True)
                await send_split_message(message.channel, res)
            return

        if content.startswith('!chat'):
            q = content[5:].strip()
            if q:
                async with message.channel.typing():
                    reply = await call_llm(f"ユーザーへ返答: {q}")
                    if reply:
                        await send_split_message(message.channel, reply)
            return

        # ==========================
        # DMでのプライベート行動処理
        # ==========================
        if isinstance(message.channel, discord.DMChannel):
            p_name = None
            for n, p in game["players"].items():
                if p.get("user_obj") and p["user_obj"].id == message.author.id:
                    p_name = n
                    break

            if not p_name or not game["is_running"]:
                await message.reply("現在参加しているゲームはありません。")
                return

            if content.startswith('!fortune') and game["phase"] == "night":
                t = content[8:].strip()
                if t == "墓場":
                    await message.reply(f"🔮 墓場: 『{game['center_cards'][0]}』, 『{game['center_cards'][1]}』")
                elif t in game["players"] and t != p_name:
                    await message.reply(f"🔮 {t} の役職は『{game['players'][t]['role']}』です。")
                return

            if content.startswith('!steal') and game["phase"] == "night":
                t = content[6:].strip()
                if t in game["players"] and t != p_name:
                    my_old = game["players"][p_name]["role"]
                    target_role = game["players"][t]["role"]
                    game["players"][p_name]["role"] = target_role
                    game["players"][t]["role"] = my_old
                    await message.reply(f"🎭 {t} から役職を盗みました！ 新役職: 『{game['players'][p_name]['role']}』")
                return

            if content.startswith('!hunt') and game["phase"] == "night":
                t = content[6:].strip()
                if t in game["players"] and t != p_name:
                    game["hunter_targets"][p_name] = t
                    await message.reply(f"🎯 狩人能力: {t} を指定しました。")
                return

            if content.startswith('!witch') and game["phase"] == "night":
                t = content[7:].strip()
                if t in game["players"]:
                    await message.reply(f"🧙 魔女っ子能力: {t} の役職は『{game['players'][t]['role']}』です。")
                return

            if content.startswith('!vote') and game["phase"] == "voting":
                t = content[5:].strip()
                if t in game["players"] or t == "墓場":
                    game["votes"][p_name] = t
                    await message.reply(f"✅ **{t}** に投票しました！")
                    if len(game["votes"]) == len(game["players"]):
                        await Tally_and_finish()
                return
            return

        # ==========================
        # サーバーチャンネルでのコマンド処理
        # ==========================
        if content.startswith('!jinro'):
            parts = content[6:].strip().split(maxsplit=1)
            sub = parts[0].lower() if len(parts) > 0 else ""

            if sub in ['clear', 'リセット']:
                reset_game_state()
                await message.reply('🔄 リセットしました！')
                return

            if sub in ['watch', '観戦']:
                if game["is_running"]:
                    await message.reply("⚠️ ゲームが既に進行中です。")
                    return
                reset_game_state()
                asyncio.create_task(setup_game(message.channel, "watch"))
                return

            if sub in ['next', '次']:
                if game["is_running"] and game["mode"] == "watch":
                    await generate_ai_discussion(is_watch=True)
                else:
                    await message.reply("⚠️ 現在、観戦モードの進行中ではありません。")
                return

            if sub == "solo":
                if game["is_running"]:
                    await message.reply("⚠️ ゲームが既に進行中です。")
                    return
                reset_game_state()
                view = RoleCountSelectView("solo", [message.author])
                await message.channel.send(embed=view.create_embed(), view=view)
                return

            # マルチモード募集開始
            if sub == "multi":
                if game["is_running"]:
                    await message.reply("⚠️ ゲームが既に進行中です。")
                    return
                reset_game_state()
                game["pending_multi_host"] = message.author
                game["pending_multi_users"] = [message.author]
                game["phase"] = "recruiting"
                game["channel"] = message.channel
                await message.reply("👥 **マルチモード参加者募集中！**\n参加したい人は `!join` と送信してください。\nホストは準備ができたら `!start` で役職選択へ進んでください。")
                return

            # 💡 議論中の発言処理（ここで handle_jinro_command を呼び出すように修正）
            if game["is_running"] and game["phase"] == "discussion" and game["mode"] != "watch":
                actual_text = content[6:].strip() or "（進行）"
                await handle_jinro_command(message, actual_text, message.author.display_name)
                return

        # マルチモードの参加受付 (`!join`)
        if content == "!join" and game.get("phase") == "recruiting":
            user = message.author
            if user not in game.get("pending_multi_users", []):
                game["pending_multi_users"].append(user)
                await message.channel.send(f"👤 **{user.display_name}** が参加しました！（現在 {len(game['pending_multi_users'])}人）")
            return

        # マルチモードのゲーム開始 (`!start`)
        if content == "!start" and game.get("phase") == "recruiting":
            if message.author == game.get("pending_multi_host"):
                users = game["pending_multi_users"]
                if len(users) > 5:
                    await message.channel.send("⚠️ 人間は最大5人まで参加可能です。")
                    return
                view = RoleCountSelectView("multi", users)
                await message.channel.send(embed=view.create_embed(), view=view)
            else:
                await message.reply("⚠️ 募集を開始したホストのみ `!start` を実行できます。")
            return

    except Exception as e:
        print(f"[Error]: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
