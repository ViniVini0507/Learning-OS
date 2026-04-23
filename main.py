import os
import json
import urllib.request
from datetime import date
from dotenv import load_dotenv
from notion_client import Client
import google.generativeai as genai

load_dotenv()

# ── CONFIGURAÇÕES INICIAIS ──────────────────────────────────────────────────
notion = Client(auth=os.environ["NOTION_TOKEN"])
DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-2.5-flash')

# ── 1. BUSCA E HIERARQUIA (NOTION) ──────────────────────────────────────────
def obter_data_source_id(db_id):
    """Busca o ID da fonte de dados para consulta."""
    db_info = notion.databases.retrieve(database_id=db_id)
    return db_info["data_sources"][0]["id"]

def obter_caminho_completo(page_id, lista_nomes=None):
    """Função recursiva para mapear a hierarquia de pastas no Anki."""
    if lista_nomes is None: lista_nomes = []
    try:
        pagina = notion.pages.retrieve(page_id=page_id)
        titulo = pagina["properties"]["Name"]["title"][0]["plain_text"] if "Name" in pagina["properties"] else "Sem Titulo"
        lista_nomes.insert(0, titulo)

        parent = pagina.get("parent", {})
        if "Parent item" in pagina["properties"] and pagina["properties"]["Parent item"]["relation"]:
            pai_id = pagina["properties"]["Parent item"]["relation"][0]["id"]
            return obter_caminho_completo(pai_id, lista_nomes)
        elif parent.get("type") == "page_id":
            return obter_caminho_completo(parent["page_id"], lista_nomes)
        return lista_nomes
    except: return lista_nomes

def buscar_paginas_marcadas():
    ds_id = obter_data_source_id(DATABASE_ID)
    filtro = {"property": "⚙️ Generate Flashcards", "checkbox": {"equals": True}}
    paginas, has_more, cursor = [], True, None

    while has_more:
        res = notion.data_sources.query(data_source_id=ds_id, filter=filtro, start_cursor=cursor) if cursor else notion.data_sources.query(data_source_id=ds_id, filter=filtro)
        for r in res["results"]:
            # --- SEGURANÇA: IGNORA PÁGINAS JÁ ARQUIVADAS ---
            if r.get("archived"):
                continue

            try:
                cat = r["properties"]["Category"]["select"]["name"]
            except: cat = "Geral"
            paginas.append({"id": r["id"], "titulo": r["properties"]["Name"]["title"][0]["plain_text"], "categoria": cat})
        has_more, cursor = res.get("has_more", False), res.get("next_cursor")
    return paginas

def extrair_texto_pagina(page_id):
    """Extrai todo o conteúdo de texto de uma página, incluindo sub-blocos."""
    texto, cursor = "", None
    while True:
        blocos = notion.blocks.children.list(block_id=page_id, start_cursor=cursor) if cursor else notion.blocks.children.list(block_id=page_id)
        for b in blocos["results"]:
            tipo = b["type"]
            if tipo in b and "rich_text" in b[tipo]:
                for t in b[tipo]["rich_text"]: texto += t["plain_text"]
                texto += "\n"
            if b.get("has_children"): texto += extrair_texto_pagina(b["id"])
        if not blocos["has_more"]: break
        cursor = blocos["next_cursor"]
    return texto

# ── 2. INTELIGÊNCIA ARTIFICIAL (GEMINI) ─────────────────────────────────────
def gerar_flashcards(texto, titulo):
    """Gera até 10 flashcards à prova de erros de formatação (Markdown) e trava de idioma."""
    if len(texto.strip()) < 80: return []

    prompt = f"""Você é um tutor acadêmico de elite.
    Sua missão é extrair os conceitos essenciais do texto abaixo e criar flashcards.
    Tópico da Aula/Texto: "{titulo}"

    🚨 REGRA DE IDIOMA (CRÍTICA):
    Mantenha ESTRITAMENTE o idioma ORIGINAL do texto.
    - Se as anotações estão em Inglês, gere perguntas e respostas em Inglês.
    - Se estão em Francês, gere em Francês.
    - NÃO traduza para o português a menos que o texto original seja em português.

    REGRAS DE CONTEÚDO (MUITO IMPORTANTE):
    - Ciências Sociais/Universidade: Foque em conceitos, teses de autores, termos técnicos e argumentos.
    - SAP, TI e Negócios: Foque em arquitetura de sistemas, uso prático e LÓGICA DE NEGÓCIO (ex: fluxos de FP&A, modelagem financeira, regras de negócios).
    - Idiomas (Inglês/Francês): Foque em extrair vocabulário novo, expressões idiomáticas, regras gramaticais ou falsos cognatos presentes no texto.
    - Ignore logística, datas de prova ou ruído (ex: "fazer exercício 3").

    FORMATO OBRIGATÓRIO:
    Você deve gerar no máximo 10 flashcards.
    NÃO use negrito (**). NÃO use asteriscos.
    Siga EXATAMENTE este padrão para cada card:
    P: [Sua pergunta]
    R: [Sua resposta]

    Se o texto for apenas um aviso logístico sem matéria, responda: SEM_CONTEUDO.

    Notas:
    {texto[:5000]}"""

    try:
        res = model.generate_content(prompt)

        # Limpeza pesada: Remove negritos e ajusta espaçamentos que a IA tenta inventar
        texto_ia = res.text.replace("**P:**", "P:").replace("**R:**", "R:")
        texto_ia = texto_ia.replace("**P:** ", "P:").replace("**R:** ", "R:")
        texto_ia = texto_ia.replace("**P: **", "P:").replace("**R: **", "R:")

        if "SEM_CONTEUDO" in texto_ia: return []

        cards = []
        q = None
        for linha in texto_ia.split("\n"):
            linha = linha.strip()
            if linha.startswith("P:"):
                q = linha[2:].strip()
            elif linha.startswith("R:") and q:
                cards.append({"pergunta": q, "resposta": linha[2:].strip()})
                q = None # Reseta para o próximo card
                if len(cards) >= 10: break

        return cards
    except Exception as e:
        print(f"   🔴 ERRO NO GEMINI (Cards): {e}")
        return []

