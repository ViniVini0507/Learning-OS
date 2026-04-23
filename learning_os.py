import os
import json
import urllib.request
from datetime import date, datetime
from dotenv import load_dotenv
from notion_client import Client
import google.generativeai as genai

load_dotenv()

# ── CONFIGURAÇÕES ──────────────────────────────────────────────────────────
notion = Client(auth=os.environ["NOTION_TOKEN"])
DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-2.5-flash') # Versão estável

# ── 1. UTILITÁRIOS NOTION ──────────────────────────────────────────────────
def obter_data_source_id(db_id):
    db_info = notion.databases.retrieve(database_id=db_id)
    return db_info["data_sources"][0]["id"]

def obter_caminho_completo(page_id, lista_nomes=None):
    if lista_nomes is None: lista_nomes = []
    try:
        pagina = notion.pages.retrieve(page_id=page_id)
        titulo = pagina["properties"]["Name"]["title"][0]["plain_text"] if "Name" in pagina["properties"] else "Sem Titulo"
        lista_nomes.insert(0, titulo)
        if "Parent item" in pagina["properties"] and pagina["properties"]["Parent item"]["relation"]:
            pai_id = pagina["properties"]["Parent item"]["relation"][0]["id"]
            return obter_caminho_completo(pai_id, lista_nomes)
        return lista_nomes
    except: return lista_nomes

def buscar_paginas_marcadas():
    ds_id = obter_data_source_id(DATABASE_ID)
    filtro = {"property": "⚙️ Generate Flashcards", "checkbox": {"equals": True}}
    paginas = []
    res = notion.data_sources.query(data_source_id=ds_id, filter=filtro)
    for r in res["results"]:
        if r.get("archived"): continue
        try: cat = r["properties"]["Category"]["select"]["name"]
        except: cat = "Geral"
        paginas.append({"id": r["id"], "titulo": r["properties"]["Name"]["title"][0]["plain_text"], "categoria": cat})
    return paginas

def extrair_texto_pagina(page_id):
    texto, cursor = "", None
    while True:
        blocos = notion.blocks.children.list(block_id=page_id, start_cursor=cursor)
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
    if len(texto.strip()) < 80: return []
    prompt = f"""Você é um tutor acadêmico de elite. Tópico: "{titulo}"
    🚨 REGRA DE IDIOMA: Mantenha ESTRITAMENTE o idioma ORIGINAL do texto (EN/FR/PT).
    REGRAS DE CONTEÚDO:
    - Ciências Sociais: Conceitos, teses de autores, argumentos sociológicos.
    - SAP/FP&A: Arquitetura, lógica de negócio e regras financeiras.
    - Idiomas: Vocabulário novo e expressões.
    FORMATO: Máximo 10 cards. P: [pergunta] / R: [resposta]. Sem negrito ou asteriscos.
    Notas: {texto[:5000]}"""
    try:
        res = model.generate_content(prompt)
        texto_ia = res.text.replace("**P:**", "P:").replace("**R:**", "R:").strip()
        if "SEM_CONTEUDO" in texto_ia: return []
        cards, q = [], None
        for linha in texto_ia.split("\n"):
            linha = linha.strip()
            if linha.startswith("P:"): q = linha[2:].strip()
            elif linha.startswith("R:") and q:
                cards.append({"pergunta": q, "resposta": linha[2:].strip()})
                q = None
        return cards
    except Exception as e:
        print(f"   🔴 ERRO GEMINI: {e}")
        return []

def consolidar_sap_meetings(textos, titulos):
    conteudo_bruto = "\n\n--- NEW MEETING ---\n\n".join(textos)[:15000]
    prompt = f"""Senior SAC Solutions Architect. Analyze {len(titulos)} meetings.
    MISSION: Extract technical knowledge/business logic. Ignore logistics.
    LANGUAGE: Respond EXCLUSIVELY in English.
    FORMAT: Technical bullet points. If only noise, respond: NO_TECHNICAL_CONTENT.
    NOTES: {conteudo_bruto}"""
    try:
        res = model.generate_content(prompt)
        if "no_technical_content" in res.text.lower(): return ""
        return res.text
    except: return ""

