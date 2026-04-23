import streamlit as st
import requests
import json
from notion_client import Client
from datetime import date
import os

# 1. Configuração base da página Streamlit
st.set_page_config(page_title="Learning OS", layout="wide", page_icon="🧠")

st.title("🧠 Tactical Command Center")
st.write(f"**Data:** {date.today().strftime('%A, %d de %B de %Y')}")

# Conexões
try:
    NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
    DATABASE_ID = st.secrets["NOTION_DATABASE_ID"]
    ACADEMIC_DB_ID = st.secrets["NOTION_ACADEMIC_DB_ID"]
except (FileNotFoundError, KeyError):
    from dotenv import load_dotenv
    load_dotenv()
    NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
    DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
    ACADEMIC_DB_ID = os.environ.get("NOTION_ACADEMIC_DB_ID")

notion = Client(auth=NOTION_TOKEN)
ANKI_URL = "http://localhost:8765"

def get_anki_due_count():
    try:
        payload = {"action": "findCards", "version": 6, "params": {"query": "is:due"}}
        response = requests.post(ANKI_URL, json=payload).json()
        return len(response.get("result", []))
    except:
        return "Offline"

def get_upcoming_deadlines():
    """Busca as próximas tarefas usando a nova API do Notion (Data Sources)."""
    try:
        # 1. Recupera o Data Source associado à sua Database Acadêmica
        db_info = notion.databases.retrieve(database_id=ACADEMIC_DB_ID)
        ds_id = db_info["data_sources"][0]["id"]

        # 2. Faz a busca correta na nova estrutura
        res = notion.data_sources.query(
            data_source_id=ds_id,
            filter={"property": "Due date", "date": {"is_not_empty": True}},
            sorts=[{"property": "Due date", "direction": "ascending"}]
        )

        deadlines = []
        for r in res.get("results", []):
            try:
                name = r["properties"]["Name"]["title"][0]["plain_text"]
                dt_str = r["properties"]["Due date"]["date"]["start"]
                dt = date.fromisoformat(dt_str[:10])
                days_left = (dt - date.today()).days

                # Ignora tarefas muito antigas (já passadas)
                if days_left >= -1:
                    deadlines.append({"name": name, "date": dt.strftime("%d/%m"), "days": days_left})
            except Exception as e:
                continue

        deadlines = sorted(deadlines, key=lambda x: x["days"])[:5]
        return deadlines

    except Exception as e:
        return [{"name": f"ERRO NA API: {e}", "days": 999}]

# ── 3. MOTOR DE DECISÃO (ALGORITMO SUSTENTÁVEL) ──
anki_total = get_anki_due_count()
deadlines = get_upcoming_deadlines()
ibm_days = (date(2026, 6, 15) - date.today()).days

# Cálculo da cota diária do Anki: o hábito nunca para, apenas a intensidade muda
if isinstance(anki_total, int):
    if anki_total > 150:
        anki_cota = 50 # Avalanche: parcela máxima sustentável
        status_anki = "Avalanche (Meta: 50 hoje)"
    elif anki_total > 50:
        anki_cota = 30 # Dívida Média: foco moderado
        status_anki = "Dívida Média (Meta: 30 hoje)"
    elif anki_total > 0:
        anki_cota = anki_total # Poucos cards: manutenção rápida
        status_anki = "Manutenção (Limpar hoje)"
    else:
        anki_cota = 0
        status_anki = "Zerado 🎉"
else:
    anki_cota = 0
    status_anki = "Offline"

# Lógica de Triagem: O que você DEVE fazer hoje?
if deadlines and "ERRO" not in deadlines[0]["name"] and deadlines[0]['days'] <= 3:
    foco_dia = deadlines[0]["name"]
    foco_tipo = "🔥 Urgência Acadêmica"
    protocolo = f"1º: Revisão Anki ({anki_cota} cards). | 2º: Deep Work (90 min) exclusivo para a entrega de '{foco_dia}'."
elif deadlines and "ERRO" not in deadlines[0]["name"] and 3 < deadlines[0]['days'] <= 7:
    foco_dia = f"{deadlines[0]['name']} + SAP"
    foco_tipo = "⚖️ Balanço Tático"
    protocolo = f"1º: Revisão Anki ({anki_cota} cards). | 2º: Avançar '{deadlines[0]['name']}' (45m). | 3º: Estudo IBM/SAP (45m)."
else:
    foco_dia = "SAP Analytics / Datasphere"
    foco_tipo = "💼 Retorno IBM"
    protocolo = f"1º: Revisão Anki ({anki_cota} cards). | 2º: Foco total em arquitetura SAP/Datasphere para o retorno à IBM."

# Trunca o nome para o painel se for muito longo
foco_display = foco_dia[:22] + "..." if len(foco_dia) > 22 else foco_dia

# ── 4. PAINÉIS DE CIMA (MÉTRICAS RÁPIDAS) ──
col1, col2, col3 = st.columns(3)
col1.metric("Anki Flow", f"{anki_total} Pendentes" if anki_total != "Offline" else "Offline", status_anki, delta_color="off")
col2.metric("Missão Ordenada", foco_display, foco_tipo, delta_color="off")
col3.metric("IBM Return", f"{ibm_days} Dias", "15/06/2026")

st.divider()

# ── 5. LAYOUT TÁTICO: EXECUÇÃO VS RADAR ──
col_exec, col_radar = st.columns([2, 1])

with col_exec:
    st.subheader("🎯 Ordem de Ação")
    st.info(f"**Foco Imediato:** {foco_dia}\n\n**Protocolo Tático:** {protocolo}")

    colA, colB, colC = st.columns(3)
    with colA:
        st.link_button("📖 Abrir Workspace (Notion)", "https://www.notion.so", use_container_width=True)
    with colB:
        if anki_total == "Offline":
            st.error("Anki local fechado.")
        else:
            st.button("🧠 Iniciar Revisão (Anki)", type="primary", use_container_width=True)
    with colC:
        st.link_button("💼 Abrir Docs SAP", "https://help.sap.com/docs/SAP_ANALYTICS_CLOUD", use_container_width=True)

with col_radar:
    st.subheader("⏳ Radar (Próximos)")
    if deadlines and "ERRO" not in deadlines[0]["name"]:
        for d in deadlines:
            # Algoritmo visual de tensão
            if d['days'] <= 3:
                urgency = "🔴"
            elif d['days'] <= 10:
                urgency = "🟡"
            else:
                urgency = "🟢"
            st.markdown(f"{urgency} **{d['name']}** \n*{d['days']} dias restantes*")
    elif deadlines and "ERRO" in deadlines[0]["name"]:
        st.error(deadlines[0]["name"])
    else:
        st.write("O radar está limpo.")