def consolidar_sap_meetings(textos, titulos):
    """
    Versão Final: Força a saída em Inglês, ignora papo furado e mostra erros.
    """
    conteudo_bruto = "\n\n--- NEW MEETING NOTES ---\n\n".join(textos)[:15000]

    prompt = f"""You are a Senior SAC Solutions Architect and Mentor.
You have been provided with notes from {len(titulos)} technical meetings.

YOUR MISSION:
Extract only the technical and conceptual KNOWLEDGE that is useful for a consultant's career long-term.

LANGUAGE RULE:
The source notes are in English. You MUST respond EXCLUSIVELY in English. Do not translate to Portuguese.

RETENTION FILTER (STRICT):
- ❌ IGNORE: Project-specific logistics (e.g., "we will use Model X", "meeting at 9am", "slides by Friday").
- ✅ KEEP: SAC architectural logic, technical limitations, Story Design best practices, and Data Modeling rules.
- ✅ KEEP: The "WHY" behind technical decisions that apply to any SAC project.

FORMAT:
Respond ONLY with technical bullet points in Markdown.
DO NOT include conversational filler like "As an architect" or "Here are the notes".
If the notes contain ONLY operational noise and ZERO technical content, respond EXACTLY with this string: NO_TECHNICAL_CONTENT"""

    try:
        res = model.generate_content(prompt)

        # Filtro simplificado: só anula se a IA disser explicitamente que não tem conteúdo
        if "no_technical_content" in res.text.lower():
            return ""

        return res.text

    except Exception as e:
        # AGORA VOCÊ VAI VER SE A API DO GOOGLE ESTÁ DANDO PAU!
        print(f"   🔴 ERRO NA API DO GEMINI: {e}")
        return ""

# ── 3. INTEGRAÇÃO (ANKI E NOTION) ───────────────────────────────────────────
def salvar_no_anki_batch(cards, page_id, categoria):
    """Envia múltiplos cartões para o Anki de uma só vez (Alta Velocidade)."""
    caminho = obter_caminho_completo(page_id)
    deck = f"Notion::{categoria}::{'::'.join(caminho)}"

    # Cria o Deck
    payload_deck = {"action": "createDeck", "version": 6, "params": {"deck": deck}}
    urllib.request.urlopen(urllib.request.Request("http://localhost:8765", json.dumps(payload_deck).encode("utf-8")))

    # Prepara notas
    notes = [{"deckName": deck, "modelName": "Basic", "fields": {"Front": c["pergunta"], "Back": c["resposta"]}, "options": {"allowDuplicate": False}} for c in cards]
    payload_notes = {"action": "addNotes", "version": 6, "params": {"notes": notes}}
    try:
        urllib.request.urlopen(urllib.request.Request("http://localhost:8765", json.dumps(payload_notes).encode("utf-8")))
        return True
    except: return False

def criar_pagina_consolidada(conteudo, pai_id=None):
    """Cria a página mestre dentro da hierarquia original no Notion."""
    blocos = [conteudo[i:i+2000] for i in range(0, len(conteudo), 2000)]
    children = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": b}}]}} for b in blocos]

    props = {"Name": {"title": [{"text": {"content": f"💎 Consolidado Técnico SAC - {date.today().strftime('%d/%m/%Y')}"}}]}, "Category": {"select": {"name": "SAP"}}}
    if pai_id: props["Parent item"] = {"relation": [{"id": pai_id}]}

    nova = notion.pages.create(parent={"database_id": DATABASE_ID}, properties=props, children=children[:100])
    return nova["id"], props["Name"]["title"][0]["text"]["content"]

