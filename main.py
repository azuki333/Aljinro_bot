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
    start_voting_phase, Tally_and_finish
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
                res = await call_llm("「テスト成功」と返答してください。", debug=True)
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

        if isinstance(message.channel, discord.DMChannel):
            p_name = message.author.display_name
            if content.startswith('!fortune') and game["is_running"]:
                t = content[8:].strip()
                if t == "墓場":
                    await message.reply(f"🔮 墓場: 『{game['center_cards'][0]}』, 『{game['center_cards'][1]}』")
                elif t in game["players"]:
                    await message.reply(f"🔮 {t} の役職は『{game['players'][t]['role']}』です。")
                return

            if content.startswith('!steal') and game["is_running"]:
                t = content[6:].strip()
                if t in game["players"] and t != p_name:
                    game["players"][p_name]["role"], game["players"][t]["role"] = game["players"][t]["role"], game["players"][p_name]["role"]
                    await message.reply(f"🎭 {t} と交換しました。新役職: 『{game['players'][p_name]['role']}』")
                return

            if content.startswith('!hunt') and game["is_running"]:
                t = content[6:].strip()
                if t in game["players"] and t != p_name:
                    game["hunter_targets"][p_name] = t
                    await message.reply(f"🎯 狩人能力: {t} を指定しました。")
                return

            if content.startswith('!witch') and game["is_running"]:
                t = content[7:].strip()
                if t in game["players"]:
                    await message.reply(f"🧙 魔女っ子能力: {t} の役職は『{game['players'][t]['role']}』です。")
                return

            if content.startswith('!vote') and game["phase"] == "voting":
                t = content[5:].strip()
                if t in game["players"]:
                    game["votes"][p_name] = t
                    await message.reply(f"✅ {t} に投票しました！")
                    if all(h in game["votes"] for h, pl in game["players"].items() if not pl["is_ai"]):
                        await Tally_and_finish()
                return

        if content.startswith('!jinro'):
            parts = content[6:].strip().split(maxsplit=1)
            sub = parts[0].lower() if len(parts) > 0 else ""

            if sub in ['clear', 'リセット']:
                if game["discussion_task"]:
                    game["discussion_task"].cancel()
                game = {
                    "is_running": False, "mode": None, "phase": "idle", "channel": None, "players": {}, "center_cards": [], "votes": {}, "hunter_targets": {}, "witch_targets": {}, "turn_count": 0, "discussion_task": None, "history": [],
                    "selected_roles": {"人狼": 2, "市民": 3, "占い師": 1, "怪盗": 1, "狩人": 0, "てるてる": 0, "魔女っ子": 0, "狂人": 0}
                }
                await message.reply('🔄 リセットしました！')
                return

            if sub in ['watch', '観戦']:
                if game["is_running"]:
                    await message.reply("⚠️ ゲームが既に進行中です。")
                    return
                await setup_game(message.channel, "watch")
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
                view = RoleCountSelectView("solo", [message.author])
                await message.channel.send(embed=view.create_embed(), view=view)
                return

            if sub in ["start", "multi"]:
                if game["is_running"]:
                    await message.reply("⚠️ ゲームが既に進行中です。")
                    return
                humans = [message.author] + message.mentions
                mode = "solo" if len(humans) == 1 else "multi"
                view = RoleCountSelectView(mode, humans)
                await message.channel.send(embed=view.create_embed(), view=view)
                return

            if game["is_running"] and game["phase"] == "discussion" and game["mode"] != "watch":
                actual_text = content[6:].strip() or "（進行）"
                await generate_ai_discussion(user_input=f"{message.author.display_name}: {actual_text}")

    except Exception as e:
        print(f"[Error]: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
