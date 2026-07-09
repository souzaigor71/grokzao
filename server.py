import os
import json
import time
import asyncio
from flask import Flask, request, jsonify, render_template

from groq import Groq
import edge_tts
from supabase import create_client, Client

# ==================== CONFIGURAÇÕES ====================
API_KEY = os.environ.get("GROQ_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

if not API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Certifique-se de definir as variáveis de ambiente no Render:\n"
        "GROQ_API_KEY, SUPABASE_URL e SUPABASE_KEY."
    )

client = Groq(api_key=API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

MODELO = "llama-3.3-70b-versatile"
EDGE_TTS_VOZ = "pt-BR-AntonioNeural"

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

SYSTEM_PROMPT = (
    "Você é GrokZão, um robô humanoid brasileiro descontraído, sarcástico e inteligente. "
    "Fala naturalmente, como se estivesse conversando de verdade, sem parecer um assistente formal.\n\n"
    "Responda SEMPRE em JSON puro, sem markdown e sem texto fora do JSON, exatamente neste formato:\n"
    '{"resposta": "texto da resposta em português, natural e falado", '
    '"emocao": "neutro|feliz|sarcastico|surpreso|bravo"}\n\n'
    "A emoção deve refletir o tom real da resposta que você deu."
)

app = Flask(__name__, template_folder=".")

# Cache local para manter o histórico fluido e integrado ao seu front-end
historico_local = []

def sincronizar_historico_nuvem():
    """Busca o histórico completo armazenado de forma permanente na nuvem."""
    global historico_local
    try:
        resposta = supabase.table("historico_grokzao").select("role, content").order("created_at").execute()
        dados = resposta.data
        if dados:
            historico_local = [{"role": item["role"], "content": item["content"]} for item in dados]
        else:
            historico_local = []
    except Exception as e:
        print(f"Erro ao sincronizar com banco de dados: {e}")
        historico_local = []

# Sincroniza as mensagens assim que o servidor inicializa
sincronizar_historico_nuvem()

def gerar_embedding_simulado(texto: str):
    """
    Gera uma representação vetorial matemática estável em Python para indexação semântica 
    usando as propriedades dos caracteres e frequências, compatível com pgvector(1536).
    """
    vetor = [0.0] * 1536
    for i, char in enumerate(texto):
        vetor[i % 1536] += ord(char)
    norma = sum(x**2 for x in vetor) ** 0.5
    if norma > 0:
        vetor = [x / norma for x in vetor]
    return vetor

def limpar_audios_antigos(max_idade_segundos: int = 300):
    agora = time.time()
    for nome in os.listdir(AUDIO_DIR):
        caminho = os.path.join(AUDIO_DIR, nome)
        if os.path.isfile(caminho) and agora - os.path.getmtime(caminho) > max_idade_segundos:
            try:
                os.remove(caminho)
            except OSError:
                pass

async def gerar_audio(texto: str, nome_arquivo: str) -> str:
    communicate = edge_tts.Communicate(text=texto, voice=EDGE_TTS_VOZ)
    caminho = os.path.join(AUDIO_DIR, nome_arquivo)
    await communicate.save(caminho)
    return caminho

def obter_resposta(texto_usuario: str):
    global historico_local
    
    # 1. Gera o vetor para a busca semântica
    embedding_usuario = gerar_embedding_simulado(texto_usuario)
    
    # 2. Insere de forma permanente a mensagem do usuário no banco persistente
    try:
        supabase.table("historico_grokzao").insert({
            "role": "user",
            "content": texto_usuario,
            "embedding": embedding_usuario
        }).execute()
    except Exception as e:
        print(f"Erro ao persistir no Supabase: {e}")

    # 3. Busca Semântica: Pergunta ao banco por lembranças relevantes sobre o assunto atual
    memorias_relevantes = []
    try:
        rpc_res = supabase.rpc("buscar_memorias_grokzao", {
            "query_embedding": embedding_usuario,
            "match_threshold": 0.1,
            "match_count": 5
        }).execute()
        if rpc_res.data:
            memorias_relevantes = [
                f"[{item['role']} comentou no passado]: {item['content']}"
                for item in rpc_res.data if item['content'] != texto_usuario
            ]
    except Exception as e:
        print(f"Erro ao buscar memórias semânticas: {e}")

    # Força atualização do cache para incluir o que acabou de ser gravado
    sincronizar_historico_nuvem()

    # 4. Injeta as memórias recuperadas diretamente no contexto da API da Groq
    contexto_prompt = SYSTEM_PROMPT
    if memorias_relevantes:
        contexto_prompt += "\n\n[Lembranças de conversas antigas que você lembrou sobre este assunto]:\n" + "\n".join(memorias_relevantes)

    mensagens_enviar = [{"role": "system", "content": contexto_prompt}]
    
    # Envia as últimas 20 mensagens recentes para manter a fluidez contínua do diálogo atual
    ultimas_mensagens = historico_local[-20:] if len(historico_local) > 20 else historico_local
    for msg in ultimas_mensagens:
        if msg["role"] != "system":
            mensagens_enviar.append(msg)

    # Garante que a última mensagem digitada faça parte do envio
    if not mensagens_enviar or mensagens_enviar[-1]["content"] != texto_usuario:
        mensagens_enviar.append({"role": "user", "content": texto_usuario})

    resp = client.chat.completions.create(
        model=MODELO,
        messages=mensagens_enviar,
        temperature=0.8,
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    bruto = resp.choices[0].message.content.strip()

    try:
        dados = json.loads(bruto)
        resposta = dados.get("resposta", bruto)
        emocao = dados.get("emocao", "neutro")
    except json.JSONDecodeError:
        resposta = bruto
        emocao = "neutro"

    # 5. Salva a resposta gerada pelo robô no banco definitivo em nuvem
    embedding_resposta = gerar_embedding_simulado(bruto)
    try:
        supabase.table("historico_grokzao").insert({
            "role": "assistant",
            "content": bruto,
            "embedding": embedding_resposta
        }).execute()
    except Exception as e:
        print(f"Erro ao persistir resposta no Supabase: {e}")

    sincronizar_historico_nuvem()
    return resposta, emocao

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    dados = request.get_json(force=True, silent=True) or {}
    texto_usuario = (dados.get("mensagem") or "").strip()

    if not texto_usuario:
        return jsonify({"erro": "Mensagem vazia"}), 400

    try:
        resposta, emocao = obter_resposta(texto_usuario)
    except Exception as e:
        return jsonify({"erro": f"Erro ao consultar a IA: {e}"}), 500

    limpar_audios_antigos()
    nome_arquivo = f"fala_{int(time.time() * 1000)}.mp3"

    try:
        asyncio.run(gerar_audio(resposta, nome_arquivo))
        audio_url = f"/static/audio/{nome_arquivo}"
    except Exception as e:
        print(f"Erro na geração de voz: {e}")
        audio_url = None

    return jsonify({
        "resposta": resposta,
        "emocao": emocao,
        "audio_url": audio_url,
    })

@app.route("/historico", methods=["GET"])
def obter_historico():
    sincronizar_historico_nuvem()
    mensagens = []
    for item in historico_local:
        if item["role"] == "user":
            mensagens.append({"quem": "user", "texto": item["content"]})
        elif item["role"] == "assistant":
            try:
                dados = json.loads(item["content"])
                texto = dados.get("resposta", item["content"])
            except json.JSONDecodeError:
                texto = item["content"]
            mensagens.append({"quem": "bot", "texto": texto})
    return jsonify({"mensagens": mensagens})

@app.route("/reset", methods=["POST"])
def reset():
    global historico_local
    try:
        supabase.table("historico_grokzao").delete().neq("role", "system").execute()
    except Exception as e:
        print(f"Erro ao limpar banco de dados: {e}")
    historico_local = []
    return jsonify({"ok": True})

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    print("🤖 GrokZão com Memória Eterna em Nuvem Rodando!")
    app.run(host="0.0.0.0", port=porta, debug=False)