# ── 3. INTEGRAÇÃO ANKI ──────────────────────────────────────────────────────
def salvar_no_anki_batch(cards, page_id, categoria):
    caminho = obter_caminho_completo(page_id)
    deck = f"Notion::{categoria}::{'::'.join(caminho)}"
    try:
        # Criar Deck
        req_deck = urllib.request.Request("http://localhost:8765", json.dumps({"action": "createDeck", "version": 6, "params": {"deck": deck}}).encode("utf-8"))
        urllib.request.urlopen(req_deck)
        # Add Notas
        notes = [{"deckName": deck, "modelName": "Basic", "fields": {"Front": c["pergunta"], "Back": c["resposta"]}, "options": {"allowDuplicate": False}} for c in cards]
        req_notes = urllib.request.Request("http://localhost:8765", json.dumps({"action": "addNotes", "version": 6, "params": {"notes": notes}}).encode("utf-8"))
        urllib.request.urlopen(req_notes)
        return True
    except: return False

def criar_pagina_consolidada(conteudo, pai_id=None):
    props = {"Name": {"title": [{"text": {"content": f"💎 Consolidado Técnico SAC - {date.today().strftime('%d/%m/%Y')}"}}]}, "Category": {"select": {"name": "SAP Meetings"}}}
    if pai_id: props["Parent item"] = {"relation": [{"id": pai_id}]}
    children = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": conteudo[:2000]}}]}}]
    nova = notion.pages.create(parent={"database_id": DATABASE_ID}, properties=props, children=children)
    return nova["id"], props["Name"]["title"][0]["text"]["content"]

# ── 4. EXECUÇÃO PRINCIPAL ───────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Motor Learning OS Iniciado...")
    paginas = buscar_paginas_marcadas()
    sap_m_txt, sap_m_tit, sap_m_ids = [], [], []

    for i, p in enumerate(paginas, 1):
        if p['categoria'] == "SAP Meetings":
            print(f"[{i}/{len(paginas)}] Agrupando reunião: {p['titulo']}")
            sap_m_txt.append(extrair_texto_pagina(p["id"]))
            sap_m_tit.append(p['titulo'])
            sap_m_ids.append(p['id'])

            if len(sap_m_ids) >= 10:
                resumo = consolidar_sap_meetings(sap_m_txt, sap_m_tit)
                if resumo:
                    n_id, n_tit = criar_pagina_consolidada(resumo, sap_m_ids[0])
                    c_cards = gerar_flashcards(resumo, n_tit)
                    if c_cards: salvar_no_anki_batch(c_cards, n_id, "SAP")
                for rid in sap_m_ids:
                    notion.pages.update(page_id=rid, properties={"⚙️ Generate Flashcards": {"checkbox": False}})
                sap_m_txt, sap_m_tit, sap_m_ids = [], [], []
        else:
            print(f"[{i}/{len(paginas)}] Processando: {p['titulo']}")
            texto = extrair_texto_pagina(p["id"])
            cards = gerar_flashcards(texto, p["titulo"])
            if cards:
                if salvar_no_anki_batch(cards, p["id"], p["categoria"]):
                    notion.pages.update(page_id=p["id"], properties={"⚙️ Generate Flashcards": {"checkbox": False}})
                    print(f"   ✅ Sucesso.")
                else: print(f"   🔴 Erro Anki (Está aberto?)")
            else:
                notion.pages.update(page_id=p["id"], properties={"⚙️ Generate Flashcards": {"checkbox": False}})
                print("   🗑️ Pulado (Sem conteúdo)")

    # Lote Residual SAP
    if sap_m_ids:
        resumo = consolidar_sap_meetings(sap_m_txt, sap_m_tit)
        if resumo:
            n_id, n_tit = criar_pagina_consolidada(resumo, sap_m_ids[0])
            c_cards = gerar_flashcards(resumo, n_tit)
            if c_cards: salvar_no_anki_batch(c_cards, n_id, "SAP")
        for rid in sap_m_ids:
            notion.pages.update(page_id=rid, properties={"⚙️ Generate Flashcards": {"checkbox": False}})

    # GERA DASHBOARD (DADOS MOCK PARA O EXEMPLO)
    dados_dash = {
        "ranked": [{"domain": "Sociais 9sem", "score": 9.8, "D":10, "R":0, "C":5, "G":0}, {"domain": "SAP Analytics Cloud", "score": 2.5, "D":0, "R":0, "C":10, "G":0}],
        "deadlines": [], "anki_total": 0, "ibm_days": 63, "ibm_date": "15/06/2026"
    }
