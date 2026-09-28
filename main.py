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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

conversation_history = []
last_api_call_time = 0
API_COOLDOWN_MS = 3.0 

game_state = {
    "is_running": False,
    "mode": "turn",
    "turn_count": 0
}

game_timer_task = None

@client.event
async def on_ready():
    print('🤖 【診断モード起動】Botが起動しました！')
    print(f"🔑 GEMINI_API_KEY設定有無: {bool(GEMINI_API_KEY)}")
    print(f"🔑 OPENAI_API_KEY設定有無: {bool(OPENAI_API_KEY)}")

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
            await message.reply('🔄 リセットしました！')
            return

        current_time = time.time()
        if current_time - last_api_call_time < API_COOLDOWN_MS:
            await message.reply('⚠️ 3秒待ってください！')
            return
        last_api_call_time = current_time

        try:
            async with message.channel.typing():
                system_content = "あなたはAI対戦ゲームのGMです。"
                ai_reply = ""
                gemini_failed = False

                # 1. Geminiの呼び出しテスト
                if GEMINI_API_KEY:
                    print("🔍 [1] Gemini APIへのリクエストを開始します...")
                    try:
                        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
                        gemini_payload = {
                            "contents": [{"parts": [{"text": "Hello"}]}]
                        }
                        gemini_req = urllib.request.Request(
                            gemini_url,
                            data=json.dumps(gemini_payload).encode('utf-8'),
                            headers={"Content-Type": "application/json"},
                            method="POST"
                        )
                        with urllib.request.urlopen(gemini_req, timeout=8.0) as gemini_res:
                            gemini_data = json.loads(gemini_res.read().decode('utf-8'))
                            ai_reply = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
                            print("✅ [1] Gemini APIからの応答成功！")
                    except urllib.error.HTTPError as e:
                        print(f"❌ [1] Gemini HTTP Error: {e.code}")
                        err_body = e.read().decode('utf-8', errors='ignore')
                        print(f"📄 [1] Gemini エラー詳細: {err_body[:200]}")
                        gemini_failed = True
                    except Exception as e:
                        print(f"❌ [1] Gemini その他のエラー: {e}")
                        gemini_failed = True

                # 2. OpenAIの呼び出しテスト（Gemini失敗時または未設定時）
                if not ai_reply:
                    print("🔍 [2] OpenAI APIへのリクエストを開始します...")
                    try:
                        openai_url = "https://api.openai.com/v1/chat/completions"
                        openai_payload = {
                            "model": "gpt-4o-mini",
                            "messages": [{"role": "user", "content": "Hello"}],
                        }
                        openai_req = urllib.request.Request(
                            openai_url,
                            data=json.dumps(openai_payload).encode('utf-8'),
                            headers={
                                "Authorization": f"Bearer {OPENAI_API_KEY}",
                                "Content-Type": "application/json"
                            },
                            method="POST"
                        )
                        with urllib.request.urlopen(openai_req, timeout=8.0) as openai_res:
                            openai_data = json.loads(openai_res.read().decode('utf-8'))
                            ai_reply = openai_data["choices"][0]["message"]["content"]
                            print("✅ [2] OpenAI APIからの応答成功！")
                    except urllib.error.HTTPError as e:
                        print(f"❌ [2] OpenAI HTTP Error: {e.code}")
                        err_body = e.read().decode('utf-8', errors='ignore')
                        print(f"📄 [2] OpenAI エラー詳細: {err_body[:200]}")
                        raise e # ここで発生した場合は下のexceptで捕捉してDiscordへ返信

                if ai_reply:
                    await message.reply(ai_reply)
                else:
                    await message.reply("⚠️ AIからの回答を取得できませんでした。")

        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            await message.reply(f'⚠️ [HTTP Error {e.code}] 門番に拒否されました。中身: {err_body[:80]}')
        except Exception as error:
            await message.reply(f'⚠️ [System Error] {error}')

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
client.run(DISCORD_TOKEN)
