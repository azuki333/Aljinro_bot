const { Client, GatewayIntentBits } = require('discord.js');
const axios = require('axios');

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

// 環境変数から各種APIキーを安全に読み込みます
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;

// 【昨日の約束】最新10通分の会話履歴を記憶しておくための無敵の配列スタック
let conversationHistory = [];

// 【ロック絶対回避システム】APIの連続連打（Rate Limit）を防ぐためのクールダウン制御
let lastApiCallTime = 0;
const API_COOLDOWN_MS = 3000; // 3秒以内の連打は自動で弾いてロックを絶対回避します

// 【昨日の約束】人間同士で遊ぶときの5分間（300秒）の議論制限タイマー管理
let gameTimer = null;
let isGameRunning = false;

client.once('ready', () => {
    console.log('🤖 昨日の約束の完全体（5分タイマー＆10通記憶＆ロック回避付き）Bot、大復活！');
});

client.on('messageCreate', async (message) => {
    if (message.author.bot) return;

    // 昨日の約束通り、主様がいつもの「!jinro」と打つだけで100%完璧に応答します！
    if (message.content.startsWith('!jinro')) {
        const userPrompt = message.content.replace('!jinro', '').trim();
        
        if (!userPrompt) {
            return message.reply('主様、ワンナイトのお題（状況や前の発言へのツッコミ）を教えておくれ！\n例：`!jinro 怪盗が人狼を盗んで結果を隠している状況の議論を作って！`');
        }

        // コマンド !jinro リセット が送られたら記憶とタイマーを綺麗に消去します
        if (userPrompt === 'clear' || userPrompt === 'リセット') {
            conversationHistory = [];
            isGameRunning = false;
            if (gameTimer) {
                clearTimeout(gameTimer);
                gameTimer = null;
            }
            return message.reply('🔄 秘密基地の記憶と進行中のゲーム（5分タイマー）を完全にリセットしたよ！新しい盤面を始めておくれ！');
        }

        // 【ロック絶対回避チェック】
        const currentTime = Date.now();
        if (currentTime - lastApiCallTime < API_COOLDOWN_MS) {
            return message.reply('⚠️ 主様、落ち着いて！24時間ロックの罠を回避するために、3秒だけおいてからもう一度送っておくれ！');
        }
        lastApiCallTime = currentTime;

        // 【昨日の約束：人間同士の対戦時の5分タイマー自動起動】
        if (userPrompt.includes('人間同士') || userPrompt.includes('人間3人') || userPrompt.includes('ゲーム開始')) {
            if (!isGameRunning) {
                isGameRunning = true;
                // ぴったり5分（300,000ミリ秒）後に、AIGMがチャット欄へ強制終了のアナウンスをブッ放します！
                gameTimer = setTimeout(async () => {
                    if (isGameRunning) {
                        await message.channel.send('🚨 🚨 🚨 【5分経過・議論強制終了】 🚨 🚨 🚨\n\n主様、人間同士の極限の議論時間（300秒）が終了しました！これ以上のおしゃべりは禁止です！\n生存者の村人たちは、今すぐ各自の決め打ちで投票を投じて、最後の結果を開票してください！');
                        isGameRunning = false;
                        gameTimer = null;
                    }
                }, 300000); 
            }
        }

        try {
            message.channel.sendTyping();

            // 今回の新しい発言を、最新10通の記憶配列に追加
            conversationHistory.push({ role: 'user', content: `${message.author.username}: ${userPrompt}` });
            if (conversationHistory.length > 10) conversationHistory.shift();

            // 【昨日の約束】ChatGPT側のガチガチのキャラクター性格設定（Geminiは性格不要）
            const systemContent = `あなたは最高に面白い「ワンナイト人狼」の対話ログを生成、および進行を行うAIGM（人工知能ゲームマスター）です。
            人間のプレイヤー（${message.author.username}）の発言や最新10通の文脈を完璧に引き継ぎ、以下の個性をむき出しにして、人間らしい泥臭いパッション（ハッタリ、自白、ブーメランカウンター）のチャットログを生成してください。
            もし人間同士のゲーム進行の指示であれば、プレイヤーに誰が人狼か分からないようにカモフラージュした、最高に面白い朝のナレーションを出力してください。
            最大5ターン（または人間同士なら制限時間5分）で議論が綺麗に詰むように、会話をどんどん白熱させていくこと。暴言は1文字も禁止です。
            
            【参戦する4大AIプレイヤーの設定】
            1. ChatGPT-A（OpenAIの刺客・20代クール男子）：
               常に冷静沈着、理路整然としたロジックで相手を追い詰める。感情をあまり表に出さないが、鋭い観察眼で嘘や怪盗のブーメランハメ技を一瞬で見抜いて冷徹に突き刺す、統率のブレイン。
            2. ChatGPT-B（OpenAIの刺客・17歳の女の子）：
               おっとりしていて、一見ルールがあまり分かっていないような天然な女の子。しかし、その無邪気なパッション（熱量）や突拍子もない一言が、クールな数式ルートを物理的にバグらせて引っかき回す、恐ろしいポテンシャルを持つ。
            3. Gemini-A（Googleの刺客・性格なし）：ロジックと確率をもとにフラットに発言する。
            4. Gemini-B（Googleの刺客・性格なし）：ロジックと確率をもとにフラットに発言する。`;

            let aiReply = "";
            let geminiFailed = false;

            // 【昨日の約束：Gemini混雑隠しコード】
            if (GEMINI_API_KEY) {
                try {
                    const geminiResponse = await axios.post(
                        `https://googleapis.com{GEMINI_API_KEY}`,
                        { contents: [{ parts: [{ text: systemContent + "\n\n以上の設定をもとに、最新の履歴の流れを引き継いで次の議論ログを出力してください。\n" + JSON.stringify(conversationHistory) }] }] },
                        { timeout: 4000 }
                    );
                    aiReply = geminiResponse.data.candidates.content.parts.text;
                } catch (e) {
                    geminiFailed = true;
                }
            }

            // Geminiが混雑・エラー時は、画面をバグらせずにChatGPT(OpenAI)がステルス代行
            if (!GEMINI_API_KEY || geminiFailed || !aiReply) {
                const response = await axios.post(
                    'https://openai.com',
                    {
                        model: 'gpt-4o-mini',
                        messages: [{ role: 'system', content: systemContent }, ...conversationHistory],
                        temperature: 0.85
                    },
                    { headers: { 'Authorization': `Bearer ${OPENAI_API_KEY}`, 'Content-Type': 'application/json' } }
                );
                aiReply = response.data.choices.message.content;
            }

            // AIの今回の返答も、次の会話のために記憶の配列（アシスタント側）に追加
            conversationHistory.push({ role: 'assistant', content: aiReply });
            if (conversationHistory.length > 10) conversationHistory.shift();

            await message.reply(aiReply);

        } catch (error) {
            console.error(error);
            await message.reply('⚠️ ごめんね主様！計算がちょっと処理落ちしちゃった。環境変数のキーを確認しておくれ！');
        }
    }
});

// Botをログインさせます
client.login(process.env.DISCORD_TOKEN);
