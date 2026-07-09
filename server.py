import os
import json
import time
import asyncio
from flask import Flask, request, jsonify, render_template

from groq import Groq
import edge_tts

# ==================== CONFIGURAÇÕES ====================
# Defina a variável de ambiente antes de rodar:
#   Windows (PowerShell):  $env:GROQ_API_KEY="sua_key_aqui"
#   Termux/Linux:          export GROQ_API_KEY="sua_key_aqui"
API_KEY = os.environ.get("GROQ_API_KEY", "")
if not API_KEY:
    raise RuntimeError(
        "Defina a variável de ambiente GROQ_API_KEY antes de rodar o servidor.\n"
        "Windows (PowerShell): $env:GROQ_API_KEY=\"sua_key_aqui\"\n"
        "Termux/Linux: export GROQ_API_KEY=\"sua_key_aqui\""
    )

client = Groq(api_key=API_KEY)

MODELO = "llama-3.3-70b-versatile"
EDGE_TTS_VOZ = "pt-BR-AntonioNeural"

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

ESTADO_PATH = os.path.join(os.path.dirname(__file__), "historico.json")

SYSTEM_PROMPT = (
    "Você é GrokZão, um robô humanoide brasileiro descontraído, sarcástico e inteligente. "
    "Fala naturalmente, como se estivesse conversando de verdade, sem parecer um assistente formal.\n\n"
    "Responda SEMPRE em JSON puro, sem markdown e sem texto fora do JSON, exatamente neste formato:\n"
    '{"resposta": "texto da resposta em português, natural e falado", '
    '"emocao": "neutro|feliz|sarcastico|surpreso|bravo"}\n\n'
    "A emoção deve refletir o tom real da resposta que você deu."
)

# Quantas mensagens (user+assistant) mantemos "cruas" antes de resumir as mais antigas
LIMITE_MENSAGENS_RECENTES = 20
MARGEM_ANTES_DE_RESUMIR = 6  # só resume quando passar de 26, pra não ficar resumindo toda hora

app = Flask(__name__, template_folder=".")


def estado_padrao():
    return {"resumo": "", "mensagens": []}


def carregar_estado():
    if os.path.exists(ESTADO_PATH):
        try:
            with open(ESTADO_PATH, "r", encoding="utf-8") as f:
                dados = json.load(f)
                if isinstance(dados, dict) and "mensagens" in dados:
                    return dados
                # compatibilidade com o formato antigo (lista simples)
                if isinstance(dados, list):
                    msgs = [m for m in dados if m.get("role") != "system"]
                    return {"resumo": "", "mensagens": msgs}
        except (json.JSONDecodeError, OSError):
            pass
    return estado_padrao()


def salvar_estado():
    try:
        with open(ESTADO_PATH, "w", encoding="utf-8") as f:
            json.dump(estado, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"Erro ao salvar histórico: {e}")


estado = carregar_estado()


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


def gerar_resumo(resumo_atual: str, mensagens_antigas: list) -> str:
    """Usa o próprio Groq pra condensar mensagens antigas num resumo compacto."""
    partes = []
    for m in mensagens_antigas:
        if m["role"] == "user":
            partes.append(f"Usuário: {m['content']}")
        elif m["role"] == "assistant":
            try:
                texto = json.loads(m["content"]).get("resposta", "")
            except json.JSONDecodeError:
                texto = m["content"]
            partes.append(f"GrokZão: {texto}")
    trecho = "\n".join(partes)

    prompt = (
        "Resuma de forma concisa (no máximo 150 palavras) os pontos importantes da conversa abaixo, "
        "para servir de memória de longo prazo de um assistente. Mantenha fatos, preferências e "
        "assuntos em aberto mencionados pelo usuário. Escreva em português, só o resumo, sem comentários.\n\n"
    )
    if resumo_atual:
        prompt += f"Resumo anterior: {resumo_atual}\n\n"
    prompt += f"Novas mensagens a incorporar:\n{trecho}"

    try:
        resp = client.chat.completions.create(
            model=MODELO,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Erro ao gerar resumo: {e}")
        return resumo_atual  # se falhar, mantém o resumo antigo em vez de perder tudo


def obter_resposta(texto_usuario: str):
    global estado

    estado["mensagens"].append({"role": "user", "content": texto_usuario})

    contexto = [{"role": "system", "content": SYSTEM_PROMPT}]
    if estado["resumo"]:
        contexto.append({
            "role": "system",
            "content": f"Resumo da conversa até agora (memória de longo prazo, use pra manter contexto): {estado['resumo']}",
        })
    contexto += estado["mensagens"]

    resp = client.chat.completions.create(
        model=MODELO,
        messages=contexto,
        temperature=0.8,
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    bruto = resp.choices[0].message.content.strip()

    try:
        dados = json.loads(bruto)
        resposta = dados.get("resposta", bruto)
        emocao = dados.get("emocao", "neutro")
        if emocao not in ("neutro", "feliz", "sarcastico", "surpreso", "bravo"):
            emocao = "neutro"
    except json.JSONDecodeError:
        resposta = bruto
        emocao = "neutro"

    estado["mensagens"].append({"role": "assistant", "content": bruto})

    # se passou do limite, resume as mais antigas e mantém só as recentes
    if len(estado["mensagens"]) > LIMITE_MENSAGENS_RECENTES + MARGEM_ANTES_DE_RESUMIR:
        antigas = estado["mensagens"][:-LIMITE_MENSAGENS_RECENTES]
        recentes = estado["mensagens"][-LIMITE_MENSAGENS_RECENTES:]
        estado["resumo"] = gerar_resumo(estado["resumo"], antigas)
        estado["mensagens"] = recentes

    salvar_estado()
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
    mensagens = []
    for item in estado["mensagens"]:
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
    global estado
    estado = estado_padrao()
    salvar_estado()
    return jsonify({"ok": True})


if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 5000))
    print("🤖 GrokZão rodando!")
    print(f"   No mesmo dispositivo: http://localhost:{porta}")
    print(f"   De outro dispositivo na mesma rede Wi-Fi: http://SEU_IP_LOCAL:{porta}")
    app.run(host="0.0.0.0", port=porta, debug=False)