# ── 4. EXECUÇÃO PRINCIPAL (BLINDADA) ───────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Motor de alta velocidade iniciado...")
    paginas = buscar_paginas_marcadas()
    sap_m_txt, sap_m_tit, sap_m_ids = [], [], []

    for i, p in enumerate(paginas, 1):
        # CASO ESPECIAL: REUNIÕES SAP (Agrupamento e Consolidação)
        if p['categoria'] == "SAP Meetings":
            print(f"[{i}/{len(paginas)}] Agrupando reunião: {p['titulo']}")
            sap_m_txt.append(extrair_texto_pagina(p["id"]))
            sap_m_tit.append(p['titulo'])
            sap_m_ids.append(p['id'])

            if len(sap_m_ids) >= 10:
                print(f"   💎 Consolidando lote de 10 reuniões...")
                resumo = consolidar_sap_meetings(sap_m_txt, sap_m_tit)

                if resumo:
                    try:
                        p_info = notion.pages.retrieve(page_id=sap_m_ids[0])
                        pai = p_info["properties"]["Parent item"]["relation"][0]["id"] if "Parent item" in p_info["properties"] and p_info["properties"]["Parent item"]["relation"] else None

                        n_id, n_tit = criar_pagina_consolidada(resumo, pai)
                        c_cards = gerar_flashcards(resumo, n_tit)
                        if c_cards:
                            salvar_no_anki_batch(c_cards, n_id, "SAP")
                        print(f"   ✅ Diamante criado com sucesso!")
                    except Exception as e:
                        print(f"   ⚠️ Erro crítico no lote: {e}")
                else:
                    print(f"   🗑️ Lote ignorado (Apenas ruído/logística. Sem conteúdo técnico).")

                # Desmarca as caixinhas sempre, com ou sem diamante gerado!
                for rid in sap_m_ids:
                    try:
                        notion.pages.update(page_id=rid, properties={"⚙️ Generate Flashcards": {"checkbox": False}})
                    except Exception as e:
                        pass

                # Limpa as listas
                sap_m_txt, sap_m_tit, sap_m_ids = [], [], []

        # CASO PADRÃO: PÁGINAS INDIVIDUAIS (Faculdade, Idiomas, SAP Estudo)
        else:
            print(f"[{i}/{len(paginas)}] Processando: {p['titulo']}")

            try:
                # 1. Extrai o texto
                texto_pag = extrair_texto_pagina(p["id"])

                if not texto_pag or len(texto_pag.strip()) < 80:
                    print(f"   🗑️ Ignorado: Página sem conteúdo suficiente para gerar cards.")
                    notion.pages.update(page_id=p["id"], properties={"⚙️ Generate Flashcards": {"checkbox": False}})
                    continue

                # 2. Chama a IA (Gemini)
                try:
                    cards_pag = gerar_flashcards(texto_pag, p["titulo"])
                except Exception as e:
                    print(f"   🔴 ERRO NA API DO GEMINI: {e}")
                    continue

                # 3. Salva no Anki e atualiza o Notion
                if cards_pag:
                    sucesso_anki = salvar_no_anki_batch(cards_pag, p["id"], p["categoria"])
                    if sucesso_anki:
                        try:
                            notion.pages.update(page_id=p["id"], properties={"⚙️ Generate Flashcards": {"checkbox": False}})
                            print(f"   ✅ {len(cards_pag)} cards injetados e Notion desmarcado.")
                        except Exception as e:
                            print(f"   ⚠️ Cards salvos, mas falha ao desmarcar o Notion: {e}")
                    else:
                        print(f"   🔴 ERRO DE CONEXÃO: Falha ao enviar. O aplicativo do Anki está aberto?")
                else:
                    print(f"   ⚠️ IA retornou vazio (Conteúdo irrelevante).")
                    notion.pages.update(page_id=p["id"], properties={"⚙️ Generate Flashcards": {"checkbox": False}})

            except Exception as e:
                print(f"   🚨 ERRO CRÍTICO INESPERADO ao processar '{p['titulo']}': {e}")

    # ==============================================================
    # PROCESSAR A "SOBRA" (Reuniões SAP < 10)
    # ==============================================================
    if len(sap_m_ids) > 0:
        print(f"\n   💎 Consolidando lote residual de {len(sap_m_ids)} reuniões...")
        resumo = consolidar_sap_meetings(sap_m_txt, sap_m_tit)

        if resumo:
            try:
                p_info = notion.pages.retrieve(page_id=sap_m_ids[0])
                pai = p_info["properties"]["Parent item"]["relation"][0]["id"] if "Parent item" in p_info["properties"] and p_info["properties"]["Parent item"]["relation"] else None

                n_id, n_tit = criar_pagina_consolidada(resumo, pai)
                c_cards = gerar_flashcards(resumo, n_tit)
                if c_cards:
                    salvar_no_anki_batch(c_cards, n_id, "SAP")
                print(f"   ✅ Lote residual processado com sucesso.")
            except Exception as e:
                print(f"   ⚠️ Erro no lote residual: {e}")
        else:
             print(f"   🗑️ Lote residual ignorado (Sem conteúdo técnico).")

        for rid in sap_m_ids:
            try:
                notion.pages.update(page_id=rid, properties={"⚙️ Generate Flashcards": {"checkbox": False}})
            except:
                pass

    print("\n✅ Processamento concluído! Verifique seu Anki e Notion.")