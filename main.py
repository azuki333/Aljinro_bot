import discord
import os
import asyncio
from google import genai
from google.genai import types
from openai import OpenAI 

### 1. 接続の初期設定（インテント設定）
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents) 

### 2. AIクライアントの初期設定（環境変数からキーを読み込む）
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) 

@client.event
async def on_ready():
    print(f'ログイン成功: {client.user}') 

@client.event
async def on_message(message): 
    ### 自分の発言には反応しない
    if message.author == client.user:
        return 

    ### コマンドの処理
    if message.content.startswith('!jinro'):
        ctx = message.content.replace('!jinro', '').strip()
        if not ctx:
            await message.channel.send("人狼ゲームの指示を入力してください。（例：!jinro ゲームを始めて）")
            return 

        await message.channel.send("🤔 AIが思考中...")
        loop = asyncio.get_event_loop()
        
        ### 【修正ポイント】GeminiとChatGPTのエラーを別々に処理する
        
        # --- Geminiの処理 ---
        try: 
            gemini_prompt = f"あなたはDiscordで動くAI人狼ゲームのプレイヤー「Gemini A」と「Gemini B」です。以下のGMの指示や状況に対して、2人分の発言を同時に出力してください。\n指示: {ctx}"
            gemini_response = await loop.run_in_executor(
                None, 
                lambda: gemini_client.models.generate_content(
                    model='gemini-3.8-flash',
                    contents=gemini_prompt,
                )
            )
            await message.channel.send(f"🟢 **【Gemini軍団からの発言】**\n{gemini_response.text}")
        except Exception as e:
            await message.channel.send(f"❌ Gemini軍団エラー: Googleサーバーが混雑しています。時間をおいて試してください。") 

        # --- ChatGPTの処理（Geminiがダメでもこちらは必ず動きます！） ---
        try:
            openai_prompt = f"あなたはDiscordで動くAI人狼ゲームのプレイヤー「ChatGPT A」と「ChatGPT B」です。以下のGMの指示や状況に対して、2人分の発言を同時に出力してください。\n指示: {ctx}"
            openai_response = await loop.run_in_executor(
                None,
                lambda: openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": openai_prompt}]
                )
            )
            await message.channel.send(f"🔵 **【ChatGPT軍団からの発言】**\n{openai_response.choices[0].message.content}")
        except Exception as e:
            await message.channel.send(f"❌ ChatGPT軍団エラー: {e}") 

### Discord Botの起動
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        client.run(token)
    else:
        print("エラー: DISCORD_TOKEN が設定されていません。")
