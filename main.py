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

# 環境変数からAPIキーを読み込み（.strip()で前後の余計な空白を自動削除）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

conversation_history = []
last_api_call_time = 0
API_COOLDOWN_MS = 3.0 

game_state = {
    "is_running": False,
    "mode": "turn",
    "turn_count": 0
}

game_timer_task = None

HTTP_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

@client.event
async def on_ready():
    print('🤖 【完全体】ワンナイトBot、起動成功！')

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
        
        if user_prompt in ['clear', 'リセット']:
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
                await message.reply('🗳️ 【5ターン制限終了】議論数は終了したよ！今すぐ各自の投票を行ってください！')
                game_state["is_running"] = False
                return

        try:
            async with message.channel.typing():
                # 会話履歴の更新
                input_text = user_prompt if user_prompt else '（ゲーム開始の合図）'
                conversation_history.append({"role": "user", "content": f"{message.author.name}: {input_text}"})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                current_mode_text = f"【現在の議論ターン数: {game_state['turn_count']} / 5 ターン】" if game_state["mode"] == "turn" else "【人間同士の5分間時間制限バトル中】"
                
                system_content = f"""あなたは「対話型ワンナイト人狼ゲーム」を進行する AIGM です。日本語で応答してください。
人間のプレイヤー（{message.author.name}）の発言を受け、以下の4匹のAIプレイヤーになりきって会話（議論）を展開してください。

【参戦する4大AIプレイヤーの設定】
1. ChatGPT-A（20代クール男子：レン）：冷静沈着、理路整然としたロジック。
2. ChatGPT-B（17歳の女の子：ユイ）：おっとり天然な女子高生。
3. Gemini-A（Googleの刺客）：確率やロジック重視。
4. Gemini-B（Googleの刺客）：確率やロジック重視。

{current_mode_text}
それぞれのキャラクターの名前を付けて発言文を作成してください。"""

                ai_reply = ""
                gemini_failed = False

                # 1. Gemini API呼び出し
                if GEMINI_API_KEY:
                    try:
                        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
                        
                        prompt_text = f"{system_content}\n\n【最新メッセージ】\n{message.author.name}: {input_text}"
                        gemini_payload = {
                            "contents": [{"parts": [{"text": prompt_text}]}]
                        }
                        gemini_req = urllib.request.Request(
                            gemini_url,
                            data=json.dumps(gemini_payload).encode('utf-8'),
                            headers=HTTP_HEADERS,
                            method="POST"
                        )
                        with urllib.request.urlopen(gemini_req, timeout=8.0) as gemini_res:
                            gemini_data = json.loads(gemini_res.read().decode('utf-8'))
                            if "candidates" in gemini_data:
                                ai_reply = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
                            else:
                                gemini_failed = True
                    except Exception as e:
                        gemini_failed = True

                # 2. OpenAI API呼び出し（バックアップ）
                if not ai_reply and OPENAI_API_KEY:
                    openai_url = "https://api.openai.com/v1/chat/completions"
                    messages_payload = [{"role": "system", "content": system_content}] + conversation_history
                    openai_payload = {
                        "model": "gpt-4o-mini",
                        "messages": messages_payload,
                        "temperature": 0.7
                    }
                    openai_headers = HTTP_HEADERS.copy()
                    openai_headers["Authorization"] = f"Bearer {OPENAI_API_KEY}"

                    openai_req = urllib.request.Request(
                        openai_url,
                        data=json.dumps(openai_payload).encode('utf-8'),
                        headers=openai_headers,
                        method="POST"
                    )
                    with urllib.request.urlopen(openai_req, timeout=8.0) as openai_res:
                        openai_data = json.loads(openai_res.read().decode('utf-8'))
                        ai_reply = openai_data["choices"][0]["message"]["content"]

                if not ai_reply:
                    ai_reply = "⚠️ AIからの応答が得られませんでした。APIキーを確認してください。"

                conversation_history.append({"role": "assistant", "content": ai_reply})
                if len(conversation_history) > 10:
                    conversation_history.pop(0)

                if game_state["is_running"] and game_state["mode"] == "turn" and game_state["turn_count"] == 5:
                    ai_reply += "\n\n🚨 🚨 🚨 【5ターン到達・議論強制終了】 🚨 🚨 🚨"
                    game_state["is_running"] = False

                await message.reply(ai_reply)

        except Exception as error:
            await message.reply(f'⚠️ [System Error] エラーが発生しました: {error}')

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
client.run(DISCORD_TOKEN)
