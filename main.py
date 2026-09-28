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
                input_text = user_prompt if user_prompt else 'ゲーム開始！全員自己紹介して議論を始めてください！'
                current_mode_text = f"【現在の議論ターン数: {game_state['turn_count']} / 5 ターン】" if game_state["mode"] == "turn" else "【人間同士の5分間時間制限バトル中】"
                
                history_text = ""
                for h in conversation_history[-4:]:
                    history_text += f"{h['speaker']}: {h['text']}\n"

                # プロンプトの構造を「純粋なユーザー命令」として1つに統合
                prompt_content = f"""[絶対命令]
あなたは「対話型ワンナイト人狼ゲーム」のゲームマスターです。英語の挨拶（Hello等）は絶対に禁止します。日本語のみで回答してください。

以下の4人のプレイヤー（レン、ユイ、Gemini-A、Gemini-B）になりきり、{message.author.name}の発言を受けて、4人が順番に人狼ゲームの議論をしている会話文を作成してください。

{current_mode_text}

【プレイヤー設定】
1. レン（20代男子）：冷静、論理的
2. ユイ（17歳女子高生）：直感重視、天然
3. Gemini-A：確率重視、淡々と話す
4. Gemini-B：人間観察、疑い深い

【直近の会話】
{history_text}

【今回のプレイヤー発言】
{message.author.name}: {input_text}

【出力形式】
レン: 「...」
ユイ: 「...」
Gemini-A: 「...」
Gemini-B: 「...」"""

                ai_reply = ""

                # 1. Gemini API呼び出し (最新エンドポイント)
                if GEMINI_API_KEY and not ai_reply:
                    try:
                        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
                        gemini_payload = {
                            "contents": [{
                                "parts": [{"text": prompt_content}]
                            }]
                        }
                        gemini_req = urllib.request.Request(
                            gemini_url,
                            data=json.dumps(gemini_payload).encode('utf-8'),
                            headers=HTTP_HEADERS,
                            method="POST"
                        )
                        with urllib.request.urlopen(gemini_req, timeout=10.0) as gemini_res:
                            gemini_data = json.loads(gemini_res.read().decode('utf-8'))
                            if "candidates" in gemini_data and len(gemini_data["candidates"]) > 0:
                                text_out = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
                                if "Hello" not in text_out and len(text_out) > 20:
                                    ai_reply = text_out
                    except Exception as e:
                        print(f"Gemini Error: {e}")

                # 2. OpenAI API呼び出し (フォールバック)
                if OPENAI_API_KEY and not ai_reply:
                    try:
                        openai_url = "https://api.openai.com/v1/chat/completions"
                        openai_payload = {
                            "model": "gpt-4o-mini",
                            "messages": [
                                {"role": "user", "content": prompt_content}
                            ],
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
                        with urllib.request.urlopen(openai_req, timeout=10.0) as openai_res:
                            openai_data = json.loads(openai_res.read().decode('utf-8'))
                            if "choices" in openai_data and len(openai_data["choices"]) > 0:
                                ai_reply = openai_data["choices"][0]["message"]["content"]
                    except Exception as e:
                        print(f"OpenAI Error: {e}")

                if not ai_reply:
                    ai_reply = "⚠️ AIからの応答が得られませんでした。APIキーまたは残高を確認してください。"

                # 履歴保存
                conversation_history.append({"speaker": message.author.name, "text": input_text})
                conversation_history.append({"speaker": "AI_GM", "text": ai_reply})

                if game_state["is_running"] and game_state["mode"] == "turn" and game_state["turn_count"] == 5:
                    ai_reply += "\n\n🚨 🚨 🚨 【5ターン到達・議論強制終了】 🚨 🚨 🚨"
                    game_state["is_running"] = False

                await message.reply(ai_reply)

        except Exception as error:
            await message.reply(f'⚠️ [System Error] エラーが発生しました: {error}')

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
client.run(DISCORD_TOKEN)
