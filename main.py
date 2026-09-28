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

# 環境変数の読み込みと前後の余白削除
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
    print('🤖 Bot起動完了')

async def start_game_timer(channel):
    global game_state
    await asyncio.sleep(300) 
    if game_state["is_running"] and game_state["mode"] == "time":
        await channel.send('🚨 【5分経過・議論強制終了】 🚨')
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
            await message.reply('🔄 リセット成功しました！')
            return

        current_time = time.time()
        if current_time - last_api_call_time < API_COOLDOWN_MS:
            await message.reply('⚠️ 3秒待ってください！')
            return
        last_api_call_time = current_time

        try:
            async with message.channel.typing():
                # キーの読み込みチェック
                gemini_key_exists = len(GEMINI_API_KEY) > 0
                openai_key_exists = len(OPENAI_API_KEY) > 0

                # APIキーがどちらもセットされていない場合の即時警告
                if not gemini_key_exists and not openai_key_exists:
                    await message.reply('❌ 【エラー】GEMINI_API_KEY も OPENAI_API_KEY も環境変数に設定されていません！サーバーのEnvironment Variablesを確認してください。')
                    return

                prompt_content = f"あなたは対話型人狼ゲームのGMです。日本語で4人のAI（レン、ユイ、Gemini-A、Gemini-B）の会話を生成してください。\n発言: {user_prompt}"

                ai_reply = ""
                debug_log = []

                # 1. Gemini試行
                if gemini_key_exists:
                    try:
                        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
                        gemini_payload = {"contents": [{"parts": [{"text": prompt_content}]}]}
                        
                        gemini_req = urllib.request.Request(
                            gemini_url,
                            data=json.dumps(gemini_payload).encode('utf-8'),
                            headers=HTTP_HEADERS,
                            method="POST"
                        )
                        with urllib.request.urlopen(gemini_req, timeout=8.0) as gemini_res:
                            gemini_data = json.loads(gemini_res.read().decode('utf-8'))
                            if "candidates" in gemini_data:
                                text_res = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
                                if "Hello" not in text_res:
                                    ai_reply = text_res
                                else:
                                    debug_log.append("GeminiがHelloを返却")
                    except urllib.error.HTTPError as e:
                        debug_log.append(f"Gemini HTTPエラー({e.code})")
                    except Exception as e:
                        debug_log.append(f"Geminiエラー({e})")

                # 2. OpenAI試行（Gemini失敗時）
                if not ai_reply and openai_key_exists:
                    try:
                        openai_url = "https://api.openai.com/v1/chat/completions"
                        openai_payload = {
                            "model": "gpt-4o-mini",
                            "messages": [{"role": "user", "content": prompt_content}]
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
                            if "choices" in openai_data:
                                ai_reply = openai_data["choices"][0]["message"]["content"]
                    except urllib.error.HTTPError as e:
                        debug_log.append(f"OpenAI HTTPエラー({e.code})")
                    except Exception as e:
                        debug_log.append(f"OpenAIエラー({e})")

                # どちらもダメだった場合の報告
                if not ai_reply:
                    log_str = " / ".join(debug_log)
                    await message.reply(f'⚠️ 両方のAPI接続に失敗しました。\n詳細: {log_str}\n※サーバーの環境変数（Environment Variables）に正しいAPIキーが設定されているか確認してください。')
                else:
                    await message.reply(ai_reply)

        except Exception as error:
            await message.reply(f'⚠️ [System Error] {error}')

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
client.run(DISCORD_TOKEN)
