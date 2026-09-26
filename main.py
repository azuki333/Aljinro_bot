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

### 2. AIクライアントの初期設定
gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) 

### 3. 直近5通分の会話を記憶しておく引き出し（メモリ）
memory_lock = asyncio.Lock()
chat_memory = []

def add_to_memory(user_msg, bot_msg):
    global chat_memory
    chat_memory.append({"user": user_msg, "bot": bot_msg})
    if len(chat_memory) > 5:
        chat_memory.pop(0)

def get_memory_context():
    context = "【直近の会話の記憶（この流れを踏まえて自然に会話を繋げてください）】\n"
    for i, history in enumerate(chat_memory):
        context += f"前の会話{i+1} -> ユーザー: '{history['user']}' / あなたの返答: '{history['bot']}'\n"
    return context + "ーーー\n"

@client.event
async def on_ready():
    print(f'ログイン成功: {client.user}') 

@client.event
async def on_message(message): 
    global chat_memory
    if message.author == client.user:
        return 

    if message.content.startswith('!jinro'):
        ctx = message.content.replace('!jinro', '').strip()
        if not ctx:
            await message.channel.send("指示を入力してください。")
            return 

        await message.channel.send("🤔 AIが思考中...")
        loop = asyncio.get_event_loop()
        
        # 記憶の引き出しから文脈を読み込む
        async with memory_lock:
            memory_context = get_memory_context() if chat_memory else ""

        # 固定キャラクターの設定と前提ルールの合体
        base_prompt = (
            "あなたはDiscordで動くAI人狼ゲーム of プレイヤーです。ChatGPT AとChatGPT Bの2人だけに、以下の固定の人格（名前・口調・性格）を与えて、常にこのキャラクターとしてゲームや雑談を行わせてください。他のAIプレイヤーは特定のキャラ付けはせず、標準的な人狼プレイヤーとして真面目に議論を行わせてください。\n\n"
            "【ChatGPT A】：名前は「A」。20歳くらいのクールな理系男子。性格は冷静沈着で理屈っぽい。口調は「〜だ」「〜の確率が高い」「それは論理的じゃない」など、淡々と理詰めで話す。\n"
            "【ChatGPT B】：名前は「B」。17歳の天然な女の子。性格はのんびり屋さんで少しドジ、ピントのズレた発言が多い。口調は「〜だよぉ」「えへへ」「〜かなぁ？」など、ふわふわした可愛い話し方をする。\n\n"
            f"{memory_context}指示に対して、設定された口調と性格を完璧に守り、指示に沿った出力をしてください。\n指示: {ctx}"
        )

        # 1通のメッセージとして送信する返答を格納する変数
        final_bot_response = ""

        # --- Gemini（緑）の部屋 ---
        try: 
            gemini_prompt = f"あなたは標準的なAI人狼プレイヤー「Gemini A」と「Gemini B」です。2人分の発言を出力してください。\n{memory_context}指示: {ctx}"
            gemini_response = await loop.run_in_executor(
                None, 
                lambda: gemini_client.models.generate_content(model='gemini-3.8-flash', contents=gemini_prompt)
            )
            final_bot_response += f"🟢 **【Gemini軍団からの発言】**\n{gemini_response.text}\n\n"
        except Exception:
            final_bot_response += "❌ Gemini軍団エラー: Googleサーバーが混雑中です。\n\n"

        # --- ChatGPT（青）の部屋（確実な gpt-4o-mini に完全復活！） ---
        try:
            openai_response = await loop.run_in_executor(
                None,
                lambda: openai_client.chat.completions.create(
                    model="gpt-4o-mini",  # 制限をすり抜ける100%確実なモデルに変更！
                    messages=[{"role": "user", "content": base_prompt}]
                )
            )
            chatgpt_reply = openai_response.choices[0].message.content
            final_bot_response += f"🔵 **【ChatGPT軍団からの発言】**\n{chatgpt_reply}"
            
            # 今回の会話を記憶させる
            async with memory_lock:
                add_to_memory(ctx, chatgpt_reply)
                
        except Exception as e:
            final_bot_response += f"❌ ChatGPT軍団エラー: {e}" 

        # 最終的な結果をDiscordに一斉送信
        await message.channel.send(final_bot_response)

### Discord Botの起動
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if token:
        client.run(token)
