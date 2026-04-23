import streamlit as st
import requests
import json
from notion_client import Client
from datetime import date

# 1. Configuração base da página Streamlit
st.set_page_config(page_title="Learning OS", layout="wide", page_icon="🧠")

st.title("🧠 Tactical Command Center")
st.write(f"**Data:** {date.today().strftime('%A, %d de %B de %Y')}")

# Conexões
notion = Client(auth=os.environ["NOTION_TOKEN"])
ANKI_URL = "http://localhost:8765"

def get_anki_due_count():
    try:
        payload = {"action": "findCards", "version": 6, "params": {"query": "is:due"}}
        response = requests.post(ANKI_URL, json=payload).json()
        return len(response.get("result", []))
    except:
        return "Offline"

def get_next_deadline():
    try:
        res = notion.databases.query(
            database_id=os.environ["NOTION_DATABASE_ID"],
            filter={"property": "Deadline", "date": {"is_not_empty": True}},
            sorts=[{"property": "Deadline", "direction": "ascending"}]
        )
        if res["results"]:
            prop = res["results"][0]["properties"]
            name = prop["Name"]["title"][0]["plain_text"]
            return name
        return "Nenhuma"
    except:
        return "Erro API"

# Atualizando o dicionário de dados reais
anki_total = get_anki_due_count()
primary_task = get_next_deadline()

dados_dash = {
    "ranked": [{"domain": primary_task, "score": 9.8}],
    "anki_total": anki_total,
    "ibm_days": (date(2026, 6, 15) - date.today()).days,
    "ibm_date": "15/06/2026"
}

# 3. Painéis de Cima (Métricas Rápidas)
col1, col2, col3 = st.columns(3)
col1.metric("Anki Flow", f"{dados_dash['anki_total']} Pendentes", "Foco em retenção")
col2.metric("Foco Acadêmico", primary_domain, "Alta Tensão")
col3.metric("IBM Return", f"{dados_dash['ibm_days']} Dias", dados_dash['ibm_date'])

st.divider()

# 4. Missão Diária (Ações Interativas)
st.subheader(f"🥇 Missão Principal: {primary_domain}")
st.info("Sessão de Deep Work. Sem notificações. Produzir 2 diamantes no Notion ao fim do bloco.")

colA, colB = st.columns(2)
with colA:
    if st.button("📖 Abrir Leitura no Notion", use_container_width=True):
        # Substitua pelo link da sua página principal de estudos
        st.link_button("Ir para o Notion", "https://www.notion.so")
with colB:
    if st.button("🧠 Começar Flashcards no Anki", use_container_width=True):
        if anki_total == "Offline":
            st.error("Abra o Anki no computador primeiro!")
        else:
            st.success("Anki conectado! Inicie a revisão pelo aplicativo.")

st.divider()

st.subheader(f"🥈 Missão Secundária: {secondary_domain}")
st.write("Avanço tático ou leitura técnica de suporte.")