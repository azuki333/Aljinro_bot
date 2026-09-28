import discord
import urllib.request
import urllib.error
import json
import time
import asyncio
import os

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 環境変数からOpenAIのAPIキーを安全に読み込みます
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 最新10通分の会話履歴を記憶しておくための無敵の配列スタック
conversation_history = []

# 【ロック絶対回避】3秒以内の連打は自動で弾いて24時間ロックを絶対回避します
last_api_call_time = 0
API_COOLDOWN_MS = 3.0 

# ゲームのモードに応じた進行管理ステート
game_state = {
    "is_running": False,
    "mode": "turn",
    "turn_count": 0
}

game_timer_task = None

@client.event
async def on_ready():
    print('🤖 【エラー自動開票システム搭載】対話型ワンナイトBot、完全起動！')

# 5分間の議論制限タイマー
async def start_game_timer(channel):
    global game_state
    await asyncio.sleep(300) 
    if game_state["is_running"] and game_state["mode"] == "time":
        await channel.send('🚨 🚨 🚨 【5分経過・議論強制終了】 🚨 🚨 🚨\n\n主様、人間同士の極限の議論時間（300秒）が終了しました！これ以上のおしゃべりは禁止です！')
        game_state["is_running"] = False

@client.event
async def on_message(message):
    global conversation_history, last_api_call_time, game_state, game_timer_task
    
    if message.author.bot:
        return

    if message.content.startswith('!jinro'):
        user_prompt = message.content[6:].strip()
        
        if user_prompt == 'clear' or user_prompt == 'リセット':
            conversation_history = []
            game_state = {"is_running": False, "mode": "turn", "turn_count": 0}
            if game_timer_task:
                game_timer_task.cancel()
                game_timer_task = None
            await message.reply('🔄 秘密基地の記憶と進行中のゲームを完全にリセットしたよ！')
            return

        current_time = time.time()
        if current_time - last_api_call_time < API_COOLDOWN_MS:
            await message.reply('⚠️ 主様、落ち着いて！3秒だけおいてからもう一度送っておくれ！')
            return
        last_api_call_time = current_time

        if 'ゲーム開始' in user_prompt or 'スタート' in user_prompt or '対戦開始' in user_prompt:
            game_state["is_running"] = True
            conversation_history = []
            if '人間同士' in user_prompt or '友達' in user_prompt:
                game_state["mode"] = "time"
                game_state["turn_count"] = 0
                if game_timer_task: game_timer_task.cancel()
                game_timer_task = asyncio.create_task(start_game_timer(message.channel))
            else:
                game_state["mode"] = "turn"
                game_state["turn_count"] = 0

        if game_state["is_running"] and game_state["mode"] == "turn":
            game_state["turn_count"] += 1
            if game_state["turn_count"] > 5:
                await message.reply('🗳️ 【5ターン制限終了】議論数は終了したよ！投票を行ってください！')
                game_state["is_running"] = False
                return

        try:
            async with message.channel.typing():
                conversation_history.append({"role": "user", "content": f"{message.author.name}: {user_prompt if user_prompt else '（ゲーム開始の合図）'}"})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                current_mode_text = f"【現在の議論ターン数: {game_state['turn_count']} / 5 ターン】" if game_state["mode"] == "turn" else "【人間同士の5分間時間制限バトル中】"
                
                system_content = f"""あなたは最高に面白い「対話型ワンナイト人狼ゲーム」を主様と一緒にリアルタイムに進行する AIGM です。
                人間のプレイヤー（{message.author.name}）の発言や最新10通の文脈を完璧に引き継ぎ、以下の4匹のAIプレイヤーの個性をむき出しにしてチャットログを生成してください。
                最大5ターン（または人間同士なら制限時間5分）で議論が綺麗に詰むように、会話をどんどん白熱させていくこと。
                
                【参戦する4大AIプレイヤーの設定】
                1. ChatGPT-A（20代クール男子）：冷静沈着、理路整然としたロジック。
                2. ChatGPT-B（17歳の女の子）：おっとり天然な女子高生。突拍子もない一言。
                3. ChatGPT-C（性格なし）：フラットにチャット発言。
                4. ChatGPT-D（性格なし）：フラットにチャット発言。"""

                # OpenAIの通信データを綺麗に整形します
                openai_payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "system", "content": system_content}] + conversation_history,
                    "temperature": 0.85
                }
                
                data_bytes = json.dumps(openai_payload).encode('utf-8')
                
                req = urllib.request.Request(
                    "https://openai.com",
                    data=data_bytes,
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    method="POST"
                )
                
                # 【完全エラー回避】標準機能で、JSONのパニックを起こさずに確実にデータを受け取ります！
                with urllib.request.urlopen(req, timeout=5.0) as res:
                    body = res.read().decode('utf-8')
                    openai_data = json.loads(body)
                    ai_reply = openai_data["choices"][0]["message"]["content"]

                conversation_history.append({"role": "assistant", "content": ai_reply})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                if game_state["is_running"] and game_state["mode"] == "turn" and game_state["turn_count"] == 5:
                    ai_reply += "\n\n🚨 🚨 🚨 【5ターン到達・議論強制終了】 🚨 🚨 🚨"
                    game_state["is_running"] = False

                await message.reply(ai_reply)

        except urllib.error.HTTPError as e:
            # 門番のアクセス拒否（403等）や、Keyの不具合（401等）の正体をそのまま自白させます！
            err_body = e.read().decode('utf-8', errors='ignore')
            await message.reply(f'⚠️ [HTTP Error {e.code}] OpenAI門番に拒否されました。中身: {err_body[:100]}')
        except Exception as error:
            await message.reply(f'⚠️ [System Error] OpenAI API Connection Failed. Reason: {error}')

# Botをログインさせます
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
client.run(DISCORD_TOKEN)
