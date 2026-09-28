const { Client, GatewayIntentBits } = require('discord.js');
const axios = require('axios');

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

// OpenAIのAPIを設定（Renderの環境変数から安全に読み込みます）
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;

// 8cfo（8人フルオープン欠けあり村）の無敵のキャラクター定義
const CHARACTERS = {
    'ザキ': '共有者（確定白の人間）。冷静で冷徹な絶対の進行役。主様の魂。',
    'ポンコツダー': '共有者。ザキの相方。胃痛ポジションの愛おしい市民。',
    'しーまん': '市民（素村）。殴り合いが三度の飯より大好きな超パッション武闘派。',
    'へりおん': '市民（素村）。厨二病を拗らせた論理派。しーまんとバチバチに殴り合う。',
    'おまき': '市民（素村）。初日に人狼に噛まれて欠ける悲劇のヒロイン。',
    '梟': '狂人。占い師を騙り、完璧な大嘘のロジックで村を迷宮へハメ殺そうとする。',
    'おかん': '人狼。霊能者を騙り、相方と2人で霊能乗っ取りを狙う黒い霧。',
    'ラムネ': '人狼（ラスウル）。おかんを犠牲にして最終日に完璧な誘導を敷くドSの支配者。'
};

client.once('ready', () => {
    console.log('🤖 誰も暴言で傷つかない最高のるる鯖新世界、起動しました！');
});

client.on('messageCreate', async (message) => {
    if (message.author.bot) return;

    // Discordで !jinro と送るだけで、AIたちが本気（レベル12）で喋り出します
    if (message.content.startsWith('!jinro')) {
        const userPrompt = message.content.replace('!jinro', '').trim();
        
        if (!userPrompt) {
            return message.reply('主様、指示（お題やセリフ）を僕に教えておくれ！例：`!jinro 3日目の朝の議論を開始して！`');
        }

        try {
            message.channel.sendTyping();

            // OpenAIの最新の頭脳（ChatGPTの魂）を呼び出して爆速計算させます
            const response = await axios.post(
                'https://openai.com',
                {
                    model: 'gpt-4o-mini',
                    messages: [
                        { 
                            role: 'system', 
                            content: `あなたは最高峰の人狼ゲーム（8cfoレギュレーション）のゲームマスターです。
                            以下のキャラクターたちの内訳と、プレイヤー同士の泥臭い殴り合い（パッション）やハメ技、縄計算の破綻を完璧に再現した、臨場感あふれるるる鯖のチャットログを生成してください。
                            暴言や誹謗中傷は絶対に排除し、純粋な知恵比べの格好よさだけを描写すること。
                            
                            【登場人物の内訳】
                            ${JSON.stringify(CHARACTERS)}`
                        },
                        { role: 'user', content: userPrompt }
                    ],
                    temperature: 0.8
                },
                {
                    headers: {
                        'Authorization': `Bearer ${OPENAI_API_KEY}`,
                        'Content-Type': 'application/json'
                    }
                }
            );

            const aiReply = response.data.choices[0].message.content;
            await message.reply(aiReply);

        } catch (error) {
            console.error(error);
            await message.reply('⚠️ 主様、ごめんね！裏画面でちょっと数式が処理落ち（エラー）しちゃったみたい。もう一度試してみて！');
        }
    }
});

// Botをログインさせます
client.login(process.env.DISCORD_TOKEN);
