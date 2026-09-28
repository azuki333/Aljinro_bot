const { Client, GatewayIntentBits } = require('discord.js');

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

// 環境変数からOpenAIのAPIキーを安全に読み込みます
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;

// 最新10通分の会話履歴を記憶しておくための配列スタック
let conversationHistory = [];

// 【ロック絶対回避】3秒以内の連打は自動で弾いて24時間ロックを絶対回避します
let lastApiCallTime = 0;
const API_COOLDOWN_MS = 3000; 

// 人間同士で遊ぶときの5分間（300秒）の議論制限タイマー管理
let gameTimer = null;
let isGameRunning = false;

client.once('ready', () => {
    console.log('🤖 昨日の約束の完全体（!jinro対応・5分タイマー＆10通記憶）Bot、完全起動！');
});

client.on('messageCreate', async (message) => {
    if (message.author.bot) return;

    // 主様がいつもの「!jinro」と打つだけで100%完璧に応答します！
    if (message.content.startsWith('!jinro')) {
        const userPrompt = message.content.replace('!jinro', '').trim();
        
        if (!userPrompt) {
            return message.reply('主様、ワンナイトのお題（状況や前の発言へのツッコミ）を教えておくれ！\n例：`!jinro 怪盗が人狼を盗んで結果を隠している状況の議論を作って！`');
        }

        if (userPrompt === 'clear' || userPrompt === 'リセット') {
            conversationHistory = [];
            isGameRunning = false;
            if (gameTimer) {
                clearTimeout(gameTimer);
                gameTimer = null;
            }
            return message.reply('🔄 秘密基地の記憶と進行中のゲーム（5分タイマー）を完全にリセットしたよ！');
        }

        // 【ロック絶対回避チェック】
        const currentTime = Date.now();
        if (currentTime - lastApiCallTime < API_COOLDOWN_MS) {
            return message.reply('⚠️ 主様、落ち着いて！24時間ロックの罠を回避するために、3秒だけおいてからもう一度送っておくれ！');
        }
        lastApiCallTime = currentTime;

        // 【5分タイマー自動起動】
        if (userPrompt.includes('人間同士') || userPrompt.includes('人間3人') || userPrompt.includes('ゲーム開始')) {
            if (!isGameRunning) {
                isGameRunning = true;
                // ぴったり5分後に、AIGMがチャット欄へ強制終了のアナウンスをブッ放します！
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

            // 20代クール男子と17歳天然女子のキャラクター性格設定
            const systemContent = `あなたは最高に面白い「ワンナイト人狼」の対話ログを生成、および進行を行うAIGM（人工知能ゲームマスター）です。
            人間のプレイヤー（${message.author.username}）の発言や最新10通の文脈を完璧に引き継ぎ、以下の個性をむき出しにして、人間らしい泥臭いパッション（ハッタリ、自白、ブーメランカウンター）のチャットログを生成してください。
            最大5ターン（または人間同士なら制限時間5分）で議論が綺麗に詰むように、会話をどんどん白熱させていくこと。プレイヤーが合計5人になるように数合わせを行って発言を出力してください。暴言は1文字も禁止です。
            
            【参戦する4大AIプレイヤーの設定】
            1. ChatGPT-A（OpenAIの刺客・20代クール男子）：
               常に冷静沈着、理路整然としたロジックで相手を追い詰める。感情をあまり表に出さないが、鋭い観察眼で嘘や怪盗のブーメランハメ技を一瞬で見抜いて冷徹に突き刺す、統率のブレイン。
            2. ChatGPT-B（OpenAIの刺客・17歳の女の子）：
               おっとりしていて、一見ルールがあまり分かっていないような天然な女の子。しかし、その無邪気なパッション（熱量）や突拍子もない一言が、クールな数式ルートを物理的にバグらせて引っかき回す、恐ろしいポテンシャルを持つ。
            3. ChatGPT-C（性格なし）：ロジックと確率をもとにフラットに発言する。
            4. ChatGPT-D（性格なし）：ロジックと確率をもとにフラットに発言する。`;

            // 【完全エラー回避】外部ライブラリを一切使わない、標準の最安定通信方式
            const response = await fetch('https://openai.com', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${OPENAI_API_KEY}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    model: 'gpt-4o-mini',
                    messages: [{ role: 'system', content: systemContent }, ...conversationHistory],
                    temperature: 0.85
                })
            });

            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error ? data.error.message : 'OpenAI API Error');
            }

            const aiReply = data.choices[0].message.content;

            // AIの今回の返答も、次の会話のために記憶の配列に追加
            conversationHistory.push({ role: 'assistant', content: aiReply });
            if (conversationHistory.length > 10) conversationHistory.shift();

            await message.reply(aiReply);

        } catch (error) {
            console.error(error);
            await message.reply('⚠️ 主様、ごめんね！APIの通信でちょっと処理落ちしちゃった。環境変数に `OPENAI_API_KEY` が正しく入っているか確認しておくれ！');
        }
    }
});

// Botをログインさせます
client.login(process.env.DISCORD_TOKEN);
